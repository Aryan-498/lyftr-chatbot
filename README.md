# LLM Chatbot with Key Failover and Response Caching

A full-stack chatbot: React frontend, FastAPI backend, LiteLLM gateway (key pool with automatic failover and built-in response cache) and SQLite for session history.

## 1. Live URLs

- Frontend: https://lyftr-chatbot-six.vercel.app
- Backend: https://lyftr-chatbot-39s4.onrender.com (health check: `/health`)
- Repository: https://github.com/Aryan-498/lyftr-chatbot
- Demo video: `<PASTE VIDEO LINK>`

> The backend runs on Render's free tier. It sleeps when idle, so the first request can take up to a minute. Free instances have no persistent disk, so history there resets when the service restarts. Locally, with Docker, history persists in a named volume.

## 2. Run locally

### With Docker

```bash
cp .env.example .env        # Windows: copy .env.example .env
# edit .env and put at least 2 real keys in LLM_API_KEYS
make up                     # or: docker compose up --build -d
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000 (`/health`, `/docs`)
- Stop with `make down` (or `docker compose down`).
- SQLite lives in the `app-data` named volume mounted at `/data`, so history survives restarts.
- On Windows without `make`, use the `docker compose` commands above.

### Without Docker

Backend (Python 3.12):

```bash
cd backend
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2
export LLM_MODEL=gemini/gemini-flash-lite-latest
export DATABASE_URL=sqlite:///./app.db
export ALLOWED_ORIGINS=http://localhost:3000
export ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000
```

On Windows PowerShell, set variables with `$env:NAME="value"` instead of `export`.

Frontend (Node 20):

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

### Tests

```bash
make test        # or: cd backend && pip install -r requirements-dev.txt && python -m pytest -q
```

The tests stub LiteLLM, so they need no API keys. They cover validation (422), failover, the 503 path, caching labels, multi-turn history, session isolation and the simulation header.

### Environment variables

| Variable | Meaning |
|---|---|
| `LLM_API_KEYS` | Comma-separated key pool (at least 2). Ids are `key_1`, `key_2`, ... in this order. |
| `LLM_MODEL` | LiteLLM model name, default `gemini/gemini-flash-lite-latest`. |
| `DATABASE_URL` | SQLite location, e.g. `sqlite:////data/app.db`. |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins. |
| `ENABLE_FAILURE_SIMULATION` | `true` enables the `X-Simulate-Failure` test hook. |
| `CACHE_TYPE` | `local` (in-memory, default) or `disk` (persists in `/data/cache`). |
| `LLM_TIMEOUT` | Per-key request timeout in seconds (default 30). |
| `VITE_API_URL` | Frontend build-time URL of the backend. |

### Deploying

- **Backend:** Docker web service (Render), root directory `backend`, with the environment variables above.
- **Frontend:** Vercel, root directory `frontend`, build `npm run build`, output `dist`, env `VITE_API_URL=<backend URL>` (no trailing slash). Redeploy after changing it, because Vite bakes it in at build time.
- Set `ALLOWED_ORIGINS` on the backend to the exact frontend URL.

## 3. Design decisions

### Key fallback

- `LLM_API_KEYS` is parsed into an ordered pool (`key_1..key_n`).
- For each request the backend tries keys in order with `litellm.acompletion(api_key=...)` and `num_retries=0`, so LiteLLM never retries silently and the app controls failover.
- Any failure (HTTP 429, quota errors, 5xx, timeouts, or an empty completion) moves on to the next key. `fallback_attempts` counts the keys that failed before one succeeded.
- If every key fails, the client gets `503 {"detail":"all providers unavailable"}` and nothing is saved to history.
- Keys are never returned or logged. Only the id (`key_1`) is exposed, and logs record the error class and status code.
- A generic exception handler guarantees JSON errors, never a stack trace or an HTML page.

### Failure simulation

