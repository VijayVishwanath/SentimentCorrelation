import { Link, useSearchParams } from "react-router-dom";
import { Any, fmt, qsOf, sevColor, useApi, useFilters } from "../api";
import { AnalystOnly, useAnalyst } from "../components/analyst";
import { Bars, TrendChart } from "../components/charts";
import { DIMENSION_COLOR, DIMENSION_KEYS, DIMENSION_LABEL, LevelBadge } from "../components/Dimensions";
import { ExplainButton } from "../components/Explain";
import { Card, ChartCard, DataTable, ErrorBox, Kpi, Loading, QueryState, SevBadge, useServerTable } from "../components/ui";

const SEV_ORDER = ["Low", "Medium", "High", "Critical"];
const SHORT: Record<string, string> = { impact: "Impact", urgency: "Urgency", trust: "Trust risk" };

/** Business impact, urgency and trust in IT: why a ticket matters, beyond how frustrated the employee is. */
function BeyondFrustration({ dims }: { dims: Any }) {
  const weeks: Record<number, Any> = {};
  DIMENSION_KEYS.forEach((k) => dims[k].weekly_high_pct.forEach((w: Any) => {
    weeks[w.week] = { ...(weeks[w.week] || { week: w.week }), [k]: w.high_pct };
  }));
  const weekly = Object.values(weeks).sort((a: Any, b: Any) => a.week - b.week);
  const cues = DIMENSION_KEYS.flatMap((k) => dims[k].cues.map((c: Any) => ({ ...c, dim: k })))
    .sort((a: Any, b: Any) => b.tickets - a.tickets);
  return (
    <div className="grid g-split mt">
      <ChartCard title="Beyond frustration" sub="share of tickets rated High on each dimension, by week" table={weekly}
                 columns={[{ key: "week", label: "Week" }, ...DIMENSION_KEYS.map((k) => ({ key: k, label: `${DIMENSION_LABEL[k]} High %`, num: true }))]}>
        <TrendChart data={weekly} yFmt={(v) => `${v.toFixed(0)}%`}
                    series={DIMENSION_KEYS.map((k) => ({ key: k, name: k === "trust" ? "Trust in IT at risk" : DIMENSION_LABEL[k], color: DIMENSION_COLOR[k] }))} />
      </ChartCard>
      <Card title="What employees are telling us" sub="the cues behind each dimension, most common first">
        <DataTable rows={cues} pageSize={6} columns={[
          { key: "dim", label: "Dimension", render: (r: Any) => <span style={{ color: DIMENSION_COLOR[r.dim], fontWeight: 600 }}>{DIMENSION_LABEL[r.dim]}</span> },
          { key: "family", label: "Cue", render: (r: Any) => (
            <span title={r.example}><b>{r.family}</b>
              <div className="faint" style={{ fontSize: 11 }}>“{r.example}”</div></span>) },
          { key: "tickets", label: "Tickets", num: true, render: (r: Any) => fmt.i(r.tickets) },
          { key: "share_pct", label: "Share", num: true, render: (r: Any) => fmt.pct(r.share_pct) },
        ]} />
      </Card>
    </div>
  );
}

function TicketExplorer() {
  const { on } = useAnalyst();
  const { filters } = useFilters();
  const st = useServerTable(5);
  const q = useApi(`/v1/experience/tickets${qsOf({ ...filters, ...st.params })}`);
  const d: Any = q.data;
  const columns: Any[] = [
    { key: "ticket_id", label: "Ticket", filter: "text", render: (r: Any) => <span className="mono">{r.ticket_id}</span> },
    ...(on ? [{ key: "week", label: "Week", num: true, filter: "num", render: (r: Any) => `W${r.week}` },
              { key: "channel", label: "Channel", filter: "select" }] : []),
    { key: "device_id", label: "Device", filter: "text", render: (r: Any) => <Link to={`/devices/${r.device_id}`}>{r.device_id}</Link> },
    { key: "employee_name", label: "Employee", filter: "text" },
    { key: "ticket_text", label: "Ticket language", filter: "text", render: (r: Any) => <span style={{ fontSize: 12.5 }}>{r.ticket_text}</span> },
    { key: "category", label: "Category", filter: "select" },
    ...(on ? [{ key: "emotion", label: "Emotion", filter: "select" },
              { key: "severity", label: "Severity", filter: "select", render: (r: Any) => <SevBadge sev={r.severity} /> }] : []),
    { key: "frustration_score", label: "Frustration", num: true, filter: "num", render: (r: Any) => (
      <ExplainButton source={{ ticketId: r.ticket_id }}><b className="mono">{r.frustration_score}</b></ExplainButton>) },
    ...DIMENSION_KEYS.map((k) => ({ key: `${k}_score`, label: SHORT[k], num: true, filter: "num",
      render: (r: Any) => <LevelBadge dim={k} level={r[`${k}_level`]} score={r[`${k}_score`]} /> })),
    { key: "outcome_status", label: "Status", filter: "select" },
  ];
  return (
    <Card title="Ticket explorer" sub="every ticket scored · sort and filter from the column headers · click a score to see how it was computed"
          right={d && <span className="chip">{fmt.i(d.total)} tickets</span>}>
      {q.error && !d ? <ErrorBox error={q.error} /> : !d ? <Loading /> : (
        <div className={q.isPlaceholderData ? "stale" : ""}>
          <DataTable rows={d.items} server={st.table(d.total, { ...d.options, severity: SEV_ORDER })} columns={columns} />
        </div>
      )}
    </Card>
  );
}

