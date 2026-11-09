"""BRD (Business Requirements Document) models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class BRD(Base):
    """Business Requirements Document generated from a transcript."""

    __tablename__ = "brd"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transcript_id = Column(Integer, ForeignKey("transcript.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    status = Column(String(32), nullable=False, default="generating")  # generating, review, finalized
    project_context = Column(Text, nullable=True)
    github_repo_url = Column(String(1024), nullable=True)
    parent_brd_id = Column(Integer, ForeignKey("brd.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)


class BRDRequirement(Base):
    """Individual requirement within a BRD."""

    __tablename__ = "brd_requirement"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brd_id = Column(Integer, ForeignKey("brd.id"), nullable=False, index=True)
    requirement_text = Column(Text, nullable=False)
    category = Column(String(128), nullable=False, default="General")
    priority = Column(String(32), nullable=False, default="should")  # must, should, could, wont
    status = Column(String(32), nullable=False, default="pending")  # pending, approved, rejected, edited
    sort_order = Column(Integer, nullable=False, default=0)
    parent_id = Column(Integer, ForeignKey("brd_requirement.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