- `X-Simulate-Failure: key_1=429,key_2=500` or `*=429` marks keys as failed for that one request. Valid statuses are 429, 500, 502 and 503.
- It works only when `ENABLE_FAILURE_SIMULATION=true`.
- A simulated key is skipped before any provider call, so a simulated request that succeeds always returns a real answer from a real key.
- Simulated requests bypass the cache read, so the demo works even for a message that was cached earlier.

### Caching

- LiteLLM's built-in cache (`litellm.cache`), in-memory by default, with an optional disk cache.
- LiteLLM's cache key covers the model and the full message list (system prompt + history + new message). The same first message in a new session gets the same key and returns `LLM_CACHE`. Any different message misses.
- The API key is not part of the cache key, so a response cached through `key_1` is reused for any key.
- A hit is detected from the response's `cache_hit` flag. On a hit, the reply text and token counts are those stored with the cached response, `key_id` is `null` and `fallback_attempts` is 0.
- The cache is in-memory, so it resets when the backend restarts. Use `CACHE_TYPE=disk` to persist it.

### SQLite session storage

- Python's standard `sqlite3`, with the schema created on startup.
- The `messages` table matches the spec (session id, role, content, JSON metadata, ISO-8601 server time), with an index on `(session_id, id)`. A small `sessions` table holds the per-session system prompt.
- The backend stores history, so the client sends only the new message. History is loaded from SQLite for every request and sent to the LLM with the system prompt.
- A turn (user message + assistant reply) is written in a single transaction, and only after the LLM call succeeds, so failed requests (422 and 503) never touch history.
- Tokens come from the provider's usage for that one request. They are never a running total.
- `GET /sessions/{id}/messages` returns history oldest first, without the system prompt. It returns 404 for unknown sessions.

## 4. Verification

Replace `B` with `http://localhost:8000` or the live backend URL.

```bash
B=https://lyftr-chatbot-39s4.onrender.com

# health
curl $B/health

# live call -> LIVE_INFERENCE, key_id key_1
curl -s $B/chat -H 'content-type: application/json' \
  -d '{"session_id":"a","message":"Name three rivers in India"}'

# same message, new session -> LLM_CACHE, key_id null, much lower latency_ms
curl -s $B/chat -H 'content-type: application/json' \
  -d '{"session_id":"b","message":"Name three rivers in India"}'

# failover -> 200 with key_id key_2, fallback_attempts 1
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"c","message":"What is the largest ocean?"}'

# every key fails -> 503 {"detail":"all providers unavailable"}, nothing stored
curl -s -i $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"d","message":"Another new question"}'

# history, with per-message metadata
curl $B/sessions/a/messages
```

On Windows PowerShell, use `curl.exe` and escape inner quotes, or use `Invoke-RestMethod`.

In the UI:

- **Failover:** open "Session settings", type `key_1=429` in the failure field and send a new message. The reply shows `key_2 (after 1 failed)`.
- **Cache hit:** open the app in a new tab (a new session) and send the same message again. The reply shows `LLM_CACHE` and a much lower latency.
- **Per-message token usage:** every reply shows input and output tokens for that request only.
- **Errors:** `*=429` shows a readable error in the chat, not a blank screen.

## 5. Setup used

- Editor: `<e.g. VS Code>`
- AI tools: `<e.g. Claude for planning and code generation>`
- Tooling: Docker Desktop, Git, Render (backend), Vercel (frontend)

## 6. Bonus features

- **Per-session system prompt:** an optional field in the UI. It is stored per session in SQLite and applied to later messages.
- **Failure simulation field in the UI:** lets you demonstrate failover without using the command line.
- **Optional disk cache:** `CACHE_TYPE=disk` persists cached responses across restarts.
- **Error handling:** a React error boundary and a global backend exception handler ensure users never see a blank screen, an HTML error page or a stack trace.
- **Health check:** `/health` returns 503 if the database is unreachable or no keys are configured.