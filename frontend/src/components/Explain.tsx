import { useQuery } from "@tanstack/react-query";
import { Info, X } from "lucide-react";
import { ReactNode, useState } from "react";
import { createPortal } from "react-dom";
import { Any, api, fmt, sevColor } from "../api";
import { ErrorBox, Loading, SevBadge } from "./ui";

export type ExplainSource = { ticketId: string } | { text: string; repeat?: number; escalations?: number };

const GROUP_COLOR: Record<string, string> = {
  Baseline: "var(--text-faint)", "Strong negative": "var(--critical)", "High negative": "var(--serious)",
  Negative: "var(--human)", "Repeat marker": "var(--human)", Behaviour: "var(--chart-machine)",
};

/** The ticket text with every phrase that moved the score highlighted in place. */
function Highlighted({ text, spans }: { text: string; spans: Any[] }) {
  const parts: ReactNode[] = [];
  let at = 0;
  spans.forEach((s, i) => {
    if (s.start > at) parts.push(text.slice(at, s.start));
    const piece = text.slice(s.start, s.end);
    if (s.kind === "score") {
      parts.push(<mark key={i} title={`${s.group}: +${s.weight}`} style={{ background: `color-mix(in srgb, ${GROUP_COLOR[s.group]} 28%, transparent)`,
        color: "var(--text)", borderRadius: 3, padding: "0 2px" }}>{piece}<sup style={{ fontSize: 9.5, fontWeight: 800, marginLeft: 2 }}>+{s.weight}</sup></mark>);
    } else {
      parts.push(<span key={i} title={s.kind === "calm" ? "softener: calm tone (sentiment only)" : `${s.group} cue (emotion only, no points)`}
        style={{ borderBottom: `2px ${s.kind === "calm" ? "solid var(--machine)" : "dashed var(--text-faint)"}` }}>{piece}</span>);
    }
    at = s.end;
  });
  if (at < text.length) parts.push(text.slice(at));
  return <p style={{ fontSize: 14, lineHeight: 1.8, margin: 0 }}>{parts}</p>;
}

/** Each step adds its points on top of the running total; the dashed line is the 100 cap. */
function Waterfall({ steps, final }: { steps: Any[]; final: number }) {
  const max = Math.max(100, steps[steps.length - 1]?.running_total || 0);
  const x = (v: number) => `${(100 * v) / max}%`;
  return (
    <div>
      {steps.map((s, i) => {
        const from = s.running_total - s.points;
        return (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "minmax(150px, 210px) 1fr 44px 40px", gap: 10, alignItems: "center", fontSize: 12.5, marginBottom: 6 }}>
            <span title={s.group}>{s.label}<div className="faint" style={{ fontSize: 10.5 }}>{s.group}</div></span>
            <div style={{ position: "relative", height: 14, background: "var(--panel-2)", borderRadius: 3 }}>
              <div style={{ position: "absolute", left: x(from), width: x(s.points), top: 0, bottom: 0, borderRadius: 3, background: GROUP_COLOR[s.group] || "var(--human)" }} />
              <div style={{ position: "absolute", left: x(100), top: -3, bottom: -3, borderLeft: "1.5px dashed var(--text-faint)" }} />
            </div>
            <span className="mono" style={{ textAlign: "right", fontWeight: 700 }}>+{s.points}</span>
            <span className="mono faint" style={{ textAlign: "right" }}>{s.running_total}</span>
          </div>
        );
      })}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(150px, 210px) 1fr 44px 40px", gap: 10, fontSize: 13, borderTop: "1px solid var(--hairline)", paddingTop: 6 }}>
        <b>Frustration score</b><span className="note">{steps[steps.length - 1]?.running_total > 100 ? `capped at 100 (${steps[steps.length - 1].running_total - final} points above the cap)` : ""}</span>
        <span /><b className="mono" style={{ textAlign: "right" }}>{final}</b>
      </div>
    </div>
  );
}

function SeverityScale({ score, bands }: { score: number; bands: Any[] }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ position: "relative", display: "flex", height: 10, borderRadius: 5, overflow: "hidden" }}>
        {bands.map((b) => <div key={b.band} style={{ flex: b.to - b.from + 1, background: sevColor(b.band), opacity: 0.55 }} />)}
      </div>
      <div style={{ position: "relative", height: 16 }}>
        <div style={{ position: "absolute", left: `calc(${score}% - 5px)`, top: -3, width: 0, height: 0, borderLeft: "5px solid transparent",
                      borderRight: "5px solid transparent", borderBottom: "7px solid var(--text)" }} />
      </div>
      <div className="row between" style={{ fontSize: 10.5, color: "var(--text-faint)" }}>
        {bands.map((b) => <span key={b.band}>{b.band} {b.from}–{b.to}</span>)}
      </div>
    </div>
  );
}

