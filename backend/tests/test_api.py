import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import litellm


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEYS", "k1,k2")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    state = SimpleNamespace(calls=[], cache={}, dead=set())

    async def fake(**kw):
        state.calls.append(kw)
        if kw["api_key"] in state.dead:
            raise RuntimeError("429 quota")
        ck = json.dumps(kw["messages"])
        hit = ck in state.cache and not kw.get("cache", {}).get("no-cache")
        if not hit:
            words = sum(len(m["content"].split()) for m in kw["messages"])
            state.cache[ck] = (f"echo:{kw['messages'][-1]['content']}", words)
        text, words = state.cache[ck]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=words, completion_tokens=3),
            _hidden_params={"cache_hit": hit},
        )

    monkeypatch.setattr(litellm, "acompletion", fake)
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        c.state = state
        yield c


def chat(c, sid, msg, **headers):
    return c.post("/chat", json={"session_id": sid, "message": msg}, headers=headers)


def test_health(env):
    assert env.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_live_then_cache_across_sessions(env):
    a = chat(env, "s1", "hello there").json()
    b = chat(env, "s2", "hello there").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE" and a["metadata"]["key_id"] == "key_1"
    assert b["metadata"]["resolution_source"] == "LLM_CACHE" and b["metadata"]["key_id"] is None
    assert a["reply"] == b["reply"]
    assert b["metadata"]["fallback_attempts"] == 0
    assert chat(env, "s3", "something else").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_history_and_per_request_tokens(env):
    first = chat(env, "m", "one two").json()
    second = chat(env, "m", "three").json()
    sent = env.state.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert second["metadata"]["input_tokens"] > first["metadata"]["input_tokens"]
    hist = env.get("/sessions/m/messages").json()["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    assert "metadata" in hist[1] and "metadata" not in hist[0]
    assert env.get("/sessions/other/messages").status_code == 404


def test_system_prompt_persists_per_session(env):
    env.post("/chat", json={"session_id": "p", "message": "hi", "system_prompt": "Be a pirate"})
    chat(env, "p", "again")
    assert env.state.calls[-1]["messages"][0]["content"] == "Be a pirate"


def test_simulated_failover(env):
    r = chat(env, "f", "q1", **{"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2" and r.json()["metadata"]["fallback_attempts"] == 1
    r = chat(env, "f", "q2", **{"X-Simulate-Failure": "key_1=429,key_2=500"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}


def test_all_failed_not_stored(env):
    r = chat(env, "x", "q", **{"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503
    assert env.get("/sessions/x/messages").status_code == 404


def test_real_failure_falls_over(env):
    env.state.dead.add("k1")
    r = chat(env, "d", "ping").json()
    assert r["metadata"]["key_id"] == "key_2" and r["metadata"]["fallback_attempts"] == 1
    env.state.dead.add("k2")
    assert chat(env, "d", "ping2").status_code == 503


def test_simulation_disabled(env, monkeypatch):
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    assert chat(env, "n", "q", **{"X-Simulate-Failure": "*=429"}).status_code == 200


@pytest.mark.parametrize("body", [
    {}, {"session_id": "a"}, {"session_id": "a", "message": "   "},
    {"session_id": "", "message": "x"}, {"session_id": "a", "message": "x" * 4001},
])
def test_validation(env, body):
    r = env.post("/chat", json=body)
    assert r.status_code == 422 and "detail" in r.json()


def test_malformed_json(env):
    r = env.post("/chat", content="{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422
