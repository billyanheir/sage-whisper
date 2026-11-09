"""BRD service for generation, review, and export."""

import json
import logging
import re
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.brd import BRD, BRDRequirement
from app.models.transcript import Transcript

logger = logging.getLogger("sage_whisper")


class BRDService:
    """Handles BRD generation, requirement management, and Markdown export."""

    def generate_brd(self, db: Session, brd_id: int) -> None:
        """Generate requirements from transcript via Ollama. Called from background thread."""
        brd = db.query(BRD).filter(BRD.id == brd_id).first()
        if not brd:
            logger.error("BRD %d not found for generation", brd_id)
            return

        transcript = db.query(Transcript).filter(Transcript.id == brd.transcript_id).first()
        if not transcript:
            logger.error("Transcript %d not found for BRD %d", brd.transcript_id, brd_id)
            brd.status = "review"
            db.commit()
            return

        # Build context
        github_context = ""
        if brd.github_repo_url:
            github_context = self._fetch_github_context(brd.github_repo_url)

        existing_requirements: list[str] = []
        if brd.parent_brd_id:
            parent_reqs = (
                db.query(BRDRequirement)
                .filter(BRDRequirement.brd_id == brd.parent_brd_id, BRDRequirement.status == "approved")
                .order_by(BRDRequirement.sort_order)
                .all()
            )
            existing_requirements = [r.requirement_text for r in parent_reqs]

        prompt = self._build_prompt(
            transcript_text=transcript.full_text,
            project_context=brd.project_context or "",
            github_context=github_context,
            existing_requirements=existing_requirements,
        )

        try:
            response_text = self._call_ollama(prompt)
            requirements = self._parse_requirements(response_text)
        except Exception:
            logger.exception("Ollama call failed for BRD %d", brd_id)
            requirements = []

        for i, req in enumerate(requirements):
            db_req = BRDRequirement(
                brd_id=brd_id,
                requirement_text=req.get("requirement", ""),
                category=req.get("category", "General"),
                priority=req.get("priority", "should"),
                status="pending",
                sort_order=i,
                created_at=datetime.utcnow(),
            )
            db.add(db_req)

        brd.status = "review"
        db.commit()
        logger.info("BRD %d generation complete with %d requirements", brd_id, len(requirements))

    def get_brd(self, db: Session, brd_id: int, user_id: int) -> dict | None:
        """Get BRD with all requirements."""
        brd = db.query(BRD).filter(BRD.id == brd_id, BRD.user_id == user_id).first()
        if not brd:
            return None

        requirements = (
            db.query(BRDRequirement).filter(BRDRequirement.brd_id == brd_id).order_by(BRDRequirement.sort_order).all()
        )

        return {
            "id": brd.id,
            "transcript_id": brd.transcript_id,
            "user_id": brd.user_id,
            "title": brd.title,
            "status": brd.status,
            "project_context": brd.project_context,
            "github_repo_url": brd.github_repo_url,
            "parent_brd_id": brd.parent_brd_id,
            "created_at": brd.created_at,
            "finalized_at": brd.finalized_at,
            "requirements": requirements,
        }

    def get_user_brds(self, db: Session, user_id: int) -> list[BRD]:
        """Get all BRDs for a user."""
        return db.query(BRD).filter(BRD.user_id == user_id).order_by(BRD.created_at.desc()).all()

    def get_finalized_brds(self, db: Session, user_id: int) -> list[BRD]:
        """Get finalized BRDs for a user (for parent BRD dropdown)."""
        return (
            db.query(BRD)
            .filter(BRD.user_id == user_id, BRD.status == "finalized")
            .order_by(BRD.created_at.desc())
            .all()
        )

    def update_requirement(
        self, db: Session, requirement_id: int, user_id: int, updates: dict
    ) -> BRDRequirement | None:
        """Update a requirement (approve, edit, reject)."""
        req = (
            db.query(BRDRequirement)
            .join(BRD, BRDRequirement.brd_id == BRD.id)
            .filter(BRDRequirement.id == requirement_id, BRD.user_id == user_id)
            .first()
        )
        if not req:
            return None

        if "status" in updates:
            req.status = updates["status"]
        if "requirement_text" in updates and updates["requirement_text"] is not None:
            req.requirement_text = updates["requirement_text"]
            if req.status == "pending":
                req.status = "edited"
        if "category" in updates and updates["category"] is not None:
            req.category = updates["category"]
        if "priority" in updates and updates["priority"] is not None:
            req.priority = updates["priority"]

        db.commit()
        db.refresh(req)
        return req

    def split_requirement(self, db: Session, requirement_id: int, user_id: int) -> list[BRDRequirement]:
        """Split a requirement into sub-requirements via Ollama."""
        req = (
            db.query(BRDRequirement)
            .join(BRD, BRDRequirement.brd_id == BRD.id)
            .filter(BRDRequirement.id == requirement_id, BRD.user_id == user_id)
            .first()
        )
        if not req:
            return []

        # Get transcript context for better splitting
        brd = db.query(BRD).filter(BRD.id == req.brd_id).first()
        transcript_text = ""
        if brd:
            transcript = db.query(Transcript).filter(Transcript.id == brd.transcript_id).first()
            if transcript:
                transcript_text = transcript.full_text

        prompt = self._build_split_prompt(req.requirement_text, transcript_text)

        try:
            response_text = self._call_ollama(prompt)
            sub_requirements = self._parse_requirements(response_text)
        except Exception:
            logger.exception("Ollama split failed for requirement %d", requirement_id)
            return []

        # Mark parent as rejected
        req.status = "rejected"

        # Get max sort_order for insertion
        max_order = req.sort_order

        children = []
        for i, sub_req in enumerate(sub_requirements):
            child = BRDRequirement(
                brd_id=req.brd_id,
                requirement_text=sub_req.get("requirement", ""),
                category=sub_req.get("category", req.category),
                priority=sub_req.get("priority", req.priority),
                status="pending",
                sort_order=max_order + i + 1,
                parent_id=req.id,
                created_at=datetime.utcnow(),
            )
            db.add(child)
            children.append(child)

        db.commit()
        for child in children:
            db.refresh(child)
        return children

    def finalize_brd(self, db: Session, brd_id: int, user_id: int) -> BRD | None:
        """Finalize a BRD after review."""
        brd = db.query(BRD).filter(BRD.id == brd_id, BRD.user_id == user_id).first()
        if not brd:
            return None
        brd.status = "finalized"
        brd.finalized_at = datetime.utcnow()
        db.commit()
        db.refresh(brd)
        return brd

    def generate_markdown(self, db: Session, brd_id: int, user_id: int) -> str | None:
        """Render approved requirements as formatted Markdown."""
        brd_data = self.get_brd(db, brd_id, user_id)
        if not brd_data:
            return None

        lines = []
        lines.append(f"# {brd_data['title']}")
        lines.append("")
        lines.append(f"**Status:** {brd_data['status']}")
        lines.append(f"**Created:** {brd_data['created_at'].strftime('%Y-%m-%d %H:%M')}")
        if brd_data["finalized_at"]:
            lines.append(f"**Finalized:** {brd_data['finalized_at'].strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Group requirements by category
        approved = [r for r in brd_data["requirements"] if r.status in ("approved", "edited")]
        categories: dict[str, list] = {}
        for req in approved:
            cat = req.category or "General"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(req)

        if not categories:
            lines.append("*No approved requirements.*")
        else:
            for category, reqs in categories.items():
                lines.append(f"## {category}")
                lines.append("")
                for req in reqs:
                    priority_label = req.priority.upper() if req.priority else "SHOULD"
                    lines.append(f"- **[{priority_label}]** {req.requirement_text}")
                lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*Generated by Sage Whisper*")

        return "\n".join(lines)

    def _call_ollama(self, prompt: str) -> str:
        """Send prompt to Ollama and return response text."""
        settings = get_settings()
        url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }
        response = httpx.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
        return response.json().get("response", "")

    def _fetch_github_context(self, repo_url: str) -> str:
        """Fetch README and top-level file structure from GitHub."""
        match = re.match(r"https?://github\.com/([^/]+/[^/]+)", repo_url.rstrip("/"))
        if not match:
            logger.warning("Could not parse GitHub URL: %s", repo_url)
            return ""

        owner_repo = match.group(1)
        context_parts = []

        try:
            # Fetch top-level file list
            contents_resp = httpx.get(
                f"https://api.github.com/repos/{owner_repo}/contents/",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=15.0,
            )
            if contents_resp.status_code == 200:
                files = contents_resp.json()
                file_list = "\n".join(f"  - {f['name']} ({f['type']})" for f in files)
                context_parts.append(f"## Repository Structure\n{file_list}")
        except Exception:
            logger.warning("Failed to fetch GitHub contents for %s", owner_repo)

        try:
            # Fetch README
            readme_resp = httpx.get(
                f"https://api.github.com/repos/{owner_repo}/readme",
                headers={"Accept": "application/vnd.github.raw"},
                timeout=15.0,
            )
            if readme_resp.status_code == 200:
                readme_text = readme_resp.text[:5000]  # Limit README size
                context_parts.append(f"## README\n{readme_text}")
        except Exception:
            logger.warning("Failed to fetch GitHub README for %s", owner_repo)

        return "\n\n".join(context_parts)

    def _build_prompt(
        self,
        transcript_text: str,
        project_context: str,
        github_context: str,
        existing_requirements: list[str],
    ) -> str:
        """Assemble the full LLM prompt for requirement extraction."""
        sections = []

        sections.append(
            "You are a business analyst. Extract business requirements from the following meeting transcript. "
            "Return ONLY a JSON array of objects with these fields: "
            '"requirement" (clear requirement statement), '
            '"category" (e.g. Functional, Non-Functional, UI/UX, Security, Performance, Integration, Data), '
            '"priority" (must, should, could, or wont based on MoSCoW prioritization). '
            "Be specific and actionable. Each requirement should be a single, testable statement."
        )

        if project_context:
            sections.append(f"## Existing System Context\n{project_context}")

        if github_context:
            sections.append(f"## Repository Context\n{github_context}")

        if existing_requirements:
            req_list = "\n".join(f"- {r}" for r in existing_requirements)
            sections.append(
                f"## Previously Captured Requirements\n"
                f"The following requirements are already documented. Focus on NEW or CHANGED requirements:\n{req_list}"
            )

        sections.append(f"## Meeting Transcript\n{transcript_text}")

        sections.append(
            "## Output\nReturn ONLY a valid JSON array. Example format:\n"
            '[{"requirement": "The system must ...", "category": "Functional", "priority": "must"}]'
        )

        return "\n\n".join(sections)

    def _build_split_prompt(self, requirement_text: str, transcript_text: str) -> str:
        """Build prompt to split a requirement into sub-requirements."""
        sections = []

        sections.append(
            "You are a business analyst. Break the following requirement into smaller, more specific sub-requirements. "
            "Return ONLY a JSON array of objects with these fields: "
            '"requirement" (clear sub-requirement statement), '
            '"category" (e.g. Functional, Non-Functional, UI/UX, Security, Performance, Integration, Data), '
            '"priority" (must, should, could, or wont). '
            "Each sub-requirement should be independently testable."
        )

        sections.append(f"## Requirement to Split\n{requirement_text}")

        if transcript_text:
            # Include truncated transcript for context
            truncated = transcript_text[:3000]
            sections.append(f"## Original Transcript Context\n{truncated}")

        sections.append(
            "## Output\nReturn ONLY a valid JSON array. Example format:\n"
            '[{"requirement": "The system must ...", "category": "Functional", "priority": "must"}]'
        )

        return "\n\n".join(sections)

    def _parse_requirements(self, response_text: str) -> list[dict]:
        """Parse LLM response into list of requirement dicts."""
        # Try direct JSON parse first
        try:
            result = json.loads(response_text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Try to extract JSON array from response text
        match = re.search(r"\[.*\]", response_text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse requirements from Ollama response")
        return []


_brd_service: BRDService | None = None


def get_brd_service() -> BRDService:
    """Get singleton BRD service instance."""
    global _brd_service
    if _brd_service is None:
        _brd_service = BRDService()
    return _brd_service
