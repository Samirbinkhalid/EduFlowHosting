# MentorMind — Agent Context

## Project Overview

MentorMind is a web application that allows authenticated users to upload screen/session recordings.
The system extracts audio from the recording, transcribes it via ElevenLabs, and persists the
transcript along with file metadata to PostgreSQL.

The landing page is a login gate. After authentication via Azure SSO the user is redirected to
the home UI (`/ui/index.html`) where they can upload recordings. Access to the upload feature is
permission-gated per user.

---

## Tech Stack

| Layer           | Technology                                  |
|-----------------|---------------------------------------------|
| Frontend        | Vanilla HTML/CSS/JS (`ui/index.html`)        |
| Backend         | FastAPI (Python 3.x) served on port `8090`  |
| Auth            | Azure AD / Microsoft Entra ID (OAuth 2.0 / OIDC) via `authlib` |
| Session         | Signed & encrypted cookie via Starlette `SessionMiddleware` |
| File Upload     | TUS resumable upload protocol (JS client → FastAPI TUS server) |
| Audio Extraction| FFmpeg — extracts audio stream to `.m4a`    |
| Transcription   | ElevenLabs API                              |
| Database        | PostgreSQL                                  |
| Config          | `python-dotenv` / environment variables     |
| Container       | Docker / Docker Compose                     |

---

## Repository Layout

```
codeline_sso_web_app/
├── app/
│   ├── main.py               # FastAPI app factory, middleware, root routes
│   ├── config.py             # Settings loaded from environment variables
│   ├── auth/
│   │   ├── dependencies.py   # get_current_user / get_optional_user FastAPI deps
│   │   └── oauth_client.py   # authlib OAuth client configured for Microsoft
│   └── routers/
│       └── auth.py           # /auth/login, /auth/ (callback), /auth/logout, /auth/me
├── ui/
│   └── index.html            # Home page (post-login); upload UI (drag-drop + button)
├── .env.example              # Required environment variable template
├── docker-compose.yml        # Single-service compose (image: codelineatyab/mentormindweb-app)
├── Dockerfile
├── pyproject.toml
└── requirements.txt
```

---

## Authentication Flow

1. User visits the landing page (`/`). If not logged in, they see a welcome prompt with a link to `/auth/login`.
2. `GET /auth/login` — FastAPI redirects browser to Microsoft's OAuth2 authorize endpoint. `authlib` automatically writes a CSCSRF `state` nonce into the session cookie.
3. Microsoft authenticates the user and redirects back to `GET /auth` (the registered redirect URI: `{APP_BASE_URL}/auth`).
4. `authlib` validates `state`, exchanges the authorization code for tokens, and verifies the ID token signature.
5. The following claims are written into the session cookie:
   - `sub` — unique Microsoft object ID
   - `email` / `preferred_username`
   - `name`, `given_name`, `family_name`
   - `tid` — Azure tenant ID
6. User is redirected to `POST_LOGIN_REDIRECT` (default `/`).
7. The home page (`/`) and all protected routes read `request.session["user"]`.
8. `GET /auth/logout` clears the local session and redirects to Microsoft's front-channel logout URL.

### Key Config Properties (`app/config.py`)

| Property                  | Description                                              |
|---------------------------|----------------------------------------------------------|
| `AZURE_CLIENT_ID`         | Azure App Registration client ID                        |
| `AZURE_CLIENT_SECRET`     | Azure App Registration client secret                    |
| `AZURE_TENANT_ID`         | Tenant ID (`"common"` for multi-tenant)                 |
| `APP_BASE_URL`            | Public URL; must match Azure redirect URI exactly       |
| `SESSION_SECRET_KEY`      | Signs/encrypts the session cookie                       |
| `POST_LOGIN_REDIRECT`     | Where to land after successful login (default `/`)      |
| `POST_LOGOUT_REDIRECT`    | Where to land after logout (default `/`)                |
| `redirect_uri` (property) | `{APP_BASE_URL}/auth`                                   |

---

## Frontend — `ui/index.html`

The home page is served after login. It must:

