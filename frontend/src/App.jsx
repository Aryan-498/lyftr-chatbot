import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const newSessionId = () =>
  "s-" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(36).slice(2, 10));

function readableError(status, body) {
  const d = body && body.detail;
  if (status === 503) return "All AI providers are unavailable right now. Try again in a moment.";
  if (status === 422) {
    if (Array.isArray(d) && d[0]?.msg) return `Invalid input: ${d[0].msg}.`;
    return "Your message was rejected. It must be 1–4000 characters.";
  }
  return typeof d === "string" ? d : `Request failed (${status}).`;
}

function Meta({ m }) {
  return (
    <dl className="meta">
      <div><dt>source</dt><dd data-testid="meta-source" className={m.resolution_source}>{m.resolution_source}</dd></div>
      <div><dt>model</dt><dd data-testid="meta-model">{m.model}</dd></div>
      <div><dt>latency</dt><dd data-testid="meta-latency">{m.latency_ms} ms</dd></div>
      <div><dt>input tokens</dt><dd data-testid="meta-input-tokens">{m.input_tokens}</dd></div>
      <div><dt>output tokens</dt><dd data-testid="meta-output-tokens">{m.output_tokens}</dd></div>
      <div><dt>key</dt><dd>{m.key_id ?? "none"}{m.fallback_attempts > 0 ? ` (after ${m.fallback_attempts} failed)` : ""}</dd></div>
    </dl>
  );
}

export default function App() {
  const [sessionId] = useState(newSessionId);
  const [items, setItems] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  useEffect(() => {
  endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, busy]);

  async function send() {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setItems((x) => [...x, { kind: "user", text: message }]);
    setBusy(true);
    try {
      const headers = { "Content-Type": "application/json" };
      if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();
      const body = { session_id: sessionId, message };
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      const res = await fetch(`${API}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(readableError(res.status, data));
      setItems((x) => [...x, { kind: "assistant", text: data.reply, meta: data.metadata }]);
    } catch (e) {
      const text = e instanceof TypeError ? "Can't reach the server. Check your connection and try again." : e.message;
      setItems((x) => [...x, { kind: "error", text }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Resilient Chat</h1>
        <span className="sid">session {sessionId}</span>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>System prompt
          <textarea data-testid="system-prompt-input" rows={2} value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)} placeholder="Optional. Applies to this session." />
        </label>
        <label>Simulate failure (demo only)
          <input value={simulate} onChange={(e) => setSimulate(e.target.value)} placeholder="key_1=429  or  *=429" />
        </label>
      </details>

      <main>
        {items.length === 0 && <p className="empty">Ask something. Send the same question in a new tab to see a cache hit.</p>}
        {items.map((it, i) =>
          it.kind === "user" ? (
            <div key={i} className="bubble user">{it.text}</div>
          ) : it.kind === "error" ? (
            <div key={i} className="bubble error" role="alert" data-testid="error-message">{it.text}</div>
          ) : (
            <div key={i} className="bubble assistant" data-testid="assistant-message">
              <p>{it.text}</p>
              <Meta m={it.meta} />
            </div>
          )
        )}
        {busy && <div className="bubble assistant pending">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea data-testid="chat-input" rows={1} value={input} placeholder="Type a message"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button data-testid="send-button" onClick={send} disabled={busy}>Send</button>
      </footer>
    </div>
  );
}
