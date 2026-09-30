# DEX Sentinel: Solution Document

*Outcome-Based Digital Employee Experience Analytics Platform · Hack-Horizon 2026*

All figures below come from the running MVP on the bundled simulated dataset (260 devices, 3,120 device-weeks, 326 tickets, 46 remediation cases, 12 weeks). None of it is real employee or endpoint data.

---

## 1. Product vision

Every IT organisation measures how fast tickets close. Few can say whether an employee's working day got better. DEX Sentinel makes **experience recovery** the unit of success. It fuses what employees *say* with what their devices *do*, uses that fusion to find the cause, and then proves the fix worked with numbers.

## 2. Executive summary

- Service desks diagnose from symptoms described in employees' own words and rarely check them against device telemetry. Tickets close on silence, not on verified recovery.
- DEX Sentinel scores every call, chat and ticket for frustration, emotion and severity. It scores every device-week for health and telemetry severity. It then correlates the two, ranks root causes, recommends a fix, and measures the DEX Score before and after.
- On the simulated fleet:
  - Frustration tracks telemetry at **r = 0.83**.
  - Remediations lifted the affected employees' DEX Score from **64.0 to 87.6 (+36.9%)**.
  - Repeat contacts fell from **46.8% to 0.7%**.
  - Under the default cost assumptions that is worth about **$115k a year**.

## 3. Business problem

| Pain | Consequence |
|---|---|
| "My laptop is slow" can map to five different objective causes | Trial-and-error troubleshooting, long calls, reassignments |
| Tickets close when the employee stops calling | Repeat contacts, hidden productivity loss, eroded trust |
| Leadership sees SLA and closure metrics | Investment decisions aren't tied to experience outcomes |

## 4. Solution architecture

```
Service-desk calls / tickets / chats ─┐
Weekly endpoint telemetry            ─┼─► Ingestion & validation ─► Analytical store (SQLite → Postgres)
Remediation register                 ─┘                                   │
        ┌─────────────────────────────── DEX Sentinel API ────────────────┴──────────────────┐
        │ M1 Experience Analytics │ M2 Telemetry Intelligence │ M3 Correlation Engine        │
        │ M4 Diagnosis Assist + Root Cause Engine (+ ML second opinion)                      │
        │ M5 DEX Copilot: agent + tools + RAG over remediation runbooks                      │
        │ M6 Outcome Reporting │ M7 DEX Score │ Executive Insights                           │
        └────────────────────────────────────────────────────────────────────────────────────┘
                                 ▼
             Executive Dashboard · module workspaces · Device 360 · CSV export · OpenAPI
```

- **Stack:** Python 3 (FastAPI, pandas, SciPy, scikit-learn, SQLAlchemy) and React + TypeScript + Recharts. The API and UI deploy as one container.
- **LLM:** Claude (default) or Azure OpenAI through a provider-neutral tool registry. A deterministic grounded engine handles offline use and failover.

## 5. Data model

| Entity | Grain | Key fields |
|---|---|---|
| Device | device | device_id, employee, department, work mode, model, age |
| Telemetry | device × week | boot s, app hangs, latency ms, packet loss %, policy compliant, hardware / battery / disk health |
| Ticket | contact | channel (Call/Chat/Portal), category, repeat flag & number, text, resolution hours, outcome (Resolved/Escalated/Reopened) |
| Remediation | case | problem type, root cause, week, action, pre/post telemetry, ticket rate, frustration, repeat rate |
| *Derived:* enriched ticket | contact | frustration, sentiment, emotion, severity, telemetry at ticket week, category severities |
| *Derived:* device-week fact | device × week | ticket count, repeats, escalations, crash events, frustration burden, device health, telemetry severity |
| Audit | event | diagnosis log, Copilot log, dataset versions, settings |

## 6. Simulated dataset design

- About 28% of devices are seeded as *declining* towards one of five root causes. Each one's telemetry ramps up to a remediation week (6–9) and then recovers.
- Ticket probability and category follow that week's actual telemetry severity. The correlations are therefore properties of the data, not assumptions laid on top.
- Ticket text is composed from symptom phrases plus frustration and repeat markers. A hidden ground-truth tier was used to validate the lexicon at 93.3%.
- **Known quirk:** 25 of the 46 remediation cases have only 1–2 post-fix tickets. The UI shows `n=` beside every post-fix average, and the aggregate is the meaningful read.