- **Display user info** — show the logged-in user's `name` and `email` (fetched from `GET /auth/me`).
- **Permission gate** — call a backend endpoint (to be implemented) that returns whether the current user has permission to upload recordings. Show or hide the upload panel based on the response.
- **Upload panel** — drag-and-drop zone and a file-picker button. Accepted formats: `MP4`, `M4A`.
- **TUS upload** — use the [tus-js-client](https://github.com/tus/tus-js-client) library to upload files to the FastAPI TUS endpoint in resumable chunks.
- **Upload status** — display progress bar and status messages.

---

## Backend — Upload Pipeline

### 1. TUS File Reception (`POST /upload/`)

- Implement a TUS server endpoint in FastAPI.
- Accept resumable uploads from the JS client.
- Store uploads **temporarily** (temp directory or object store). Files are transient — they are cleaned up after processing.
- TUS metadata should capture at minimum: original filename, file size, content type.

### 2. Audio Extraction (`ffmpeg`)

After the TUS upload completes:

1. Invoke `ffmpeg` to extract only the audio stream from the uploaded video file.
2. Output format: `.m4a` (AAC audio in an MP4 container).
3. Example command:
   ```
   ffmpeg -i <input_file> -vn -acodec copy <output_uuid>.m4a
   ```
4. The original video file can be deleted after successful extraction.

### 3. Transcription (ElevenLabs API)

1. Send the `.m4a` audio file to the ElevenLabs Speech-to-Text API.
2. Receive the transcript text.
3. Delete the temporary `.m4a` file after a successful API response.

### 4. Persistence (PostgreSQL)

Save the transcript and metadata to PostgreSQL. Table name TBD (configure later).

**Schema (columns):**

| Column         | Type        | Notes                                          |
|----------------|-------------|------------------------------------------------|
| `id`           | `UUID`      | Primary key; generated server-side (`uuid4`)  |
| `transcript`   | `TEXT`      | Full transcript text returned by ElevenLabs   |
| `author_name`  | `VARCHAR`   | `name` claim from the authenticated session   |
| `author_email` | `VARCHAR`   | `email` claim from the authenticated session  |
| `created_at`   | `TIMESTAMP` | UTC timestamp of insertion                    |

---

## Permission System (Planned)

A backend endpoint (e.g. `GET /user/permissions`) should return whether the logged-in user is
authorised to upload recordings. This is checked by the frontend immediately after login.
Implementation details (e.g. an allowlist table, Azure group membership, etc.) are TBD.

---

## API Surface (Current + Planned)

| Method | Path                | Auth Required | Description                              |
|--------|---------------------|---------------|------------------------------------------|
| `GET`  | `/`                 | No            | Root; returns greeting or user info      |
| `GET`  | `/protected`        | Yes           | Example protected endpoint               |
| `GET`  | `/auth/login`       | No            | Initiates Azure OAuth2 redirect          |
| `GET`  | `/auth/`            | No            | OAuth2 callback; sets session            |
| `GET`  | `/auth/logout`      | No            | Clears session; redirects to MS logout   |
| `GET`  | `/auth/me`          | No            | Returns `{authenticated, user}` from session |
| `POST` | `/upload/`          | Yes (TBD)     | TUS upload creation endpoint             |
| `PATCH`| `/upload/{id}`      | Yes (TBD)     | TUS upload continuation endpoint         |
| `HEAD` | `/upload/{id}`      | Yes (TBD)     | TUS upload offset query                  |
| `GET`  | `/user/permissions` | Yes (TBD)     | Returns upload permission for current user |

---

## Environment Variables (Full Set)

Copy `.env.example` to `.env` and populate:

```dotenv
# Azure AD
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
AZURE_TENANT_ID=

# App
APP_BASE_URL=https://mentormindweb.thedevrelay.com
SESSION_SECRET_KEY=                  # python -c "import secrets; print(secrets.token_hex(32))"
POST_LOGIN_REDIRECT=/
POST_LOGOUT_REDIRECT=/

# Database (to be added)
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname

# ElevenLabs (to be added)
ELEVENLABS_API_KEY=
```

---

## Running the App

**Development**
```bash
uv run dev        # hot-reload on port 8090
```

**Production**
```bash
uv run serve      # 4 workers, port 8090, proxy-headers enabled
```

**Docker**
```bash
docker compose up --build
```

The container exposes port `8090`. The healthcheck polls `GET /auth/me` every 30 s.

---

## Key Implementation Notes for Agents

- **Session cookie** is signed + encrypted. Never store sensitive secrets inside it beyond what is already there (`sub`, `email`, `name`, `given_name`, `family_name`, `tid`).
- **TUS uploads are temporary.** Do not persist the raw video — only the extracted `.m4a` is needed, and only until ElevenLabs responds.
- **FFmpeg audio extraction** should use `-acodec copy` where possible (stream copy, no re-encode) for speed. Fall back to `-acodec aac` if the source audio codec is not AAC-compatible.
- **ElevenLabs transcription** should be called asynchronously (FastAPI `BackgroundTasks` or a task queue) so the HTTP response to the upload does not block on the full pipeline.
- **PostgreSQL integration** should use `asyncpg` (async driver) via SQLAlchemy async session or `databases` library to stay non-blocking inside FastAPI.
- **`author_name` and `author_email`** must always be read from the server-side session (`request.session["user"]`), never trusted from client-supplied metadata.
- The `ui/index.html` currently has no JS fetch calls to the backend — those need to be added (user info display, permission check, TUS upload wiring).
