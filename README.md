# DEX Sentinel

**Outcome-based Digital Employee Experience analytics.** DEX Sentinel correlates subjective employee-experience signals (service-desk calls, ticket language, frustration, repeat contacts, escalations) with objective endpoint telemetry (boot duration, application hangs, network quality, policy state, hardware health). Service-desk teams use it to diagnose faster and remediate the actual cause. Leadership uses it to see whether the employee experience got better, not just whether tickets were closed.

> Hack-Horizon 2026 · the dataset is fully simulated, with seeded, verifiable correlations. No real employee data is used.

---

## What's in the box

| Module | What it does | Where |
|---|---|---|
| **Executive Dashboard** | DEX Score, Experience Recovery %, EEI, Device Health, Correlation Score, repeat-contact rate, business-impact savings, trends, top drivers, generated insights, at-risk devices | `/` |
| **M1 Experience Analytics** | Sentiment, frustration score (0–100), emotion classification, experience severity, repeat-contact ladder, live text analyser, ticket explorer | `/experience` |
| **M2 Telemetry Intelligence** | Device Health Score, Telemetry Severity Score, threshold breaches, fleet health bands, device fleet table | `/telemetry` |
| **M3 Correlation Engine** | Severity lift, compliance incidence lift, Pearson/Spearman correlation matrix, risk heatmap, frustration heatmap, impact ranking, scatter with fit | `/correlation` |
| **M4 Diagnosis Assist + Root Cause Engine** | 65/35 telemetry/text fusion, then ranked causes, confidence, sub-cause, telemetry evidence, fix and expected outcome, with an ML second opinion | `/diagnosis` |
| **M5 DEX Copilot** | Tool-using agent grounded in the engines, with RAG over 22 remediation runbooks. Runs on Claude or Azure OpenAI, or the grounded template engine offline | `/copilot` |
| **M6 Outcome Reporting** | Before vs after remediation, Experience Recovery %, per-category and per-case register, business impact, CSV export | `/outcomes` |
| **M7 DEX Score** | Formula, component definitions, trends, cohort breakdown, what-if simulator | `/dex-score` |
| **M8 Upload Dataset** | Upload new real-time data (.xlsx or .csv, up to 200 MB per file, replace or append), then **Submit for Analysis** re-runs the whole pipeline and refreshes every screen, with a before/after comparison | `/upload` |
| Device 360 | Per-device telemetry history with the remediation week marked, tickets and before/after | `/devices/:id` |
| Data & Settings | Business-impact assumptions, model evaluation, API key | `/settings` |

## Quick start

**Windows (PowerShell):**

```powershell
.\run.ps1                # first run creates .venv, installs deps, builds the UI, serves http://127.0.0.1:8000
.\run.ps1 -Port 8010     # if port 8000 is taken
.\run.ps1 -Dev           # API with auto-reload + Vite dev server on http://localhost:5173
.\run.ps1 -Test          # backend test suite
```

**macOS / Linux / Git Bash:** `./run.sh [port]`

**Docker:** `docker build -t dex-sentinel . && docker run -p 8080:8080 -e ANTHROPIC_API_KEY=... dex-sentinel`

**Google Cloud (Cloud Run):** `.\deploy\gcp\deploy.ps1 -ProjectId YOUR_PROJECT` deploys a public, access-key-protected
demo in asia-south1. See [deploy/gcp/README.md](deploy/gcp/README.md).

Prerequisites: Python 3.11+ and Node 18+. On first start the bundled workbook `data/DEX_Sentinel_Simulated_Dataset.xlsx` is validated and loaded into SQLite (`data/dex_sentinel.db`).

### Enable the LLM Copilot (optional)

Copy `.env.example` to `.env` and set **one** of the following:

- `ANTHROPIC_API_KEY`: Claude. This is the default provider; the model is `claude-opus-5-5`, overridable via `DEX_ANTHROPIC_MODEL`. Server-side refusal fallbacks are enabled.
- `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_DEPLOYMENT`: Azure OpenAI.

With no key, the Copilot uses the **grounded template engine**. It calls the same tools and returns the same schema, so the demo works fully offline. If an LLM call fails or is refused, the app falls back to the template engine automatically and says so in the UI.

## Uploading new data (Module 8)

1. Open **Upload Dataset (M8)** and drop an `.xlsx` workbook (one sheet per table) or one or more `.csv` files (one per table). Each file can be up to **200 MB**; up to 10 files per upload.
2. Choose **Replace current dataset**, or **Append to current dataset** to merge new rows by key (for example, a weekly feed).
3. Click **Submit for Analysis**. A background job then:
   - reads the files
   - validates and normalises them
   - scores sentiment and frustration
   - correlates experience with telemetry
   - computes diagnosis inputs, outcomes and the DEX Score
   - publishes to all dashboards

   The new dataset is built off to the side and swapped in only if analysis succeeds. A failed upload never touches the live data.
4. The results panel compares headline metrics before and after, lists everything the system derived, and links to every module.