function ExplainDrawer({ source, onClose }: { source: ExplainSource; onClose: () => void }) {
  const byTicket = "ticketId" in source;
  const q = useQuery<Any>({
    queryKey: ["explain", source],
    queryFn: () => byTicket
      ? api(`/v1/experience/tickets/${encodeURIComponent((source as { ticketId: string }).ticketId)}/explain`)
      : api("/v1/experience/explain", { method: "POST", body: JSON.stringify({ text: (source as Any).text, repeat_contacts: (source as Any).repeat || 0, escalations: (source as Any).escalations || 0 }) }),
  });
  const d = q.data;
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-labelledby="ex-title">
        <div className="row between">
          <div className="eyebrow" style={{ margin: 0 }}>Explainable AI · Experience Analytics</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><X size={13} /></button>
        </div>
        <h3 id="ex-title" style={{ margin: "6px 0 2px", fontSize: 18 }}>How this score was computed</h3>
        {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : d && (
          <>
            {d.ticket && <div className="note">{d.ticket.ticket_id} · {d.ticket.employee_name} · {d.ticket.department} · {d.ticket.channel} · W{d.ticket.week} · {d.ticket.category} · {d.ticket.outcome_status}</div>}

            <div className="row mt" style={{ alignItems: "flex-end", gap: 16 }}>
              <div style={{ fontSize: 48, fontWeight: 800, lineHeight: 1, color: sevColor(d.severity) }}>{d.frustration_score}<span className="faint" style={{ fontSize: 16 }}>/100</span></div>
              <div><SevBadge sev={d.severity} /><div className="note" style={{ marginTop: 4 }}>Emotion <b>{d.emotion.primary}</b> · sentiment {fmt.n(d.sentiment.polarity, 2)} · text tier {d.sentiment_tier}</div></div>
            </div>
            <SeverityScale score={d.frustration_score} bands={d.severity_bands} />

            <div className="field mt">1 · What the employee wrote</div>
            <div className="card-flat"><Highlighted text={d.text} spans={d.spans} /></div>
            <div className="note" style={{ marginTop: 4 }}>
              <mark style={{ background: "color-mix(in srgb, var(--human) 28%, transparent)", color: "var(--text)" }}>highlight</mark> = adds points ·
              <span style={{ borderBottom: "2px dashed var(--text-faint)", margin: "0 4px" }}>dashed</span> = emotion cue ·
              <span style={{ borderBottom: "2px solid var(--machine)", margin: "0 4px" }}>underline</span> = calm tone
            </div>

            <div className="field mt">2 · Points, step by step</div>
            <Waterfall steps={d.steps} final={d.frustration_score} />
            {d.inputs && (
              <div className="note" style={{ marginTop: 6 }}>
                Behaviour inputs from the ticket record: {d.inputs.prior_contacts} prior contact(s) ({d.inputs.prior_contacts_rule}) ·
                escalated: {d.inputs.escalated ? "yes" : "no"}{d.inputs.reopened ? " · reopened" : ""}
              </div>
            )}

            <div className="grid g-2 mt">
              <div>
                <div className="field">3 · Emotion</div>
                {d.emotion.hits.map((h: Any) => (
                  <div key={h.emotion} className="row between" style={{ fontSize: 12.5, marginBottom: 4, fontWeight: h.emotion === d.emotion.primary ? 800 : 400 }}>
                    <span>{h.emotion}{h.phrases.length ? <span className="faint" style={{ fontWeight: 400 }}> · {h.phrases.length} cue(s)</span> : null}</span>
                    <span className="mono">{h.phrases.length} × {h.weight} = {fmt.n(h.score, 1)}</span>
                  </div>
                ))}
                <div className="note">Highest weighted score wins; no cues → Neutral.</div>
              </div>
              <div>
                <div className="field">4 · Sentiment polarity</div>
                <div className="mono" style={{ fontSize: 12 }}>{d.sentiment.formula}</div>
                <div className="mono" style={{ fontSize: 12, marginTop: 4 }}>= {fmt.n(d.sentiment.positivity, 2)} × (1 − {fmt.n(d.sentiment.negativity, 2)}) − {fmt.n(d.sentiment.negativity, 2)} = <b>{fmt.n(d.sentiment.polarity, 2)}</b></div>
                <div className="note">negativity = (text score − 8) / 92 · positivity = 0.25 per calm phrase{d.sentiment.softeners.length ? ` (${d.sentiment.softeners.join(", ")})` : ""}</div>
              </div>
            </div>

            <details className="mt">
              <summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13 }}><Info size={13} style={{ verticalAlign: -2, marginRight: 4 }} />Method & full lexicon</summary>
              <p style={{ fontSize: 12.5 }}>{d.method.summary}</p>
              <p className="note">{d.method.validation}. {d.method.why_rules}</p>
              {d.method.lexicon.map((g: Any) => (
                <div key={g.group} style={{ fontSize: 12, marginBottom: 6 }}>
                  <b style={{ color: GROUP_COLOR[g.group] }}>{g.group} +{g.weight}</b>: {g.phrases.map((p: string) => `“${p}”`).join(", ")}
                </div>
              ))}
              <div style={{ fontSize: 12 }}><b style={{ color: GROUP_COLOR.Behaviour }}>Behaviour</b>: +10 per prior contact on the same issue, +15 per escalation</div>
            </details>
          </>
        )}
      </aside>
    </>
  );
}

/** Clickable score that opens the explanation. */
export function ExplainButton({ source, children, title = "How was this computed?", defaultOpen = false }: {
  source: ExplainSource; children?: ReactNode; title?: string; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      <button className="btn btn-ghost btn-sm" style={{ padding: "2px 8px" }} title={title} aria-label={title}
              onClick={(e) => { e.stopPropagation(); setOpen(true); }}>
        {children}<Info size={12} />
      </button>
      {open && createPortal(
        <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <ExplainDrawer source={source} onClose={() => setOpen(false)} />
        </div>, document.body)}
    </>
  );
}
