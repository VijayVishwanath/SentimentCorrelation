# DEX Sentinel: 7-Minute Hackathon Pitch

## Problem (1 minute)

**The Digital Employee Experience Crisis**

- **9,435 IT tickets** analyzed: 74% express only baseline frustration—not because they're calm, but because the text doesn't capture *why* their work stopped.
- IT support teams are **flying blind**: They see "Outlook crashes" but not "I can't get my work done AND my whole team is affected AND I have a presentation in 2 hours."
- Current frustration scores alone miss:
  - **19% of tickets** signal productivity loss
  - **18% signal** meeting or client disruption  
  - **8% signal** that the same fix didn't hold
- **Result**: Reactive firefighting. Slow remediation. Employee churn. Wasted IT budget on low-impact fixes.

---

## Solution (1 minute)

**DEX Sentinel: Three Dimensions Beyond Frustration**

We expanded sentiment analysis to capture **what matters to the business**, not just emotion:

### 1. **Business Impact** (Can't work? Data loss? Team affected?)
   - Scores the actual cost of an issue to the organization
   - Weights: "can't work" (+60) > "productivity loss" (+40) > "meetings" (+20)

### 2. **Urgency** (Deadline? Escalating? Asking for action?)
   - Captures business pressure and time sensitivity
   - Weights: "explicit urgency" (+60) > "deadline" (+15) > "escalation behavior" (+25)

### 3. **Trust in IT** (Did the last fix hold? Is this the 3rd report?)
   - Signals customer confidence and repeat-contact risk
   - Weights: "fix didn't hold" (+45) > "recurrence" (+20) > "prior contacts" (×12, capped ×36)

**All rule-based, explainable, and validated on 9,597 real tickets.**

---

## How It Works (1 minute)

1. **Ingest**: ServiceNow API (live) or CSV/Excel (one-click upload)
2. **Score**: Frustration (unchanged, 93.3% validated) + 3 Dimensions (rule-based cues)
3. **Diagnose**: Root cause ranking (65% telemetry + 35% text) + priority triage
4. **Forecast**: Next-week frustration risk (LightGBM, calibrated)
5. **Correlate**: Device health ↔ Employee sentiment; rank by impact
6. **Remediate**: 
   - Manual: Copilot-assisted fix recommendations with evidence
   - Auto: One-click software removal (MCP, audit trail, safe)
7. **Track**: Causal outcomes (difference-in-differences, separates "fixed" from "would've improved anyway")

---

## Differentiators (2 minutes)

### **1. Explainable Sentiment**
- No black-box ML on sentiment. Every score shows *which phrases* triggered it.
- Users see: "High business impact because: 'can't work' (60pts) + 'team is affected' (25pts)"
- **Why it matters**: Jury can verify our numbers. IT can trust the priorities.

### **2. Dimension-Driven Triage**
- High urgency → +10 priority boost
- High business impact → +10 priority boost
- Hang/heat language detected → +5 thermal boost
- Device temperature ≥95°C → flagged in priority reasons
- **Why it matters**: P1 tickets are now defensible: "urgent + high impact + thermal."

### **3. Honest Causal Tracking**
- We don't claim "this fix caused X improvement."
- We measure: "This group improved by Y; a matched control group improved by Z; the fix caused (Y - Z)."
- Recovery %, case register, before/after metrics.
- **Why it matters**: CFOs see real ROI, not inflated numbers.

### **4. Analyst vs. Jury View**
- **Default**: Simple, executive-ready dashboard (7 nav entries, core metrics, Fix Now buttons).
- **Analyst toggle**: Deep dives (calibration charts, heatmaps, formulas, audit trails).
- **Why it matters**: Same app for both audiences. Jury sees proof, analysts get tools.

### **5. Automated Remediation**
- Security team emails a version number.
- We find all devices with that exact version.
- Show a safe-removal plan (block system-critical, show dependencies).
- Execute with human approval, audit trail, rollback on error.
- **Why it matters**: Closes the loop from detection to fix in minutes, not weeks.

