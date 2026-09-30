import { BookOpen, Bot, Send, Wrench, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useSearchParams } from "react-router-dom";
import { Any, useMeta, api, qsOf, useApi } from "../api";
import { Card, ErrorBox, Loading } from "../components/ui";

interface Turn { role: "user" | "assistant"; content: string; result?: Any; error?: unknown }

const SUGGESTIONS = [
  { q: "Why does this employee's Outlook keep crashing, and what should we do?", device: "DEV-0002", text: "This is unacceptable at this point. Outlook keeps crashing.", week: "6" },
  { q: "Which department has the worst experience and what should we fix first?" },
  { q: "Which devices should we remediate proactively this week?" },
  { q: "What business value did our remediations deliver?" },
];

function KbDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useApi(`/v1/kb/${id}`);
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`Runbook ${id}`}>
        <div className="row between"><span className="chip"><BookOpen size={12} />Runbook</span><button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><X size={13} /></button></div>
        {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : <div className="kb-md"><ReactMarkdown>{q.data.markdown}</ReactMarkdown></div>}
      </aside>
    </>
  );
}

function Answer({ r, openKb }: { r: Any; openKb: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const x = r.response;
  return (
    <div className="msg-bot">
      <ReactMarkdown>{x.answer}</ReactMarkdown>
      <div className="row" style={{ marginTop: 6, gap: 6 }}>
        {x.citations.map((c: string) => c.startsWith("KB-")
          ? <button key={c} className="chip" style={{ cursor: "pointer" }} onClick={() => openKb(c)}><BookOpen size={11} />{c}</button>
          : <span key={c} className="chip">{c}</span>)}
        <span className="chip">confidence {x.confidence}%</span>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} full analysis</button>
      </div>
      {open && (
        <dl className="kv mt" style={{ gridTemplateColumns: "150px 1fr" }}>
          <dt>Ticket summary</dt><dd>{x.ticket_summary}</dd>
          <dt>Executive summary</dt><dd>{x.executive_summary}</dd>
          <dt>Primary driver</dt><dd><b>{x.primary_driver}</b></dd>
          <dt>Root cause</dt><dd>{x.root_cause_explanation}</dd>
          <dt>Evidence</dt><dd><ul style={{ margin: 0, paddingLeft: 16 }}>{x.supporting_evidence.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul></dd>
          <dt>Recommended fix</dt><dd><b>{x.recommended_fix}</b></dd>
          {x.remediation_steps.length > 0 && <><dt>Steps</dt><dd><ol style={{ margin: 0, paddingLeft: 18 }}>{x.remediation_steps.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol></dd></>}
          <dt>Expected outcome</dt><dd>{x.expected_outcome}</dd>
          <dt>Business impact</dt><dd>{x.business_impact}</dd>
        </dl>
      )}
      <div className="trace mt">
        <Wrench size={11} />{r.tool_calls.map((t: Any, i: number) => <span key={i} className={t.is_error ? "crit" : ""}>{t.tool}{i < r.tool_calls.length - 1 ? " →" : ""}</span>)}
        <span>· {r.provider === "template" ? "grounded template" : `${r.provider} · ${r.model}`} · {r.latency_ms} ms</span>
        {r.fallback_reason && <span className="state-warn">· LLM unavailable ({r.fallback_reason}) — answered from grounded engine</span>}
      </div>
    </div>
  );
}

function KbBrowser({ openKb }: { openKb: (id: string) => void }) {
  const [q, setQ] = useState("");
  const list = useApi("/v1/kb");
  const search = useApi(q.trim().length > 1 ? `/v1/kb/search${qsOf({ q })}` : null);
  const items: Any[] = q.trim().length > 1 ? search.data?.results || [] : list.data?.items || [];
  return (
    <Card title="Knowledge base (RAG source)" sub={`${list.data?.items.length ?? "…"} remediation runbooks · BM25 retrieval`}>
      <input type="search" placeholder="Search runbooks…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%", marginBottom: 10 }} aria-label="Search runbooks" />
      <div style={{ maxHeight: 420, overflowY: "auto" }}>
        {items.map((a) => (
          <button key={a.id} onClick={() => openKb(a.id)} className="card-flat" style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 6, cursor: "pointer", color: "inherit" }}>
            <div className="mono faint" style={{ fontSize: 10.5 }}>{a.id} · {a.category}{a.score ? ` · score ${a.score}` : ""}</div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{a.title}</div>
          </button>
        ))}
      </div>
    </Card>
  );
}

