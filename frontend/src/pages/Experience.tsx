import { useState } from "react";
import { Link } from "react-router-dom";
import { Any, fmt, qsOf, sevColor, useApi, useFilters, useMeta, usePost } from "../api";
import { Bars, TrendChart } from "../components/charts";
import { Card, ChartCard, DataTable, ErrorBox, Kpi, Meter, QueryState, SevBadge } from "../components/ui";

const SEV_ORDER = ["Low", "Medium", "High", "Critical"];

function Analyzer() {
  const [text, setText] = useState("This is the 3 time I'm reporting this exact issue. Outlook keeps crashing and this is unacceptable.");
  const [rep, setRep] = useState(2);
  const [esc, setEsc] = useState(0);
  const m = usePost<{ text: string; repeat_contacts: number; escalations: number }>("/v1/experience/analyze");
  const r: Any = m.data;
  return (
    <Card title="Live sentiment & frustration analyser" sub="validated keyword lexicon (93.3% agreement with ground truth) + repeat/escalation boost">
      <label className="field" htmlFor="an-text">Ticket, call note or chat message</label>
      <textarea id="an-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row mt">
        <label className="field" style={{ margin: 0 }}>Prior contacts</label>
        <input type="number" min={0} max={20} value={rep} onChange={(e) => setRep(+e.target.value)} style={{ width: 64 }} />
        <label className="field" style={{ margin: 0 }}>Escalations</label>
        <input type="number" min={0} max={5} value={esc} onChange={(e) => setEsc(+e.target.value)} style={{ width: 64 }} />
        <button className="btn btn-primary" disabled={!text.trim() || m.isPending} onClick={() => m.mutate({ text, repeat_contacts: rep, escalations: esc })}>Analyse</button>
      </div>
      {m.error && <div className="mt"><ErrorBox error={m.error} /></div>}
      {r && (
        <div className="mt">
          <Meter value={r.frustration_score} color={sevColor(r.severity)}
                 label={<span className="mono" style={{ color: sevColor(r.severity), fontWeight: 700 }}>{r.frustration_score}/100</span>} />
          <div className="grid g-4 mt">
            <div className="vital"><div className="k">Severity</div><div className="v"><SevBadge sev={r.severity} /></div></div>
            <div className="vital"><div className="k">Emotion</div><div className="v" style={{ fontSize: 14 }}>{r.emotion}</div></div>
            <div className="vital"><div className="k">Sentiment</div><div className="v">{fmt.n(r.sentiment, 2)}</div></div>
            <div className="vital"><div className="k">Text-only score</div><div className="v">{r.text_score}</div></div>
          </div>
          <div className="note mt">
            {r.matched_phrases.length ? <>Matched: {r.matched_phrases.map((p: Any) => `“${p.phrase}” (+${p.weight})`).join(", ")}</> : "No frustration phrases matched (baseline 8)."}
            {(r.repeat_contacts || r.escalations) ? ` · behaviour boost +${r.repeat_contacts * 10 + r.escalations * 15}` : ""}
          </div>
        </div>
      )}
    </Card>
  );
}

