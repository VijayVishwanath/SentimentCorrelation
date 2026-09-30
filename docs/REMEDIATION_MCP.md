# Software Remediation MCP Server

DEX Sentinel can act on security-team emails that ask for a specific software version to be removed ("uninstall .NET 6.0.36 from these devices"). An MCP server exposes the workflow as tools, so Claude (Claude Code, Claude Desktop or any MCP client) can read the request, check it and run it. A named human must approve before anything is removed.

> **Simulated fleet only.** Detection and removal run against a deterministic software inventory generated for each device in the DEX Sentinel dataset. The tools return the exact commands a real endpoint agent would run (`msiexec /x`, `reg delete`, `Remove-Item`, `Checkpoint-Computer`), but they never execute on the machine hosting the server.

## Run it

```powershell
# from backend/
..\.venv\Scripts\python.exe -m app.remediation.mcp_server
```

In Claude Code, add it to the project's `.mcp.json`. The file is gitignored, so each developer keeps their own paths:

```json
{
  "mcpServers": {
    "dex-remediation": {
      "type": "stdio",
      "command": "C:\\PROJECTS\\Hackathon\\DEXSentimentCorrelation\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.remediation.mcp_server"],
      "env": { "PYTHONPATH": "C:\\PROJECTS\\Hackathon\\DEXSentimentCorrelation\\backend" }
    }
  }
}
```

The server uses the same database as the web app (`DEX_DATABASE_URL`). On first use it seeds four demo emails into the inbox.

## Web UI

Open **Software Remediation** in the sidebar (`/remediation`, badge **MCP**). The page drives the same engine as the MCP server through `/api/v1/remediation/*`:

1. **Inbox.** Click an email. Rejected senders show a red badge.
2. **Parsed request.** Shows the software, version, targets, urgency and reason. Errors make the request non-actionable.
3. **Targets & safety checks.** Shows the exact-version matches, the versions left untouched and the per-device verdicts (safe, warning or blocked). Tick *Acknowledge dependencies* to override a dependency block.
4. **Plan, approve & execute.** *Create dry-run plan*, enter the approver's name, then *Approve & execute*. Click a device row to see its commands and the result of each step.
5. **Outcome.** Shows boot time before and projected after, the security-team summary, escalations and the message sent to each employee.
6. **Recent runs** and **Audit trail**, with the chain-integrity status.

## Fix now: runbook actions

Every recommended fix in the app has a **Fix now** button: the Command Center action cards and at-risk table, the Proactive Watchlist rows and the Diagnosis Assist result. It opens a drawer that shows the runbook, its target devices and a dry-run plan, then runs it. The runbooks use the same safeguards as software removal: a scoped token, atomic per-device steps with a snapshot and rollback, verification, and the audit log.

| Runbook | Category | Risk | Targets (telemetry breach) |
|---|---|---|---|
| RB-NET-01 Push QoS profile, reset Wi-Fi | Network | low: auto-approved | latency, packet loss |
| RB-AUTH-01 Push compliance policy, re-sync enrollment | Login/Auth | low: auto-approved | policy non-compliance |
| RB-APP-01 Reinstall and patch the app suite | Application Crash | high: named approver | app hangs |
| RB-PERF-01 Reimage device | Performance | high: named approver | boot duration |
| RB-HW-01 Replace battery and disk | Hardware | high: named approver | hardware, battery or disk health |

Devices that are already fixed are not targeted again. Each plan projects the tickets avoided and the savings, based on the observed before/after effect of past fixes of the same category. API: `/api/v1/remediation/runbooks[/targets|/runs]`. MCP tools: `runbook_catalog`, `runbook_targets`, `run_runbook`.

## Workflow and tools

| Step | Tool | What it does |
|---|---|---|
| 1 | `email_monitor` | `list` the inbox, `poll` IMAP (if configured) or `mark_processed` a request. Senders outside the allowlist are stored as `rejected`. |
| 1 | `submit_email` | Adds an email by hand (testing, forwarding). |
| 2 | `email_parser` | Extracts software, exact version, devices (or `Affected Devices: all`), reason, replacement and urgency. Reads `Software:` / `Version:` lines, falls back to the subject line, and reads CSV/JSON attachments. Returns validation errors. |
| 3 | `software_inventory` | Scans the registry (HKLM, WOW6432Node, HKCU), Program Files, Program Files (x86), AppData, WMI/MSI and running processes. |
| 4 | `version_matcher` | Finds installations of **exactly** the requested version (`6.0.36` never matches `6.0.37`) and lists the other versions it will leave alone. |
| 5 | `safety_validator` | Per device: system-critical packages and dependent applications **block** removal; running processes are warnings (they are stopped first). Pass `acknowledge_dependencies` to override a dependency block. |
| 6 | `credential_manager` | Issues a short-lived, scoped, **single-use** token for the removal service account. No password is ever returned. |
| 7 | `removal_orchestrator` | Dry run by default: returns the per-device plan. With `dry_run=false`, `approved_by`, `token_id` and the `plan_hash` returned by the reviewed dry run, it executes. On each device it creates a restore point, stops processes, runs the MSI/EXE uninstall, deletes files, cleans the registry and verifies. |
| 8 | `verify_removal` | Re-scans the devices and confirms the version is gone. |
| 9 | `outcome_reporter` | Reports before telemetry against projected after-telemetry, recent tickets, a notification for each user, a security-team summary and escalations. It also closes the originating email. |
| — | `audit_trail` | Reads the hash-chained audit log and checks its integrity. |