Real-world exports work as they are:
- Column names are matched by alias ("Device ID", "Short Description", "Opened At", "Boot Time (sec)", and so on).
- Dates become week numbers, and daily or event-level telemetry rolls up to device-weeks.
- Missing fields are derived:
  - ticket category from the text
  - repeat contacts from history
  - devices from the IDs they appear under
  - remediation before/after metrics from the data
- Unmeasured signals are skipped rather than scored as zero.

The column guide and CSV templates for each table are on the page. Scale tested: a 163 MB upload (2.34M device-weeks, 120k tickets) is analysed and live in about 80 s.

API: `POST /api/v1/datasets/analyze` (multipart `files`, `mode`) → `GET /api/v1/datasets/jobs/{id}`; see also `/datasets/active`, `/datasets/schema`, `/datasets/templates/{table}.csv`, `/datasets/restore-sample`.

## Architecture

```
 Excel / CSV upload ─► Ingestion + validation (schema, types, keys, referential integrity) ─► SQLite / Postgres
                                                                                  │
 ┌──────────────────────────────── FastAPI  /api/v1 ──────────────────────────────┴───────────┐
 │ M1 experience.py   lexicon sentiment · frustration · emotion · severity                     │
 │ M2 telemetry.py    device health · category severity · telemetry severity score             │
 │ M3 correlation.py  lift · incidence lift · Pearson/Spearman matrix · heatmaps · impact rank  │
 │ M4 diagnosis.py    65/35 fusion · sub-cause rules · evidence · expected outcome   + ml.py     │
 │ M5 copilot/        agent loop (Claude | Azure OpenAI | template) · tools.py · BM25 RAG · KB   │
 │ M6 outcomes.py     pre/post windows · Experience Recovery % · business impact                │
 │ M7 dex_score.py    0.35·EEI + 0.25·DHS + 0.20·RSS + 0.10·TRE + 0.10·STS                      │
 │    insights.py     executive insights, each tied to a metric                                 │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
                     ▲  JSON (NaN-safe)                       audit log: diagnoses, copilot calls
 React 18 + TypeScript + Recharts SPA (built to frontend/dist, served by FastAPI on the same origin)
```

- **Store:** an in-memory analytical snapshot (raw tables, the ticket↔telemetry join, and a 3,120-row device-week fact table), rebuilt atomically on upload. Heavy views are memoised and pre-warmed at startup.
- **Security:** optional `DEX_API_KEY` (checked in constant time), input validation on every body and query parameter, upload size and type limits, security headers, a PII-masking switch (`DEX_MASK_PII`), and request IDs plus structured access logs.
- **API docs:** OpenAPI is served at `/docs`.

## Validated numbers

The Python engines reproduce every figure in the judge briefing. These are enforced by `backend/tests/test_golden.py`:

| Figure | Value |
|---|---|
| Severity lift: boot / latency / app hangs / hardware health | 1.9× / 1.9× / 1.8× / 1.6× |
| Login/Auth ticket incidence: non-compliant vs compliant weeks | 28.5% vs 0.0% (∞) |
| Remediation outcomes (46 cases): frustration | 69.0 → 58.2 |
| Repeat-contact rate | 46.8% → 0.7% |
| Tickets per week | 0.41 → 0.15 (45 of 46 cases improved) |
| Briefing example "This is unacceptable at this point. Outlook keeps crashing." | High 62/100 · Application Crash 100% |

New in the MVP:
- Correlation score r = 0.83 (frustration vs telemetry severity, n = 326).
- DEX Score for the remediated cohort rises from 64.0 to 87.6 (**+36.9% Experience Recovery**).
- About $115k annualised value under the default cost assumptions.

## Tests

```powershell
cd backend; ..\.venv\Scripts\python -m pytest -q     # 68 tests: golden figures, engines, API, uploads, Copilot tool loop (mocked)
cd frontend; npm run typecheck
```

## Project layout

```
backend/app/        FastAPI app: api/ (routes), engines/ (M1-M4, M6, M7, ML, insights), copilot/ (agent, providers, tools, retriever, kb/*.md), data/ (loader, store)
backend/tests/      pytest suite
frontend/src/       React SPA: pages/ (one per module), components/ (UI kit, charts, layout), api.ts
data/               bundled simulated dataset (+ SQLite db at runtime)
docs/SOLUTION.md    hackathon solution document (vision → roadmap, demo story)
```

## Known limitations

- The dataset is simulated. Categories were seeded from telemetry and templated text, so root-cause accuracy here (about 100%) reflects separable synthetic data, not real-world accuracy.
- The lexicon is validated against the dataset's hidden ground truth (93.3%). It needs retuning on real ticket language.
- Some signals are derived because the source data doesn't carry them: crash events are counted from Application-Crash tickets, and VPN failures are weeks with ≥1.5% packet loss. Memory-leak and profile-corruption causes are inferred as sub-causes from ticket language and telemetry trends.
- The fusion weights (65/35), severity thresholds and DEX sub-score scalings are sensible defaults, not fitted parameters.
