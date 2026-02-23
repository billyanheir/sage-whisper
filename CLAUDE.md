# Sage Whisper - Claude Session Notes

## Governing Documents
ALL work MUST follow:
1. `Python API Prompt.txt` - Senior Python API architect workflow
   - Architecture first, code second
   - Small, incremental steps: build, test, deploy, smoke test, extend
   - Mandatory pytest unit tests for every change
   - Ruff formatting/linting, mypy type checking
   - OWASP API Top 10 compliance, defence-in-depth
   - Python 3.10, FastAPI, SQLite via SQLAlchemy, Alembic, Pydantic

2. `templates/base.html` - UI conventions:
   - Tailwind CSS (via CDN), HTMX 1.9.10, Alpine.js
   - Dark glass nav bar with cyan accent branding
   - Navy/cyan/indigo colour scheme, card-elevated pattern
   - Toast notifications, HTMX loading states
   - Responsive with mobile hamburger menu

## Database Rules
- SQLite for simplicity (single-file, no server)
- DATABASE_URL defaults to `sqlite:///./sage_whisper.db`
- Alembic migrations for schema changes

## Architecture Notes
- main.py: FastAPI entry point with web routes + API router includes
- app/routers/: API endpoints (auth, voice_notes, transcripts)
- app/services/: Business logic (auth, jwt, voice_note, transcription, transcript)
- app/models/: SQLAlchemy models (user, voice_note, transcript)
- app/schemas/: Pydantic request/response schemas
- JWT cookie-based auth (simplified, no multi-database)
- faster-whisper for local transcription (no API keys)

## Test Coverage
- pytest with in-memory SQLite
- All auth flows tested
- Upload validation tested
- Transcription flow tested (mocked faster-whisper)

## CI/CD Target
- GitHub Actions (future)
- No containers