export default function Copilot() {
  const [params] = useSearchParams();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [device, setDevice] = useState(params.get("device") || "");
  const [text, setText] = useState(params.get("text") || "");
  const [week, setWeek] = useState(params.get("week") || "");
  const [busy, setBusy] = useState(false);
  const [kb, setKb] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const status = useApi("/v1/copilot/status");
  const meta = useMeta();

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns, busy]);


  const ask = async (question: string, ctx?: { device?: string; text?: string; week?: string }) => {
    const d = ctx?.device ?? device, t = ctx?.text ?? text, w = ctx?.week ?? week;
    if (!question.trim() || busy) return;
    const history = turns.filter((x) => !x.error).slice(-8).map((x) => ({ role: x.role, content: x.content }));
    setTurns((ts) => [...ts, { role: "user", content: question }]);
    setQ(""); setBusy(true);
    try {
      const result = await api("/v1/copilot/ask", { method: "POST", body: JSON.stringify({
        question, device_id: d || null, ticket_text: t || null, week: w ? +w : null, history }) });
      setTurns((ts) => [...ts, { role: "assistant", content: result.response.answer, result }]);
    } catch (e) {
      setTurns((ts) => [...ts, { role: "assistant", content: "", error: e }]);
    } finally { setBusy(false); }
  };

  // Deep link from Diagnosis Assist (?device&text&week): ask immediately with that context.
  const autoAsked = useRef(false);
  useEffect(() => {
    if (autoAsked.current || !params.get("device") || !params.get("text")) return;
    autoAsked.current = true;
    ask(params.get("q") || "Explain the root cause, the evidence and what we should do.");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">DEX Copilot</div>
          <h2>Ask about any ticket, device or the whole fleet</h2>
          <p>An agent that calls DEX Sentinel's engines as tools (diagnosis, telemetry, outcomes, fleet KPIs) and retrieves remediation
            runbooks, then answers in business language — every number traceable to a tool result.</p>
        </div>
        {status.data && <span className="chip"><Bot size={12} />{status.data.llm_enabled ? `${status.data.provider} · ${status.data.model}` : "Grounded template engine (set ANTHROPIC_API_KEY for LLM mode)"}</span>}
      </div>
      <div className="grid g-split" style={{ gridTemplateColumns: "minmax(0,1.6fr) minmax(0,0.8fr)" }}>
        <Card>
          <div className="chat" style={{ minHeight: 380 }}>
            {!turns.length && (
              <div>
                <div className="field">Try one of these</div>
                <div className="grid" style={{ gap: 8 }}>
                  {SUGGESTIONS.map((s) => (
                    <button key={s.q} className="card-flat" style={{ textAlign: "left", cursor: "pointer", color: "inherit" }}
                            onClick={() => { if (s.device) { setDevice(s.device); setText(s.text!); setWeek(s.week!); } else { setDevice(""); setText(""); setWeek(""); } ask(s.q, s.device ? { device: s.device, text: s.text, week: s.week } : { device: "", text: "", week: "" }); }}>
                      {s.q}{s.device && <div className="note">context: {s.device} · “{s.text}”</div>}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((t, i) => t.role === "user"
              ? <div key={i} className="msg-user">{t.content}</div>
              : t.error ? <ErrorBox key={i} error={t.error} /> : <Answer key={i} r={t.result} openKb={setKb} />)}
            {busy && <div className="msg-bot faint">Copilot is calling tools…</div>}
            <div ref={endRef} />
          </div>
          <form className="row mt" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
            <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask DEX Copilot…" style={{ flex: 1 }} aria-label="Question" />
            <button className="btn btn-primary" type="submit" disabled={busy || !q.trim()}><Send size={14} />Ask</button>
            {turns.length > 0 && <button type="button" className="btn btn-ghost" onClick={() => setTurns([])}>New chat</button>}
          </form>
        </Card>
        <div className="grid" style={{ alignContent: "start" }}>
          <Card title="Context (optional)" sub="attach a ticket and device for a root-cause answer">
            <label className="field" htmlFor="cd">Device ID</label>
            <input id="cd" type="text" value={device} onChange={(e) => setDevice(e.target.value.toUpperCase())} placeholder="e.g. DEV-0002" style={{ width: "100%" }} />
            <label className="field mt" htmlFor="ct">Ticket text</label>
            <textarea id="ct" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Employee's words…" />
            <label className="field mt" htmlFor="cw">Telemetry week</label>
            <select id="cw" value={week} onChange={(e) => setWeek(e.target.value)} style={{ width: "100%" }}>
              <option value="">Latest</option>{(meta.data?.dimensions.weeks || []).map((w: Any) => w.week as number).map((w: number) => <option key={w} value={w}>Week {w}</option>)}
            </select>
          </Card>
          <KbBrowser openKb={setKb} />
        </div>
      </div>
      {kb && <KbDrawer id={kb} onClose={() => setKb(null)} />}
    </>
  );
}