export default function Experience() {
  const { qs } = useFilters();
  const q = useApi(`/v1/experience/summary${qs}`);
  const [params] = useSearchParams();
  const deep = params.get("explain");  // /experience?explain=<ticket_id> opens the score explanation directly
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Experience Analytics</div>
          <h2>What employees are telling the service desk</h2>
          <p>How frustrated employees are, and beyond that: how much it hurts the business, how urgent it is, and whether they still trust IT.</p>
        </div>
        {deep && <ExplainButton source={{ ticketId: deep }} defaultOpen>{deep}</ExplainButton>}
      </div>
      <QueryState q={q}>
        {(d: Any) => d.kpis.tickets === 0 ? <div className="empty">No tickets for this scope</div> : (
          <>
            <div className="grid g-4">
              <Kpi label="Avg frustration" value={fmt.n(d.kpis.avg_frustration)} unit="/100" accent="var(--human)"
                   deltaLabel={`${fmt.i(d.kpis.tickets)} tickets · ${fmt.pct(d.kpis.critical_high_share_pct, 0)} high or critical`} />
              <Kpi label="High business impact" value={fmt.pct(d.dimensions.impact.high_pct)} accent={DIMENSION_COLOR.impact}
                   deltaLabel={`${fmt.pct(d.dimensions.impact.elevated_pct, 0)} medium or high`}
                   hint="Work stopped, hours lost, meetings disrupted, data lost or a whole team affected" />
              <Kpi label="Urgent" value={fmt.pct(d.dimensions.urgency.high_pct)} accent={DIMENSION_COLOR.urgency}
                   deltaLabel={`${fmt.pct(d.dimensions.urgency.elevated_pct, 0)} medium or high`}
                   hint="Explicit urgency, asks for action, deadlines, escalations" />
              <Kpi label="Trust in IT at risk" value={fmt.pct(d.dimensions.trust.high_pct)} accent={DIMENSION_COLOR.trust}
                   deltaLabel={`${fmt.pct(d.dimensions.trust.elevated_pct, 0)} medium or high`}
                   hint="The fix didn't hold, the issue keeps coming back, repeat contacts, reopened tickets" />
            </div>

            <BeyondFrustration dims={d.dimensions} />

            <AnalystOnly>
              <div className="grid g-4 mt">
                <Kpi label="Experience Index" value={fmt.n(d.kpis.employee_experience_index)} accent="var(--machine)" />
                <Kpi label="Repeat contacts" value={fmt.pct(d.kpis.repeat_contact_rate_pct)} accent="var(--human)" deltaLabel="flagged by service desk"
                     hint="Share of tickets the service desk flagged as a repeat contact" />
                <Kpi label="Escalations" value={fmt.pct(d.kpis.escalation_rate_pct)} accent="var(--critical)" />
                <Kpi label="Negative sentiment" value={fmt.pct(d.kpis.negative_sentiment_share_pct)} accent="var(--human)"
                     deltaLabel={`avg polarity ${fmt.n(d.kpis.avg_sentiment, 2)}`} />
              </div>
            </AnalystOnly>

            <div className="grid g-2 mt">
              <ChartCard title="Frustration by week" sub="average score of tickets raised" table={d.weekly}
                         columns={[{ key: "week", label: "Week" }, { key: "tickets", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }, { key: "repeat_contacts", label: "Repeats", num: true }, { key: "escalations", label: "Escalations", num: true }]}>
                <TrendChart data={d.weekly} series={[{ key: "avg_frustration", name: "Avg frustration", color: "var(--chart-human)" }]} yDomain={[0, 100]} />
              </ChartCard>
              <ChartCard title="Frustration climbs with every repeat contact" sub="avg frustration by contact number (#1 = first contact) on the same issue" table={d.repeat_ladder}
                         columns={[{ key: "contact_number", label: "Contact #", num: true }, { key: "tickets", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }]}>
                <Bars data={d.repeat_ladder.map((r: Any) => ({ ...r, label: `#${r.contact_number}` }))} x="label" y="avg_frustration" name="Avg frustration" color="var(--chart-human)"
                      labels emphasize={(_, i) => i === d.repeat_ladder.length - 1} />
              </ChartCard>
            </div>

            <AnalystOnly>
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
                <ChartCard title="Ticket volume by week" sub="all channels" table={d.weekly}
                           columns={[{ key: "week", label: "Week" }, { key: "tickets", label: "Tickets", num: true }]}>
                  <Bars data={d.weekly.map((w: Any) => ({ ...w, label: `W${w.week}` }))} x="label" y="tickets" name="Tickets" color="var(--chart-human)" height={200} yFmt={(v) => fmt.i(v)} />
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
              <div className="mt">
                <Card title="Top frustration language" sub="phrases weighted by the lexicon · score a new ticket on Diagnosis Assist"
                      right={<Link to="/diagnosis" className="note">Score a ticket →</Link>}>
                  <DataTable rows={d.drivers.phrases} pageSize={5} sortable columns={[
                    { key: "phrase", label: "Phrase", filter: "text", render: (r: Any) => <span>“{r.phrase}”</span> },
                    { key: "weight", label: "Weight", num: true, filter: "num" },
                    { key: "tickets", label: "Tickets", num: true, filter: "num" },
                    { key: "avg_frustration", label: "Avg frustr.", num: true, filter: "num" },
                  ]} />
                </Card>
              </div>
            </AnalystOnly>

            <div className="mt"><TicketExplorer /></div>
          </>
        )}
      </QueryState>
    </>
  );
}