---

## Technical Proof (1 minute)

| Metric | Status |
|--------|--------|
| **Frustration Scoring** | 93.3% agreement with domain experts; unchanged from baseline (golden tests pass) |
| **Dimension Scoring** | 9,597 tickets scored on all three dimensions; cues highlighted in UI |
| **Database** | 2,600 devices, 12 weeks history, 31,200 device-weeks, SQLite + in-memory cache |
| **ML Forecast** | LightGBM model, calibrated on out-of-time data, risk 0–100% |
| **Root Cause** | Fusion of device telemetry (65%) and ticket language (35%); ranked confidence |
| **Tests** | 153 backend tests passing; frontend typecheck clean; E2E in Edge |
| **API** | FastAPI, 5 analytics engines, 8 endpoints, ServiceNow + Claude Copilot integrations |

---

## Live Demo Moment

**Show command center:**
- DEX Score card (one number summarizing experience + device health)
- Top 3 actions (prioritized by impact/urgency/trust)

**Show experience page:**
- KPI row: avg frustration, high business impact %, urgent %, trust at risk %
- "Beyond frustration" trend: 3 dimensions by week
- Ticket explorer: sort/filter by impact, urgency, trust

**Show diagnosis:**
- Paste a ticket: "Outlook crashes, slowing me down, I can't get this report to the CFO before lunch"
- Output: Frustration (72), Impact (85 High), Urgency (95 High), Trust (Low), Primary concern: Business impact
- Root cause: Hangs + boot slowness, priority P1 (base 72 + impact boost +10 + urgency boost +10 = 92)

**Show proof & value:**
- Causal outcomes: "After fix, this cohort's frustration dropped by 18 points; matched control dropped by 4; fix caused 14-point gain"

---

## Numbers to Cite

- **9,597 tickets**, 2,600 devices, 12 weeks (live demo data)
- **3 dimensions** beyond frustration (explainable, rule-based)
- **7 nav sections** (jury-ready, analyst mode off by default)
- **153 tests** all passing (no regressions)
- **93.3% validated** frustration score
- **Thermal detection**: Device temperature + hang language → priority boost
- **Causal measurement**: Separates fix effect from trend
- **One-click remediation**: ServiceNow sync + MCP auto-removal

---

## The Ask

DEX Sentinel answers the question every IT leader has:

> **"Why are my employees frustrated, which problems should I fix first, and how much will the fix actually help?"**

We deliver:
1. **Why**: Three dimensions that explain frustration beyond emotion
2. **Which**: Priority triage backed by business impact + urgency + trust
3. **How much**: Honest causal outcomes (no inflated claims)

**On a jury-ready interface that takes 2 minutes to understand and 7 days to master.**

---

## Closing (30 seconds)

We've built a **production-grade sentiment platform** that:
- ✅ Explains every number (explainable AI, not a black box)
- ✅ Tracks causal impact (honest measurement, not vanity metrics)
- ✅ Closes the remediation loop (ServiceNow sync → diagnosis → one-click fix → outcome)
- ✅ Works with real data (9,597 tickets, validated scoring)
- ✅ Scales (in-memory cache, device-week rollups, forecast on 2,600 devices)

**DEX Sentinel turns frustrated employee tickets into measurable business outcomes.**

---

## Appendix: Quick Facts

**Frontend**: React 18, TypeScript, 7 pages, analyst mode toggle, deep tabs  
**Backend**: FastAPI, 8 analytics engines, 153 tests, Sonnet 5.5 copilot  
**Data**: SQLite, 9,597 tickets, 2,600 devices, temperature signal  
**Integrations**: ServiceNow (live), Claude Copilot (tool agent), MCP (safe removal)  
**Validation**: Golden frustration numbers pinned; dimension cues highlighted; causal measurement defended  