## 7. AI models

| Model | Method | Evaluation |
|---|---|---|
| Frustration / sentiment | Weighted keyword lexicon (validated) plus behavioural boost: +10 per prior contact, +15 per escalation, capped at 100 | 93.3% tier agreement with hidden ground truth |
| Emotion | Lexicon → Anger / Frustration / Anxiety / Inquiry / Neutral with a distribution | Explainable phrase hits |
| Device health | Spec formula: (100 − 0.1·boot − 3·hangs − 4·crashes − 0.05·latency)·0.8 + 0.2·hardware | Unit-tested |
| Telemetry severity | Distance past warn → critical per category, composite = 60% worst + 40% mean | Golden lifts |
| Root cause (primary) | 65% telemetry severity + 35% text-category fusion, then rule-based sub-causes | 100% top-1 vs category* |
| Root cause (second opinion) | Logistic regression on TF-IDF text + standardised telemetry | 99.6% 5-fold CV (text-only 100%, telemetry-only 99.6%)* |
| Predictive risk ("fix before they call") | LightGBM on telemetry levels and 1–4-week trends, recent experience history and device profile, predicting a frustrated ticket (frustration ≥ 60) next week. Per-prediction feature contributions grouped into drivers; isotonic calibration on out-of-time predictions (`engines/forecast.py`) | Rolling-origin backtest vs the rule at-risk score. On a 5,000-device × 26-week simulated fleet (`python -m app.data.simulator`): 72.3% of next-week frustrated tickets caught from the top 5% of devices vs 48.8% for rules; PR-AUC 0.455 vs 0.250. The bundled sample is flagged low-sample.* |
| Copilot | Tool-using LLM agent (Claude `claude-opus-5-5` / Azure OpenAI), structured JSON output, RAG over 22 runbooks (BM25) | Grounding rule: every number must come from a tool result; mocked-loop test |

\*The simulated categories are cleanly separable. Real-world accuracy will be lower, and the fusion weights should be refit on real diagnosis outcomes.

## 8. User interface

The app has a dark "machine vs human" design system: teal marks telemetry and amber marks experience. Both light and dark themes are available. Chart colours are validated for colour-vision deficiency on both surfaces, and every chart has a table-view twin and a hover tooltip. A global filter row (department, device model, work mode, week range) scopes every analytics page. The views are: Executive Dashboard, the seven module workspaces, Device 360, and Data & Settings.

## 9. Executive dashboard

KPIs:
- DEX Score **79.3** (Good, +3.5 pts vs the first half of the window)
- Experience Recovery **+36.9%**
- Business impact **$114,734/yr**
- Correlation score **0.83**
- At-risk devices **8**
- EEI **94.3**
- Device Health **90.5**
- Repeat-contact rate **46.0%** (recomputed within the window)
- Average frustration **54.1**

It also shows the DEX and frustration trends, the top telemetry and experience drivers, generated insights, DEX by department, the before/after summary and the at-risk device list.

## 10. Correlation analytics

- **Severity lift** (worst vs best bucket, frustration): boot **1.9×**, latency **1.9×**, app hangs **1.8×**, hardware health **1.6×**.
- **Incidence lift:** non-compliant device-weeks raise a Login/Auth ticket **28.5%** of the time vs **0%** when compliant (∞). A binary signal gates *whether* tickets happen, so it needs incidence lift rather than severity lift.
- **Correlation matrix:** 8 experience signals × 9 telemetry signals, with Pearson r, p-values, Spearman, and explicit grain (ticket or device-week).
- **Risk heatmap:** cohort × signal, breach rate × frustration. Plus a cohort × week frustration heatmap.
- **Impact ranking:** excess tickets on breached weeks vs the healthy-week rate, weighted by frustration and repeat share. Network latency ranks first, with about 40 excess tickets at average frustration 82.

## 11. Diagnosis assist

Input is a ticket text plus a device (and optionally the week, prior contacts and escalations). Output:
- Frustration score and severity
- Five causes ranked by likelihood and confidence
- The leading sub-cause
- Telemetry evidence (the reading, fleet median, thresholds, and weeks breached out of the last 4)
- The recommended fix with its runbook ID
- The expected outcome, taken from past fixes of the same class
- An ML second opinion
- The ticket history

