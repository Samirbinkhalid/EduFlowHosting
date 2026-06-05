# EduFlow AI — Agent Context

## Project
Recordings upload → FFmpeg audio extract → ElevenLabs STT → R2 + PostgreSQL sync.
Auth: Google OAuth/OIDC via authlib. Upload gated by external webhook (USERS_URL).
Admin dashboard at /dbstatus.

## Stack
Vanilla HTML/CSS/JS + FastAPI (port 8090) + SQLite (WAL) + PostgreSQL + Cloudflare R2.
TUS resumable upload. Docker Compose for prod.

## DO NOT MODIFY
- `ui/app.js` — drop-zone, TUS upload, health check, auth logic
- `ui/monitor.js` — table rendering, /dbstatus/data fetch
- `ui/tus.min.js`, `ui/fonts.css`
- Inline scripts in `index.html` (Vanta, star field, ECG, theme toggle, checkAuth)
- All `id` attrs referenced by JS: `dropZone, fileInput, uploadBtn, uploadBtnLabel, uploadFeedback, uploadError, uploadProgressWrap, uploadProgressBar, uploadStatus, sysStatus, authBtn, authSub`

## Schema (SQLite)
- `uploads(uuid PK, user_email, user_name, created_at, is_processed{0=pending,1=done,2=in-progress,-1=failed}, retry_count)`
- `transcriptions(uuid PK, user_email, user_name, created_at, is_processed{0=pending,1=synced,2=in-progress,-1=failed}, retry_count)`

## API
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/` | No | Serves index.html |
| GET | `/auth/login` | No | Google OAuth2 redirect |
| GET | `/auth` | No | OAuth2 callback |
| GET | `/auth/logout` | No | Clear session |
| GET | `/auth/me` | No | Session info |
| POST/PATCH/HEAD | `/upload/[/{id}]` | Yes | TUS upload |
| GET | `/dbstatus` | Admin | Monitor page |
| GET | `/dbstatus/data` | Admin | JSON stats |

## Env Config
See `.env.example`: GOOGLE_CLIENT_ID/SECRET, APP_BASE_URL, SESSION_SECRET_KEY, HTTPS_ONLY,
ADMIN_EMAILS, USERS_URL, DATA_DIR, UPLOADS_DIR, TUS_UPLOADS_DIR, TRANSCRIPTIONS_DIR,
ELEVENLABS_API_KEY, R2_*, POSTGRES_*, MAX_TRANSCRIPTION_RETRIES, MAX_SYNC_RETRIES

## Pipeline
TUS receive → FFmpeg→.m4a → ElevenLabs→.txt → R2 upload → PG sync.
Bkg threads: `scheduler.py` (transcription), `sync_scheduler.py` (R2+PG).

## Key Rules
- `author_name`/`author_email` always from server-side session, never client metadata
- File UUID = correlation key across all pipeline stages
- Temp files deleted after processing
- Session cookie: signed+encrypted, only store existing claims
- Monitor page scrollable, main page `overflow:hidden 100vh`
- Run: `uv run dev` (dev), `uv run serve` (prod), `docker compose up --build`
