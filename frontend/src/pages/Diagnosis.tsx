import { Bot, CheckCircle2, CircleAlert, Stethoscope } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Any, useMeta, fmt, qsOf, sevColor, useApi, usePost } from "../api";
import { ExplainButton } from "../components/Explain";
import { FixNowButton } from "../components/FixNow";
import { Card, DataTable, ErrorBox, Meter, SevBadge, StateText } from "../components/ui";

interface Body { ticket_text: string; device_id: string; week?: number; repeat_contacts: number; escalations: number; include_ml: boolean }

export function Vitals({ vitals }: { vitals: Any[] }) {
  return (
    <div className="grid g-4" style={{ gap: 8 }}>
      {vitals.map((v) => (
        <div key={v.key} className="vital">
          <div className="k">{v.label}</div>
          <div className={`v state-${v.state}`}>{typeof v.value === "number" ? fmt.n(v.value, v.value % 1 ? 1 : 0) : v.value}{v.unit && <small className="faint" style={{ fontSize: 11 }}>{v.unit}</small>}</div>
        </div>
      ))}
    </div>
  );
}

export default function Diagnosis() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const meta = useMeta();
  const tickets = useApi(`/v1/experience/tickets${qsOf({ sort: "ticket_id", limit: 500 })}`);
  const devices = useApi(`/v1/telemetry/devices${qsOf({ sort: "device_id", limit: 300 })}`);
  const [ticketId, setTicketId] = useState(params.get("ticket") || "");
  const [text, setText] = useState("Outlook keeps crashing and this is unacceptable.");
  const [device, setDevice] = useState(params.get("device") || "DEV-0002");
  const [week, setWeek] = useState<string>(params.get("week") || "6");
  const [rep, setRep] = useState(0);
  const [esc, setEsc] = useState(0);
  const m = usePost<Body>("/v1/diagnosis", ["/v1/diagnosis"]);

  useEffect(() => {
    if (!ticketId || !tickets.data) return;
    const t = tickets.data.items.find((x: Any) => x.ticket_id === ticketId);
    if (t) {
      setText(t.ticket_text); setDevice(t.device_id); setWeek(String(t.week));
      setRep(Math.max(0, t.repeat_number - 1) + (t.outcome_status === "Reopened" ? 1 : 0)); setEsc(t.outcome_status === "Escalated" ? 1 : 0);
    }
  }, [ticketId, tickets.data]);

  // Deep link (?ticket=...&run=1 or from Device 360): fill from the ticket, then run once.
  const [autoRan, setAutoRan] = useState(false);
  useEffect(() => {
    if (autoRan || !params.get("ticket") || !tickets.data || !devices.data) return;
    const t = tickets.data.items.find((x: Any) => x.ticket_id === params.get("ticket"));
    if (!t) return;
    setAutoRan(true);
    m.mutate({ ticket_text: t.ticket_text, device_id: t.device_id, week: t.week,
               repeat_contacts: Math.max(0, t.repeat_number - 1) + (t.outcome_status === "Reopened" ? 1 : 0),
               escalations: t.outcome_status === "Escalated" ? 1 : 0, include_ml: true });
  }, [autoRan, params, tickets.data, devices.data, m]);

  const run = () => m.mutate({ ticket_text: text, device_id: device, week: week ? +week : undefined, repeat_contacts: rep, escalations: esc, include_ml: true });
  const r: Any = m.data;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Diagnosis Assist + Root Cause Engine</div>
          <h2>Root cause in seconds, from a ticket and a device</h2>
          <p>Fuses telemetry severity (65%) with the ticket's language (35%) into ranked root causes, refines to a sub-cause,
            shows the telemetry evidence and recommends a fix — with an ML second opinion.</p>
        </div>
      </div>
      <div className="grid g-split">
        <Card title="Ticket intake">
          <label className="field" htmlFor="tp">Pick an existing ticket, or write your own</label>
          <select id="tp" style={{ width: "100%", marginBottom: 12 }} value={ticketId} onChange={(e) => setTicketId(e.target.value)}>
            <option value="">— write a new ticket below —</option>
            {tickets.data?.items.map((t: Any) => <option key={t.ticket_id} value={t.ticket_id}>{t.ticket_id} · W{t.week} · {t.category} · {t.employee_name} · {t.frustration_score}</option>)}
          </select>
          <label className="field" htmlFor="tt">Ticket / call text</label>
          <textarea id="tt" rows={4} value={text} onChange={(e) => { setText(e.target.value); setTicketId(""); }} />
          <div className="grid g-2 mt">
            <div>
              <label className="field" htmlFor="dp">Device</label>
              <select id="dp" style={{ width: "100%" }} value={device} onChange={(e) => setDevice(e.target.value)}>
                {devices.data?.items.map((d: Any) => <option key={d.device_id} value={d.device_id}>{d.device_id} · {d.employee_name} · {d.department}</option>)}
              </select>
            </div>
            <div>
              <label className="field" htmlFor="wk">Telemetry week</label>
              <select id="wk" style={{ width: "100%" }} value={week} onChange={(e) => setWeek(e.target.value)}>
                <option value="">Latest</option>
                {(meta.data?.dimensions.weeks || []).map((w: Any) => w.week as number).map((w: number) => <option key={w} value={w}>Week {w}</option>)}
              </select>
            </div>
          </div>
          <div className="row mt">
            <label className="field" style={{ margin: 0 }}>Prior contacts</label>
            <input type="number" min={0} max={20} value={rep} onChange={(e) => setRep(+e.target.value)} style={{ width: 60 }} />
            <label className="field" style={{ margin: 0 }}>Escalations</label>
            <input type="number" min={0} max={5} value={esc} onChange={(e) => setEsc(+e.target.value)} style={{ width: 60 }} />
          </div>
          <div className="row mt">
            <button className="btn btn-primary" onClick={run} disabled={!text.trim() || !device || m.isPending}><Stethoscope size={14} />{m.isPending ? "Diagnosing…" : "Run diagnosis"}</button>
            <button className="btn btn-ghost" onClick={() => { setText(""); setTicketId(""); m.reset(); }}>Clear</button>
          </div>
          {r && (
            <div className="mt-lg">
              <div className="row between" style={{ marginBottom: 8 }}>
                <span className="card-title">Device vitals · {r.device.device_id} · W{r.device.week}</span>
                <Link to={`/devices/${r.device.device_id}`} className="note">Device 360 →</Link>
              </div>
              <Vitals vitals={r.telemetry.vitals} />
              <div className="note mt">Device Health {fmt.n(r.telemetry.device_health)} ({r.telemetry.health_band}) · Telemetry severity {fmt.n(r.telemetry.telemetry_severity)} · {r.history.prior_tickets} ticket(s) to date</div>
            </div>
          )}
        </Card>

        <Card title="Engine output" sub={r ? r.method.fusion : "ranked root causes, confidence, evidence and fix"}>
          {m.error && <ErrorBox error={m.error} />}
          {!r && !m.error && <div className="empty">Run a diagnosis to see ranked root causes, frustration score and a suggested remediation.</div>}
          {r && (
            <>
              <div className="row between" style={{ marginBottom: 6 }}>
                <span className="field" style={{ margin: 0 }}>Frustration score</span>
                <span className="row" style={{ gap: 6 }}><SevBadge sev={r.experience.severity} /><span className="chip">{r.experience.emotion}</span>
                  <ExplainButton source={{ text, repeat: r.experience.repeat_contacts, escalations: r.experience.escalations }}>Why?</ExplainButton></span>
              </div>
              <Meter value={r.experience.frustration_score} color={sevColor(r.experience.severity)}
                     label={<b className="mono" style={{ color: sevColor(r.experience.severity) }}>{r.experience.frustration_score}/100</b>} />

              <div className="field mt-lg" style={{ marginBottom: 10 }}>Likely causes · likelihood / confidence</div>
              {r.root_causes.map((c: Any, i: number) => (
                <div key={c.category} className="rank-row" style={{ gridTemplateColumns: "18px 150px 1fr 76px" }}
                     title={`telemetry ${c.telemetry_component} · text ${c.text_component} · ${c.keyword_hits} keyword hit(s)`}>
                  <span className="rn">{i + 1}</span><span style={{ fontWeight: 600 }}>{c.category}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ width: `${c.likelihood}%`, opacity: i === 0 ? 1 : 0.45 }} /></div>
                  <span className="rc">{c.likelihood}% · {c.confidence}</span>
                </div>
              ))}

              {r.inconclusive ? (
                <div className="callout mt"><div className="rk">Inconclusive</div><div>{r.recommendation}</div></div>
              ) : (
                <>
                  <div className="field mt-lg" style={{ marginBottom: 10 }}>Sub-cause within {r.primary.category}</div>
                  {r.root_causes[0].subcauses.slice(0, 3).map((s: Any, i: number) => (
                    <div key={s.name} className="rank-row" style={{ gridTemplateColumns: "18px 1fr 90px 40px" }}>
                      <span className="rn">{i + 1}</span><span>{s.name}</span>
                      <div className="bar-track"><div className="bar-fill" style={{ width: `${s.share}%`, background: "var(--chart-human)", opacity: i === 0 ? 1 : 0.45 }} /></div>
                      <span className="rc">{s.share}%</span>
                    </div>
                  ))}
                  <div className="field mt">Telemetry evidence</div>
                  <ul style={{ margin: "0 0 0 16px", padding: 0, fontSize: 12.5, lineHeight: 1.6 }}>
                    {r.root_causes[0].evidence.map((e: Any) => <li key={e.signal}><StateText state={e.state}>{e.text}</StateText></li>)}
                  </ul>
                  <div className="callout mt">
                    <div className="rk">Suggested remediation · confidence {r.primary.confidence}% {r.primary.kb_id && <>· runbook {r.primary.kb_id}</>}</div>
                    <div style={{ fontWeight: 700, fontSize: 14 }}>{r.recommendation}</div>
                    {r.standard_action !== r.recommendation && <div className="note" style={{ marginTop: 4 }}>Standard action for {r.primary.category}: {r.standard_action}</div>}
                    <div className="mt"><FixNowButton label={`Fix ${r.device.device_id} now`} target={{ category: r.primary.category, deviceIds: [r.device.device_id] }} /></div>
                  </div>
                  {r.expected_outcome && (
                    <div className="note mt">Expected outcome from {r.expected_outcome.based_on_cases} past {r.primary.category} fixes: repeat contacts −{fmt.n(r.expected_outcome.repeat_contact_reduction_pct, 0)}%,
                      {" "}ticket rate −{fmt.n(r.expected_outcome.ticket_rate_reduction_pct, 0)}% ({r.expected_outcome.ticket_effect}).</div>
                  )}
                </>
              )}

              {r.ml_second_opinion && (
                <div className="card-flat mt">
                  <div className="row between">
                    <span className="field" style={{ margin: 0 }}>ML second opinion (TF-IDF + telemetry logistic regression)</span>
                    {r.ml_second_opinion.agrees_with_rules
                      ? <span className="state-ok" style={{ fontSize: 12 }}><CheckCircle2 size={12} style={{ verticalAlign: -1 }} /> agrees</span>
                      : <span className="state-warn" style={{ fontSize: 12 }}><CircleAlert size={12} style={{ verticalAlign: -1 }} /> disagrees</span>}
                  </div>
                  <div style={{ fontSize: 13, marginTop: 6 }}>Predicts <b>{r.ml_second_opinion.prediction}</b> · {r.ml_second_opinion.probabilities.slice(0, 3).map((p: Any) => `${p.category} ${fmt.n(p.probability, 0)}%`).join(" · ")}</div>
                  <div className="note" style={{ marginTop: 4 }}>Top features: {r.ml_second_opinion.top_features.map((f: Any) => f.feature.replace("telemetry:", "⚙ ")).join(", ") || "—"}</div>
                </div>
              )}
              <div className="row mt">
                <button className="btn btn-ghost" onClick={() => nav(`/copilot${qsOf({ device: r.device.device_id, week: r.device.week, text })}`)}><Bot size={14} />Explain with DEX Copilot</button>
              </div>
            </>
          )}
        </Card>
      </div>
      {r?.history?.last_tickets?.length > 0 && (
        <Card className="mt" title={`Ticket history · ${r.device.employee_name}`} sub={`${r.history.prior_same_category} prior ${r.primary.category} ticket(s)`}>
          <DataTable rows={r.history.last_tickets} columns={[
            { key: "ticket_id", label: "Ticket" }, { key: "week", label: "Week", num: true }, { key: "category", label: "Category" },
            { key: "ticket_text", label: "Text" },
            { key: "frustration_score", label: "Frustration", num: true, render: (x: Any) => x.ticket_id
              ? <ExplainButton source={{ ticketId: x.ticket_id }}><b className="mono">{x.frustration_score}</b></ExplainButton> : x.frustration_score },
            { key: "outcome_status", label: "Status" },
          ]} />
        </Card>
      )}
    </>
  );
}
