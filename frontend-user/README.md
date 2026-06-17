# TerraMind — Config Portal (`frontend-user/`)

The player-facing **config** surface (D-011). **Not a chat surface** — chat
happens in-game via the mod. Vite + React + TypeScript.

## What it does
- **Log in / register / continue as guest** — JWT pair stored client-side; the
  password is never persisted.
- **Pick a wiki corpus version** (`GET /versions`).
- **Read/update preferences** (`GET`/`PATCH /me/preferences`) — persists across reload.
- **Erase your data** (`DELETE /me`) behind a confirm step.
- **401 → silent `/auth/refresh` + retry**, else bounce to login. Guests are
  access-only (no refresh).

## Run with the stack (Docker)
The portal needs the API up (for CORS + the endpoints):

```bash
docker compose up -d --build api frontend-user
# portal → http://localhost:5173    API → http://localhost:8000
```

## Run locally (dev)
```bash
cd frontend-user
npm install
npm run dev     # http://localhost:5173 → talks to http://localhost:8000
```
Override the API base with `VITE_API_BASE_URL` (default `http://localhost:8000`).

## Notes
- **Design-token SKILL unavailable** in the build environment — built with
  standard React/CSS defaults (clean, labeled forms, loading/error states,
  basic responsive), per the approved Phase-5.1 plan.
- Only the JWT pair is persisted (`localStorage`); all other state is React state.
- Stored `selected_version` is **not yet consumed by `/bot/ask`** retrieval (P-017).