Example (TCK-00002, DEV-0002, week 6): *"This is unacceptable at this point. Outlook keeps crashing."*
- Frustration **62/100 (High, anger)**
- Cause **Application Crash**: 100% likelihood, **99% confidence**
- Evidence: 9 app hangs in the week (critical above 6), breached in 3 of the last 4 weeks
- Fix: **Reinstall and patch the affected application** (KB-APP-001)
- Expected outcome: repeat contacts −100%, ticket rate −64%
- The ML model agrees

## 12. Root cause engine

1. **Category fusion.** Telemetry severity normalised to 0–1 per category (65%) is combined with the ticket's keyword hits per category, normalised (35%). *Likelihood* is the share of the fused score; *confidence* is the absolute evidence strength, plus a bonus when the breach has persisted over recent weeks.
2. **Sub-cause rules** within the category use ticket wording, device attributes and telemetry trend. Examples: an Outlook complaint that repeats points to *mail profile corruption*; a rising hang trend points to a *memory leak*; a remote worker with "home" in the text points to *home ISP quality*.
3. **Guardrail.** When there is no telemetry anomaly and no symptom match, the result is flagged *inconclusive* and routed to L1 knowledge instead of forcing a fix.

## 13. Outcome reporting

Every remediation is measured before (weeks before the fix) and after (the fix week onward). Frustration, repeat-contact rate, tickets per week, telemetry and DEX Score are compared, with repeats recomputed inside each window so a pre-fix ticket can't make a post-fix one look like a repeat.

- Aggregate:
  - Frustration **69.0 → 58.2**
  - Repeat contacts **46.8% → 0.7%**
  - Tickets per week **0.41 → 0.15**
  - **45 of 46** cases improved
- Cohort DEX **64.0 → 87.6 (+36.9%)**.
- Recovery by category: Performance +40.8%, Network +39.4%, Application Crash +35.7%, Login/Auth +33.2%, Hardware +30.4%.
- Business impact: about 621 tickets avoided and about 1,838 productive hours recovered per year, **$114,734** in total. The assumptions ($22 per ticket, $55 per hour, 50% productivity loss) can be edited in Settings.

## 14. DEX Score framework

`DEX = 0.35·EEI + 0.25·DHS + 0.20·RSS + 0.10·TRE + 0.10·STS`

| Component | Definition |
|---|---|
| EEI: Employee Experience Index | 100 − mean weekly frustration burden per employee-week (burden = highest frustration raised that week, 0 when there is no contact) |
| DHS: Device Health Score | mean Device Health Score over the device-weeks |
| RSS: Remediation Success Score | 100 × (1 − repeat-contact rate), with repeats recomputed within the window |
| TRE: Ticket Resolution Efficiency | mean over tickets of first-time resolution × SLA attainment (default 8 h SLA) |
| STS: Sentiment Trend Score | 50 − 50·tanh(weekly burden slope / 10). 50 means flat; higher means improving |

Bands: Excellent ≥ 85, Good ≥ 70, Fair ≥ 55, Poor < 55. The score can be computed for the fleet, any cohort or a single device, over any window. **Experience Recovery % = (after − before) / before × 100**; the spec's example of 52 → 78 gives 50%, and this is unit-tested.

## 15. Executive insights (generated)

1. Sentiment tracks telemetry: r = 0.832 (strong, n = 326).
2. Network latency is the #1 experience driver: about 40 excess tickets across 17 devices, average frustration 82.1, 62% repeat contacts.
3. Non-compliance generates login tickets: 28.5% vs 0.0% of device-weeks. Policy remediation is ticket prevention.
4. DEX Score improved 3.5 pts from weeks 1–6 to weeks 7–12.
5. Remediation recovered experience by +36.9%.
6. The fixes are worth $114,734 a year.
7. HR has the lowest DEX Score (78.3 vs 80.4 in Sales). It should be prioritised in the next remediation wave.

## 15b. Module 8: Upload Dataset (real-time data)

New data arrives through `.xlsx` or `.csv` uploads (up to 200 MB per file), in replace or append mode. **Submit for Analysis** starts a staged background job:
1. read
2. validate and normalise
3. sentiment
4. correlation
5. outcomes and DEX Score
6. publish

