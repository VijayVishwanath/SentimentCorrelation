# Deploying DEX Sentinel to Google Cloud (demo tier)

This guide puts DEX Sentinel on a public HTTPS URL using **Cloud Run** in **asia-south1 (Mumbai)**. The whole app
(API and web UI) runs in one container. Visitors unlock it with an **access key**, and **DEX Copilot** uses
**Claude via the Anthropic API**. Most of the work is done by one script.

```
Browser ──HTTPS──► Cloud Run service "dex-sentinel"  (asia-south1)
                    · one container: Hypercorn (HTTP/2) → FastAPI API + React UI
                    · 1 instance max · scales to zero when idle · 2 vCPU / 8 GiB
                    · secrets from Secret Manager: DEX_API_KEY, ANTHROPIC_API_KEY
                    └──HTTPS──► api.anthropic.com   (DEX Copilot answers)
Build: gcloud run deploy --source .  →  Cloud Build (repo Dockerfile)  →  Artifact Registry
```

> **Demo tier:** anything uploaded through Module 8, plus upload history and edited settings, resets to the sample
> dataset when the service restarts, scales to zero, or is redeployed. The Upload screen says so. See
> [Upgrading to production](#upgrading-to-production) for persistent storage.

---

## 1. One-time prerequisites

| # | What | How |
|---|---|---|
| 1 | A Google Cloud **project with billing enabled** | console.cloud.google.com → project picker → *New project*; Billing → link a billing account |
| 2 | Your permissions on that project | **Owner**, or: Cloud Run Admin, Service Account User, Cloud Build Editor, Artifact Registry Admin, Secret Manager Admin, Service Usage Admin (+ Project IAM Admin for step 2 of the script) |
| 3 | **Google Cloud CLI** on your PC | PowerShell: `winget install Google.CloudSDK`, then open a **new** terminal. (Or use *Cloud Shell* in the console, which has it pre-installed.) |
| 4 | Sign in | `gcloud auth login` (opens a browser) |
| 5 | An **Anthropic API key** | console.anthropic.com → API keys. Optional: use `-NoLlm` to deploy without one. |

No Docker is needed on your PC; the image is built in Google Cloud.

## 1b. Can't install the Google Cloud CLI? (company policy)

You don't need anything on your PC. Use one of these browser-only routes.

### Option A: Google Cloud Shell (recommended)

Cloud Shell is a free Linux terminal inside the Google Cloud console. `gcloud` is preinstalled and already signed in.

1. On your PC, locate **`dex-sentinel-source.zip`** in the project folder (a 0.4 MB bundle of the source, without
   `.venv`, `node_modules` or databases). To rebuild it after code changes, ask for "rebuild the Cloud Shell zip".
2. Open **console.cloud.google.com**, select your project, and click the **Activate Cloud Shell** icon (`>_`, top right).
3. In the Cloud Shell toolbar, click **⋮ → Upload** and choose `dex-sentinel-source.zip`.
4. Run:
   ```bash
   unzip -q dex-sentinel-source.zip && cd dex-sentinel
   ./deploy/gcp/deploy.sh "$(gcloud config get-value project)"
   ```
   Paste the Anthropic key when asked (hidden). The script prints the URL and access key at the end, about 5–10 minutes later.
5. To redeploy later: upload the new zip, then `rm -rf dex-sentinel && unzip -q -o dex-sentinel-source.zip && cd dex-sentinel && ./deploy/gcp/deploy.sh "$(gcloud config get-value project)"`.

If Cloud Shell is disabled by your organisation, use option B.

### Option B: Console only (point-and-click, needs a Git repository)

Cloud Run can build straight from **GitHub / GitLab / Bitbucket** with no CLI:

1. Push this project to a repository your organisation allows.
2. **Secret Manager** → *Create secret*:
   - `dex-api-key`: any long random string; this becomes the access key.
   - `anthropic-api-key`: your Anthropic key. Skip it if you'll run without an LLM.
3. **IAM → Service accounts** → create `dex-sentinel-run`, then grant it **Secret Manager Secret Accessor** on both secrets.
4. **Cloud Run → Create service → "Continuously deploy from a repository" → Set up with Cloud Build** → connect the
   repository and branch → **Build type: Dockerfile**, source location `/Dockerfile`.
5. Fill in the form:

   | Section | Setting |
   |---|---|
   | Region | `asia-south1 (Mumbai)` |
   | Authentication | **Allow unauthenticated invocations** |
   | Billing | **Instance-based** (CPU always allocated) |
   | Scaling | Minimum **0**, maximum **1** instances |
   | Container → port | **8080** |
   | Container → resources | **8 GiB** memory, **2** CPU |
   | Container → request timeout | **900** s; max concurrent requests **40** |
   | Container → execution environment | **Second generation** |
   | Networking | Tick **Use HTTP/2 end-to-end** |
   | Variables | `DEX_ENVIRONMENT=production`, `DEX_STORAGE_MODE=ephemeral`, `DEX_LLM_PROVIDER=auto` (or `template`), `DEX_MAX_UPLOAD_MB=200` |
   | Secrets | Expose `dex-api-key` as env var **`DEX_API_KEY`**, and `anthropic-api-key` as **`ANTHROPIC_API_KEY`** (version *latest*) |
   | Security | Service account **`dex-sentinel-run`** |

6. Click **Create**. Every push to the branch then rebuilds and redeploys automatically.

### Option C: ask your platform / IT team

Send them this folder, or just `deploy/gcp/deploy.sh` plus this README. The script is non-interactive except for the
Anthropic key prompt, and everything it creates is listed in section 2. It can also run from a CI pipeline (for
example GitHub Actions with Workload Identity Federation).

## 2. Deploy

From the project root:

```powershell
# Windows PowerShell
.\deploy\gcp\deploy.ps1 -ProjectId YOUR_PROJECT_ID
```

```bash
# Cloud Shell / macOS / Linux
./deploy/gcp/deploy.sh YOUR_PROJECT_ID
```

The first run takes about 5–10 minutes, and you are asked once for the Anthropic key (the input is hidden). The script:

1. Enables the Cloud Run, Cloud Build, Artifact Registry and Secret Manager APIs.
2. Creates a least-privilege runtime service account, `dex-sentinel-run@…`, which can only read its two secrets.
3. Stores **`dex-api-key`** (a random 32-character access key it generates) and **`anthropic-api-key`** in Secret Manager.
4. Builds the container with Cloud Build and deploys it to Cloud Run with these settings:

   | Setting | Why |
   |---|---|
   | `--use-http2` + Hypercorn | Removes Cloud Run's 32 MiB HTTP/1 upload cap, so Module 8's 200 MB uploads work |
   | `--max-instances 1` | Data, analysis jobs and caches live in one process; a second instance would disagree |
   | `--no-cpu-throttling` | Upload analysis runs in the background after the request returns and needs CPU |
   | `--cpu 2 --memory 8Gi` | Sized for the tested 163 MB upload (2.3 million telemetry rows) |
   | `--timeout 900` | Time to upload large files over slower connections |
   | `--allow-unauthenticated` | Public URL; the app's access key protects the data and API |

5. Runs a smoke test (health, key enforcement, dataset, Copilot provider) and prints the **URL** and the **access key**.

Re-running the script is safe. It keeps the existing keys and deploys a new revision, so use it to ship code changes.

| Option (PowerShell / bash env var) | Effect |
|---|---|
| `-NoLlm` / `NO_LLM=1` | The Copilot uses the offline grounded template engine and no Anthropic key is needed |
| `-UpdateAnthropicKey` / `UPDATE_ANTHROPIC_KEY=1` | Store a new Anthropic key version |
| `-RotateAccessKey` / `ROTATE_ACCESS_KEY=1` | Generate a new access key (users must re-enter it) |
| `-MinInstances 1` / `MIN_INSTANCES=1` | Keep one instance warm: no cold start, and uploads survive between visits |
| `-Region` / `REGION=` | Deploy somewhere other than asia-south1 |

## 3. Verify

1. Open the printed URL. The **Access key required** prompt appears. Enter the key and the Executive Dashboard loads
   (DEX Score **79.3**, correlation **r = 0.83** on the sample data).
2. **Diagnosis Assist:** pick `TCK-00002` → Application Crash, 99% confidence.
3. **DEX Copilot:** the top-bar chip reads `Copilot: anthropic`. Ask *"Which department has the worst experience?"*;
   the answer shows a tool trace and citations.
4. **Upload Dataset (M8):** the *Demo instance* notice is shown. Upload a CSV and click **Submit for Analysis**; the
   stages run and every screen updates. Try a file larger than 32 MB to confirm HTTP/2 is working. Finish with
   **Restore sample dataset**.
5. The downloads (CSV templates, sample workbook, outcomes export) work once the key is entered.

Command-line checks:

```bash
curl https://YOUR-URL/api/health                                        # {"status":"ok",...}
curl -i https://YOUR-URL/api/v1/meta                                    # 401 without the key
curl -H "X-API-Key: YOUR-KEY" https://YOUR-URL/api/v1/meta              # 200 with the key
```

## 4. Day-to-day operations

| Task | Command |
|---|---|
| View logs | `gcloud run services logs read dex-sentinel --region asia-south1 --limit 100` (or Console → Cloud Run → dex-sentinel → Logs) |
| Before a demo (no cold start, keep uploads) | `gcloud run services update dex-sentinel --region asia-south1 --min-instances 1` |
| After the demo (back to pay-per-use) | `gcloud run services update dex-sentinel --region asia-south1 --min-instances 0` |
| Show the access key again | `gcloud secrets versions access latest --secret dex-api-key` |
| Roll back to a previous revision | Console → Cloud Run → dex-sentinel → Revisions → *Manage traffic* |
| Set a spending alert | Console → Billing → Budgets & alerts → e.g. $50/month |
| Delete everything | `gcloud run services delete dex-sentinel --region asia-south1` · `gcloud secrets delete dex-api-key` · `gcloud secrets delete anthropic-api-key` · delete the `cloud-run-source-deploy` repository in Artifact Registry |

## 5. What it costs (approximate)

| Usage pattern | Rough cost |
|---|---|
| Idle (scaled to zero) | ≈ $0, plus cents per month for stored container images and secrets |
| While in use (2 vCPU / 8 GiB, instance billing) | roughly **$0.10–0.15 per hour** the instance is running; it stops about 15 min after the last request |
| Kept warm 24×7 (`--min-instances 1`) | roughly **$75–110 per month** |
| DEX Copilot | Billed by Anthropic per question (tokens) |
| Cloud Build | Plenty of free build minutes for occasional deploys |

Check the current prices with the Google Cloud Pricing Calculator for asia-south1.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Build fails with a *permission denied* on the Compute Engine service account | Ask a project admin to grant **Cloud Run Builder** (`roles/run.builder`) to `PROJECT_NUMBER-compute@developer.gserviceaccount.com`, then re-run |
| `PERMISSION_DENIED` enabling APIs or creating secrets | Your account lacks one of the roles in section 1 |
| The UI keeps asking for the key | The key was rotated or mistyped; print it with the command in section 4 |
| Copilot chip shows "grounded template" | No Anthropic key stored (or `-NoLlm` was used). Re-run with `-UpdateAnthropicKey`. |
| Uploads over 32 MB fail with 413 | The service was deployed without `--use-http2`; re-run the script. If HTTP/2 can't be used in your environment, set `DEX_MAX_UPLOAD_MB=30` and the UI enforces a 30 MB limit. |
| The first page load takes a few seconds | Cold start after scale-to-zero; use `--min-instances 1` during demos |
| Uploaded data disappeared | Expected on the demo tier after a restart or redeploy; re-upload, or see production below |

## 7. Operate with Claude Code through MCP servers (optional)

Two **official remote MCP servers** (HTTPS, nothing to install) let Claude Code manage the repository and the
deployment for you. The locally installed Google MCPs (`@google-cloud/cloud-run-mcp`, `@google-cloud/gcloud-mcp`)
need the gcloud CLI, so they are not used here.

| Server | Endpoint | Claude can |
|---|---|---|
| **GitHub** (by GitHub) | `https://api.githubcopilot.com/mcp/` | read/write code, commits, PRs, issues; run GitHub Actions and read their logs |
| **Cloud Run** (managed by Google, GA) | `https://run.googleapis.com/mcp` (Mumbai regional endpoint in preview: `https://run.asia-south1.rep.googleapis.com/mcp`) | deploy services, list and inspect services and revisions, check status |

**GitHub: one-time setup**
1. github.com → Settings → Developer settings → **Fine-grained tokens** → *Generate new token*. Use these settings:
   - Repository access: *Only select repositories* → `SentimentCorrelation`
   - Permissions: **Contents**, **Pull requests**, **Issues**, **Actions** and **Workflows** set to *Read and write*
   - Expiry: 30–90 days
2. Windows → *Edit environment variables for your account* → add a new variable **`GITHUB_PAT`** = the token.
   This needs no admin rights. Then restart VS Code.
3. The project's `.mcp.json` (git-ignored) already contains the `github` server, reading the token from `${GITHUB_PAT}`.
   Approve it when Claude Code asks, then check `/mcp`.

**Cloud Run: one-time setup (Cloud Console, no gcloud)**
1. APIs & Services → enable **Cloud Run Admin API**.
2. IAM → grant your account: *Cloud Run Developer*, *Service Account User*, *Artifact Registry Reader*,
   *Service Account Token Creator* and **MCP Tool User** (`roles/mcp.toolUser`).
3. APIs & Services → configure the **OAuth consent screen** (user type *Internal* if offered). Then go to
   Credentials → **Create OAuth client ID** → type **Web application** → authorised redirect URI
   `http://localhost:8765/callback`.
4. Send the **client ID** to Claude, who will add the `cloud-run` server. Enter the **client secret** yourself at the
   masked prompt. It is stored in Claude Code's credential store, never in the repo. The resulting entry looks like:
   ```json
   "cloud-run": { "type": "http", "url": "https://run.googleapis.com/mcp",
                  "oauth": { "clientId": "YOUR_CLIENT_ID", "callbackPort": 8765,
                             "scopes": "https://www.googleapis.com/auth/run" } }
   ```
5. In Claude Code, run `/mcp` → `cloud-run` → *Authenticate*, then sign in with Google. If Google reports
   `redirect_uri_mismatch`, add the exact redirect URI it shows to the OAuth client and try again.

**Least privilege.** The token is limited to one repository and expires; revoke it at any time on GitHub. For
look-but-don't-touch access to Cloud Run, use the scope `https://www.googleapis.com/auth/run.readonly`. Claude Code
asks before each MCP tool call, so keep deploy actions on *ask*. If your organisation blocks OAuth-client creation or
MCP use, the GCP admin must enable it.

## Upgrading to production

When the demo becomes a pilot:
- Move datasets to **Cloud Storage** and metadata (versions, jobs, audit, settings) to **Cloud SQL for PostgreSQL**. The app already accepts `DEX_DATABASE_URL`.
- Run upload analysis as a **Cloud Run Job** and allow several service instances.
- Replace the shared key with **Identity-Aware Proxy** (company SSO).
- Optionally use **Claude on Vertex AI** to keep LLM traffic inside Google Cloud.
- Add a **Cloud Build trigger** that runs the test suite and deploys on every merge.
