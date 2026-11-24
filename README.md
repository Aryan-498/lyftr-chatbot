# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + LiteLLM + SQLite.

## 1. Live URLs
- Frontend: `TODO`
- Backend: `TODO` (try `/health`)
- Demo video: `TODO`

## 2. Run locally
**Docker:** `cp .env.example .env`, add 2+ real keys to `LLM_API_KEYS`, then `make up`.
Frontend http://localhost:3000, backend http://localhost:8000. `make down` stops it. History lives in the `app-data` volume at `/data/app.db`.

**Without Docker:**
```bash
cd backend && pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db ALLOWED_ORIGINS=http://localhost:3000 ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000
# new terminal
cd frontend && npm install && VITE_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```
Tests: `make test` (LiteLLM is stubbed, no keys needed).

**Deploying:** backend as a Docker web service (Render/Railway/Fly; attach a disk at `/data` for persistent history; set `LLM_API_KEYS`, `ALLOWED_ORIGINS=<frontend URL>`, `ENABLE_FAILURE_SIMULATION=true`). Frontend on Vercel/Netlify with root `frontend`, build `npm run build`, output `dist`, env `VITE_API_URL=<backend URL>`.

## 3. Design decisions
- **Key fallback:** `LLM_API_KEYS` is parsed into `key_1..key_n`. For each request the backend tries keys in order with `litellm.acompletion(api_key=...)`, `num_retries=0`. Any exception (429, quota, 5xx, timeout) or empty completion moves to the next key; if all fail the client gets `503 {"detail":"all providers unavailable"}`. Keys are never logged or returned. `X-Simulate-Failure` (only when `ENABLE_FAILURE_SIMULATION=true`) marks keys as failed before calling the provider and bypasses the cache for that request, so a simulated request always returns a real live answer.
- **Caching:** LiteLLM's built-in cache (`litellm.cache`, in-memory by default, `CACHE_TYPE=disk` to persist). The key is derived from model + full message list (system + history + new message), so the same first message in a new session hits the cache and any different message does not. The key does not depend on which API key is used. A hit is detected via `_hidden_params["cache_hit"]`.
- **SQLite sessions:** stdlib `sqlite3`, schema created on startup, `messages` table as specified plus a `sessions` table for the per-session system prompt. A turn (user + assistant rows) is written in one transaction only after success, so failed requests (422/503) leave no trace. Tokens come from the provider's usage for that one request.

## 4. Verification
```bash
B=http://localhost:8000
curl $B/health
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a","message":"Capital of France?"}'   # LIVE_INFERENCE
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"b","message":"Capital of France?"}'   # LLM_CACHE, key_id null
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"c","message":"New question"}'  # key_id key_2
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"c","message":"Another"}'          # 503
curl $B/sessions/a/messages
```
In the UI every reply shows source, model, latency and per-request tokens; "Session settings" has a field for the failure header.

## 5. Setup used
TODO: your editor and AI tools.

## 6. Bonus features
- Per-session system prompt field; failure-simulation field in the UI; optional disk cache.