The job builds a complete new analytical store and swaps it in atomically, so every module (dashboard, correlation, diagnosis, Copilot, outcomes) reflects the new data at once, and a failed upload leaves the live data untouched.

The ingestion layer accepts real exports:
- It maps column aliases.
- It derives weeks from dates.
- It rolls daily telemetry up to device-weeks.
- It infers ticket categories from the text and repeat contacts from history.
- It computes remediation before/after metrics when they aren't supplied.

Every derivation is shown to the user. In testing, a ServiceNow/DEX-style export with none of the canonical column names still produced r = 0.81. A 163 MB file (2.34M device-weeks) completes in about 80 s.

## 16. Demo story (7 minutes)

1. **Executive Dashboard (60 s).** "Ticket SLAs look fine, but is experience improving?" Show the DEX Score of 79.3, the dip in weeks 6–7 and the recovery, +36.9% recovery and $115k of value.
2. **Correlation (60 s).** "Frustration isn't random." Show r = 0.83, boot >85 s at 1.9× frustration, non-compliance creating login tickets (28.5% vs 0%), and the risk heatmap.
3. **Experience Analytics (45 s).** Show the repeat-contact ladder (frustration climbs with every contact). Paste a ticket into the live analyser.
4. **Diagnosis Assist (90 s).** Pick TCK-00002, the briefing's Outlook example. The result is Application Crash at 99% confidence, with 9 hangs breached 3 of 4 weeks as evidence, fix KB-APP-001, an expected −64% ticket rate, and the ML model agreeing.
5. **DEX Copilot (60 s).** Click "Explain with DEX Copilot". It returns a business-language answer, the tool trace (diagnose → KB → outcomes) and citations. Then ask: "Which department has the worst experience and what should we fix first?"
6. **Device 360 (30 s).** Open DEV-0003. Latency climbs until the week-7 fix, then drops. The DEX Score moves from 68.1 to 80.7.
7. **Outcome Reporting (45 s).** Show 45/46 cases improved and the recovery by category. Note the honest n= disclosure, then export to CSV.
8. **Upload Dataset, M8 (45 s).** Drop a new telemetry export and a ticket export, then click Submit for Analysis. Watch the stages run, see the before/after comparison, and open the dashboard to show it updated.
9. **Close (15 s).** "Fuse the signal, diagnose the cause, prove the fix."

## 17. Hackathon presentation

Map the existing 12-slide deck (`DEX_Sentinel_Pitch_Deck.pptx`) to the live MVP:

| Slide | Content | Live proof |
|---|---|---|
| 1–2 | Title, problem | — |
| 3 | By the numbers | Settings → dataset card |
| 4 | Neither signal is enough alone | Correlation matrix |
| 5 | Pipeline | Architecture (§4) |
| 6 | Correlation lifts | Correlation page (identical numbers) |
| 7 | Diagnosis example | Diagnosis Assist (TCK-00002) |
| 8 | Outcomes | Outcome Reporting |
| 9 | Why trust the numbers | Golden tests, `n=` disclosure, model metrics |
| 10 | Business impact | Dashboard KPIs, Settings assumptions |
| 11 | Roadmap | §18 |

Suggested additions: one slide on the **DEX Score framework** (§14) and one on the **DEX Copilot**, showing its tool trace and grounding rule.

## 18. Future roadmap

1. **Connect real signals.** Add connectors for ServiceNow / Jira SM (tickets, CSAT), Teams / telephony transcripts, and DEX telemetry platforms (Nexthink, 1E, Intune / Endpoint Analytics). Move to Postgres with scheduled ingestion.
2. **Learn from real language.** Tune the lexicon on real tickets. Add a transformer sentiment and emotion model, with the lexicon kept as the explainable baseline. Add multilingual support.
3. **Fit, don't assume.** Calibrate thresholds on fleet baselines, and learn the fusion weights and DEX sub-score scalings from confirmed diagnoses and outcomes.
4. **Go proactive.** Trigger remediation scripts automatically for at-risk devices, and have the Copilot draft the change and employee communication with human approval.
5. **Close the loop in ITSM.** Write diagnoses and verified-recovery status back to the ticket, and offer a "Resolved, verified" closure code (KB-GEN-001).
6. **Enterprise hardening.** Add SSO/RBAC, row-level security by business unit, audit export, a data-retention policy and full PII redaction for transcripts.