### Safety rules built into the server

- **Sender allowlist, matched exactly.** `security-team@company.com.attacker.io` is rejected. The demo inbox includes this spoofed email.
- **Version-specific.** A request without a version is not actionable.
- **Human approval.** Execution fails without `approved_by` naming a human (agent and service identities such as "agent", "Claude" or the service account are refused) and a valid, unexpired token.
- **Plan-bound, single-use execution.** Every dry run returns a `plan_hash`: a fingerprint of the software, version and exact installations (or, for runbooks, devices) it would change. Execution must present that hash, so a scope that changed after review is refused, and each token authorises exactly one execution. The *Fix now* drawer and the Remediation page pass it automatically.
- **Atomic per device.** If any step fails on a device (the simulated inventory includes a few uninstallers that exit with code 1603), the whole device is rolled back to its restore point, left unchanged and flagged for escalation. Other devices in the run continue.
- **Tamper-evident audit.** Every token issue, plan, execution, rollback and outcome is appended to `remediation_audit`. Each row carries `sha256(previous hash + row)`, so editing or deleting a row breaks `audit_trail().integrity`.

## Demo inbox

| Message | Request | What it shows |
|---|---|---|
| `<demo-001@company.com>` | .NET Runtime 6.0.36, 4 listed devices, critical | x64 and x86 copies are both removed; one device is blocked because Contoso Expense Client 3.0 depends on .NET 6 |
| `<demo-002@company.com>` | TeamViewer 15.51.5, `Affected Devices: all` | Fleet-wide scope; 15.58.4 is left alone; a locked uninstaller triggers a rollback |
| `<demo-003@company.com>` | WinRAR 5.61.0, devices in a CSV attachment | Attachment parsing |
| `<demo-004@company.com>` | Chrome from a look-alike sender | Rejected, never actionable |

A typical session prompt: *"Process the pending removal emails. Show me the plan before executing anything."* Claude lists the inbox, parses a request, runs the matcher and the safety checks, and shows the dry-run plan. It executes only after you name the approver.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DEX_REMEDIATION_ALLOWED_SENDERS` | security-team@, it-compliance@, vulnerability-scanner@company.com | JSON list of authorized sender addresses |
| `DEX_REMEDIATION_SERVICE_ACCOUNT` | `svc_software_removal` | Account that tokens are issued for |
| `DEX_REMEDIATION_TOKEN_TTL_SEC` | `1800` | Token lifetime |
| `DEX_REMEDIATION_SEED_INBOX` | `true` | Seed the demo emails when the inbox is empty |
| `DEX_IMAP_HOST`, `DEX_IMAP_PORT`, `DEX_IMAP_USERNAME`, `DEX_IMAP_PASSWORD`, `DEX_IMAP_FOLDER` | unset, 993, INBOX | Optional real mailbox. Polling is read-only (`BODY.PEEK`, never flags or deletes) and imports only tagged subjects. |

Recognized subject tags: `[UNAUTHORIZED-SOFTWARE]`, `[EOL-SOFTWARE]`, `[SECURITY-PATCH]`.

## Code map

| File | Role |
|---|---|
| `backend/app/remediation/mcp_server.py` | MCP tool surface (stdio) and agent instructions |
| `backend/app/remediation/engine.py` | Matching, safety checks, tokens, atomic removal and rollback, verification, outcome report |
| `backend/app/remediation/inventory.py` | Simulated inventory for each device, and name and version matching |
| `backend/app/remediation/parser.py` | Email parsing and the sender allowlist |
| `backend/app/remediation/mailbox.py` | Inbox (SQLite), IMAP connector, demo seed |
| `backend/app/remediation/audit.py` | Hash-chained audit log |
| `backend/tests/test_remediation.py` | Parser, matching, safety, dry run, approval, rollback, audit tampering and MCP surface |

## Toward a real deployment

The plan in `MCP_Email_Integration.md.txt` also covers the pieces that need real infrastructure. The interfaces above are where they plug in:

- **Endpoint execution.** Replace the simulated step results in `engine.remove` with an endpoint-management channel (Intune, ConfigMgr, or an agent on each device). Keep the per-device atomicity and restore-point rollback.
- **Vault-backed credentials.** Back `issue_token` with Azure Key Vault or HashiCorp Vault, plus Active Directory group checks.
- **Mail connectors.** A Microsoft 365 (Graph) or Gmail connector alongside the IMAP one.
- **Outcome measurement.** Write executed runs into DEX Sentinel's remediation register once post-removal telemetry arrives, so the Outcome Report measures the real effect instead of the projection.
