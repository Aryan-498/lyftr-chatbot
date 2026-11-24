"""LiteLLM gateway: key-pool failover + built-in response cache."""
import logging
import os

import litellm
from litellm import Cache

log = logging.getLogger("llm")
DEFAULT_MODEL = "gemini/gemini-2.0-flash"
VALID_SIM_STATUSES = {429, 500, 502, 503}


class AllProvidersFailed(Exception):
    pass


def keys() -> list[str]:
    return [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]


def setup_cache() -> None:
    if os.getenv("CACHE_TYPE", "local") == "disk":
        litellm.cache = Cache(type="disk", disk_cache_dir=os.getenv("CACHE_DIR", "/data/cache"))
    else:
        litellm.cache = Cache(type="local")


def cache_enabled() -> bool:
    return litellm.cache is not None


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Bad pairs are ignored."""
    out: dict[str, int] = {}
    for pair in (header or "").split(","):
        name, _, status = pair.strip().partition("=")
        if name and status.strip().isdigit() and int(status) in VALID_SIM_STATUSES:
            out[name.strip()] = int(status)
    return out


async def generate(messages: list[dict], simulate: dict[str, int]) -> dict:
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    timeout = float(os.getenv("LLM_TIMEOUT", "30"))
    failed = 0
    for i, key in enumerate(keys(), start=1):
        key_id = f"key_{i}"
        sim_status = simulate.get(key_id, simulate.get("*"))
        if sim_status:
            log.warning("simulated %s on %s", sim_status, key_id)
            failed += 1
            continue
        extra = {"cache": {"no-cache": True}} if simulate else {}  # simulated requests always hit a live key
        try:
            resp = await litellm.acompletion(
                model=model, messages=messages, api_key=key,
                num_retries=0, timeout=timeout, **extra,
            )
            text = resp.choices[0].message.content or ""
            if not text.strip():
                raise ValueError("empty completion")
        except Exception as exc:  # 429 / quota / 5xx / timeouts -> next key (never log the key)
            log.warning("%s failed: %s status=%s", key_id, type(exc).__name__, getattr(exc, "status_code", "?"))
            failed += 1
            continue
        hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
        usage = resp.usage
        return {
            "reply": text,
            "resolution_source": "LLM_CACHE" if hit else "LIVE_INFERENCE",
            "model": model,
            "input_tokens": int(usage.prompt_tokens),
            "output_tokens": int(usage.completion_tokens),
            "key_id": None if hit else key_id,
            "fallback_attempts": 0 if hit else failed,
        }
    raise AllProvidersFailed()