function TicketExplorer() {
  const { filters } = useFilters();
  const [f, setF] = useState({ severity: "", emotion: "", channel: "", q: "" });
  const [page, setPage] = useState(0);
  const meta = useMeta();
  const limit = 12;
  const q = useApi(`/v1/experience/tickets${qsOf({ ...filters, ...f, limit, offset: page * limit })}`);
  const set = (patch: Partial<typeof f>) => { setF({ ...f, ...patch }); setPage(0); };
  return (
    <Card title="Ticket explorer" sub="every ticket scored — click a device for its 360 view">
      <div className="row" style={{ marginBottom: 12 }}>
        <input type="search" placeholder="Search text, ticket, employee…" value={f.q} onChange={(e) => set({ q: e.target.value })} style={{ minWidth: 240 }} aria-label="Search tickets" />
        <select value={f.severity} onChange={(e) => set({ severity: e.target.value })} aria-label="Severity"><option value="">All severities</option>{SEV_ORDER.map((s) => <option key={s}>{s}</option>)}</select>
        <select value={f.emotion} onChange={(e) => set({ emotion: e.target.value })} aria-label="Emotion"><option value="">All emotions</option>{["Anger", "Frustration", "Anxiety", "Inquiry", "Neutral"].map((s) => <option key={s}>{s}</option>)}</select>
        <select value={f.channel} onChange={(e) => set({ channel: e.target.value })} aria-label="Channel"><option value="">All channels</option>{(meta.data?.dimensions.channels || []).map((s: string) => <option key={s}>{s}</option>)}</select>
        {q.data && <span className="chip">{q.data.total} tickets</span>}
      </div>
      <QueryState q={q}>
        {(d: Any) => (
          <>
            <DataTable rows={d.items} columns={[
              { key: "ticket_id", label: "Ticket", render: (r: Any) => <span className="mono">{r.ticket_id}<div className="faint" style={{ fontSize: 11 }}>W{r.week} · {r.channel}</div></span> },
              { key: "device_id", label: "Device", render: (r: Any) => <Link to={`/devices/${r.device_id}`}>{r.device_id}</Link> },
              { key: "ticket_text", label: "Ticket language", render: (r: Any) => <span style={{ fontSize: 12.5 }}>{r.ticket_text}</span> },
              { key: "category", label: "Category" },
              { key: "emotion", label: "Emotion" },
              { key: "severity", label: "Severity", render: (r: Any) => <SevBadge sev={r.severity} /> },
              { key: "frustration_score", label: "Frustration", num: true },
              { key: "outcome_status", label: "Status" },
            ]} />
            <div className="row mt between">
              <span className="note">Showing {d.total ? page * limit + 1 : 0}–{Math.min(d.total, (page + 1) * limit)} of {d.total}</span>
              <div className="row">
                <button className="btn btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
                <button className="btn btn-ghost btn-sm" disabled={(page + 1) * limit >= d.total} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </QueryState>
    </Card>
  );
}

export default function Experience() {
  const { qs } = useFilters();
  const q = useApi(`/v1/experience/summary${qs}`);
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Module 1 · Experience Analytics</div>
          <h2>What employees are telling the service desk</h2>
          <p>Sentiment analysis, frustration scoring, emotion classification and experience severity across calls, chats,
            portal tickets, repeat contacts and escalations.</p>
        </div>
      </div>
      <QueryState q={q}>
        {(d: Any) => d.kpis.tickets === 0 ? <div className="empty">No tickets for this scope</div> : (
          <>
            <div className="grid g-6">
              <Kpi label="Tickets" value={fmt.i(d.kpis.tickets)} accent="var(--human)" />
              <Kpi label="Avg frustration" value={fmt.n(d.kpis.avg_frustration)} unit="/100" accent="var(--human)" />
              <Kpi label="Experience Index" value={fmt.n(d.kpis.employee_experience_index)} accent="var(--machine)" />
              <Kpi label="Repeat contacts" value={fmt.pct(d.kpis.repeat_contact_rate_pct)} accent="var(--human)" deltaLabel="flagged by service desk" hint="Share of tickets the service desk flagged as a repeat contact" />
              <Kpi label="Escalations" value={fmt.pct(d.kpis.escalation_rate_pct)} accent="var(--critical)" />
              <Kpi label="High + critical" value={fmt.pct(d.kpis.critical_high_share_pct)} accent="var(--critical)" />
            </div>
            <div className="grid g-2 mt">
              <ChartCard title="Frustration by week" sub="average score of tickets raised" table={d.weekly}
                         columns={[{ key: "week", label: "Week" }, { key: "tickets", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }, { key: "repeat_contacts", label: "Repeats", num: true }, { key: "escalations", label: "Escalations", num: true }]}>
                <TrendChart data={d.weekly} series={[{ key: "avg_frustration", name: "Avg frustration", color: "var(--chart-human)" }]} yDomain={[0, 100]} />
              </ChartCard>
              <ChartCard title="Ticket volume by week" sub="all channels" table={d.weekly}
                         columns={[{ key: "week", label: "Week" }, { key: "tickets", label: "Tickets", num: true }]}>
                <Bars data={d.weekly.map((w: Any) => ({ ...w, label: `W${w.week}` }))} x="label" y="tickets" name="Tickets" color="var(--chart-human)" yFmt={(v) => fmt.i(v)} />
              </ChartCard>
            </div>
            <div className="grid g-3 mt">
              <ChartCard title="Experience severity" sub="Low <40 · Medium 40-59 · High 60-79 · Critical ≥80" table={d.severity}
                         columns={[{ key: "value", label: "Severity" }, { key: "count", label: "Tickets", num: true }, { key: "share_pct", label: "Share %", num: true }]}>
                {d.severity.map((s: Any) => (
                  <div key={s.value} className="rank-row" style={{ gridTemplateColumns: "90px 1fr 70px" }}>
                    <SevBadge sev={s.value} />
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${s.share_pct}%`, background: sevColor(s.value) }} /></div>
                    <span className="rc">{s.count} · {fmt.n(s.share_pct, 0)}%</span>
                  </div>
                ))}
              </ChartCard>
              <ChartCard title="Emotion classification" sub="primary emotion per ticket" table={d.emotion}
                         columns={[{ key: "value", label: "Emotion" }, { key: "count", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }]}>
                <Bars data={d.emotion} x="value" y="count" name="Tickets" horizontal height={200} labels xWidth={84} color="var(--chart-human)" yFmt={(v) => fmt.i(v)} />
              </ChartCard>
              <ChartCard title="Frustration climbs with every repeat contact" sub="avg frustration by contact number on the same issue" table={d.repeat_ladder}
                         columns={[{ key: "contact_number", label: "Contact #", num: true }, { key: "tickets", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }]}>
                <Bars data={d.repeat_ladder.map((r: Any) => ({ ...r, label: `Contact ${r.contact_number}` }))} x="label" y="avg_frustration" name="Avg frustration" color="var(--chart-human)"
                      height={200} labels emphasize={(_, i) => i === d.repeat_ladder.length - 1} />
              </ChartCard>
            </div>
            <div className="grid g-3 mt">
              <ChartCard title="By channel" sub="avg frustration" table={d.channel} columns={[{ key: "value", label: "Channel" }, { key: "count", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }]}>
                <Bars data={d.channel} x="value" y="avg_frustration" name="Avg frustration" color="var(--chart-human)" height={190} labels />
              </ChartCard>
              <ChartCard title="By category" sub="avg frustration" table={d.category} columns={[{ key: "value", label: "Category" }, { key: "count", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }]}>
                <Bars data={d.category} x="value" y="avg_frustration" name="Avg frustration" color="var(--chart-human)" height={190} horizontal labels xWidth={120} />
              </ChartCard>
              <ChartCard title="Frustration distribution" sub="tickets per 10-point band" table={d.histogram} columns={[{ key: "bin", label: "Band" }, { key: "count", label: "Tickets", num: true }]}>
                <Bars data={d.histogram.map((h: Any) => ({ ...h, band: h.bin.split("-")[0] }))} x="band" y="count" name="Tickets" color="var(--chart-human)" height={190} yFmt={(v) => fmt.i(v)} />
              </ChartCard>
            </div>
            <div className="grid g-split mt">
              <Analyzer />
              <Card title="Top frustration language" sub="phrases weighted by the lexicon">
                <DataTable rows={d.drivers.phrases} max={9} columns={[
                  { key: "phrase", label: "Phrase", render: (r: Any) => <span>“{r.phrase}”</span> },
                  { key: "weight", label: "Weight", num: true },
                  { key: "tickets", label: "Tickets", num: true },
                  { key: "avg_frustration", label: "Avg frustr.", num: true },
                ]} />
              </Card>
            </div>
            <div className="mt"><TicketExplorer /></div>
          </>
        )}
      </QueryState>
    </>
  );
}
