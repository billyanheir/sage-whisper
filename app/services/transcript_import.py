"""Transcript file import service for .txt, .vtt, and .srt files."""

import re
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_IMPORT_EXTENSIONS = {".txt", ".vtt", ".srt"}
ALLOWED_IMPORT_MIME_TYPES = {
    "text/plain",
    "text/vtt",
    "text/srt",
    "application/x-subrip",
    "application/octet-stream",
}


@dataclass
class ParsedSegment:
    """A single timestamped segment from a transcript file."""

    index: int
    start_time: float
    end_time: float
    text: str


@dataclass
class ParsedTranscript:
    """Result of parsing a transcript file."""

    full_text: str
    segments: list[ParsedSegment] = field(default_factory=list)
    language: str | None = None


# Regex for HTML tag stripping
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# WebVTT timestamp: 00:01:23.456 or 01:23.456
_VTT_TIMESTAMP_RE = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})")

# SRT timestamp: 00:01:23,456 --> 00:01:27,890
_SRT_TIMESTAMP_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _strip_html(text: str) -> str:
    """Remove HTML/formatting tags from subtitle text."""
    return _HTML_TAG_RE.sub("", text)


def _timestamp_to_seconds(hours: int, minutes: int, seconds: int, millis: int) -> float:
    """Convert timestamp components to seconds."""
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


class TranscriptImportService:
    """Parses imported transcript files (.txt, .vtt, .srt)."""

    def validate_import_metadata(self, filename: str, content_type: str | None) -> str | None:
        """Validate import file metadata. Returns error message or None if valid."""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_IMPORT_EXTENSIONS:
            return f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_IMPORT_EXTENSIONS))}"

        if content_type and content_type not in ALLOWED_IMPORT_MIME_TYPES and not content_type.startswith("text/"):
            return f"Invalid content type '{content_type}'. Must be a text file."

        return None

    def parse_file(self, content: str, filename: str) -> ParsedTranscript:
        """Parse a transcript file based on its extension."""
        ext = Path(filename).suffix.lower()
        if ext == ".vtt":
            return self._parse_vtt(content)
        elif ext == ".srt":
            return self._parse_srt(content)
        else:
            return self._parse_txt(content)

    def _parse_txt(self, content: str) -> ParsedTranscript:
        """Parse a plain text transcript. No segments."""
        text = content.strip()
        if not text:
            raise ValueError("Transcript file is empty")
        return ParsedTranscript(full_text=text)

    def _parse_vtt(self, content: str) -> ParsedTranscript:
        """Parse a WebVTT file into segments."""
        lines = content.splitlines()
        segments: list[ParsedSegment] = []
        text_parts: list[str] = []
        index = 0

        i = 0
        # Skip WEBVTT header and any metadata lines
        while i < len(lines) and not _VTT_TIMESTAMP_RE.search(lines[i]):
            i += 1

        while i < len(lines):
            line = lines[i]
            match = _VTT_TIMESTAMP_RE.search(line)
            if match:
                start_h = int(match.group(1) or 0)
                start_m = int(match.group(2))
                start_s = int(match.group(3))
                start_ms = int(match.group(4))
                end_h = int(match.group(5) or 0)
                end_m = int(match.group(6))
                end_s = int(match.group(7))
                end_ms = int(match.group(8))

                start_time = _timestamp_to_seconds(start_h, start_m, start_s, start_ms)
                end_time = _timestamp_to_seconds(end_h, end_m, end_s, end_ms)

                # Collect text lines until blank line or end
                i += 1
                seg_lines: list[str] = []
                while i < len(lines) and lines[i].strip():
                    seg_lines.append(_strip_html(lines[i].strip()))
                    i += 1

                seg_text = " ".join(seg_lines)
                if seg_text:
                    segments.append(ParsedSegment(index=index, start_time=start_time, end_time=end_time, text=seg_text))
                    text_parts.append(seg_text)
                    index += 1
            else:
                i += 1

        full_text = " ".join(text_parts)
        if not full_text.strip():
            raise ValueError("Transcript file is empty")

        return ParsedTranscript(full_text=full_text, segments=segments)

    def _parse_srt(self, content: str) -> ParsedTranscript:
        """Parse an SRT (SubRip) file into segments."""
        # Split into blocks separated by blank lines
        blocks = re.split(r"\n\s*\n", content.strip())
        segments: list[ParsedSegment] = []
        text_parts: list[str] = []
        index = 0

        for block in blocks:
            block_lines = block.strip().splitlines()
            if len(block_lines) < 2:
                continue

            # Find the timestamp line
            timestamp_line_idx = None
            for j, bl in enumerate(block_lines):
                if _SRT_TIMESTAMP_RE.search(bl):
                    timestamp_line_idx = j
                    break

            if timestamp_line_idx is None:
                continue

            match = _SRT_TIMESTAMP_RE.search(block_lines[timestamp_line_idx])
            if not match:
                continue

            start_time = _timestamp_to_seconds(
                int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
            )
            end_time = _timestamp_to_seconds(
                int(match.group(5)), int(match.group(6)), int(match.group(7)), int(match.group(8))
            )

            # Text lines follow the timestamp
            seg_lines = [_strip_html(line.strip()) for line in block_lines[timestamp_line_idx + 1 :] if line.strip()]
            seg_text = " ".join(seg_lines)

            if seg_text:
                segments.append(ParsedSegment(index=index, start_time=start_time, end_time=end_time, text=seg_text))
                text_parts.append(seg_text)
                index += 1

        full_text = " ".join(text_parts)
        if not full_text.strip():
            raise ValueError("Transcript file is empty")

        return ParsedTranscript(full_text=full_text, segments=segments)


_transcript_import_service: TranscriptImportService | None = None


def get_transcript_import_service() -> TranscriptImportService:
    """Get singleton transcript import service instance."""
    global _transcript_import_service
    if _transcript_import_service is None:
        _transcript_import_service = TranscriptImportService()
    return _transcript_import_service
