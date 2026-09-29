#!/usr/bin/env bash
# Deploy DEX Sentinel to Google Cloud Run (demo tier) from Cloud Shell, macOS or Linux. Safe to re-run.
#   ./deploy/gcp/deploy.sh PROJECT_ID                 # Copilot with Claude (prompts for the Anthropic key once)
#   NO_LLM=1 ./deploy/gcp/deploy.sh PROJECT_ID        # Copilot uses the offline template engine
#   MIN_INSTANCES=1 ./deploy/gcp/deploy.sh PROJECT_ID # demo day: no cold starts
#   UPDATE_ANTHROPIC_KEY=1 / ROTATE_ACCESS_KEY=1      # store a new key version
set -euo pipefail
PROJECT_ID="${1:?usage: deploy.sh PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-dex-sentinel}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
SA_NAME="${SERVICE}-run"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
ACCESS_SECRET="dex-api-key"
LLM_SECRET="anthropic-api-key"
cd "$(dirname "$0")/../.."

step() { printf '\n==> %s\n' "$*"; }
set_secret() {  # name value  (printf %s: no trailing newline)
  if gcloud secrets describe "$1" --project "$PROJECT_ID" >/dev/null 2>&1; then
    printf %s "$2" | gcloud secrets versions add "$1" --data-file=- --project "$PROJECT_ID" --quiet >/dev/null
  else
    printf %s "$2" | gcloud secrets create "$1" --data-file=- --replication-policy=automatic --project "$PROJECT_ID" --quiet >/dev/null
  fi
}
grant() { gcloud secrets add-iam-policy-binding "$1" --member "serviceAccount:${SA_EMAIL}" \
  --role roles/secretmanager.secretAccessor --project "$PROJECT_ID" --quiet >/dev/null; }

command -v gcloud >/dev/null || { echo "Install the Google Cloud CLI first: https://cloud.google.com/sdk/docs/install"; exit 1; }
[ -n "$(gcloud config get-value account 2>/dev/null)" ] || { echo "Run: gcloud auth login"; exit 1; }
gcloud config set project "$PROJECT_ID" --quiet

step "Enabling required APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

step "Service account ${SA_EMAIL}"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name "DEX Sentinel Cloud Run runtime"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role roles/run.builder --condition None --quiet >/dev/null 2>&1 || \
  echo "WARNING: could not grant roles/run.builder to the build service account (needs Project IAM Admin)."

step "Secrets"
if [ -n "${ROTATE_ACCESS_KEY:-}" ] || ! gcloud secrets describe "$ACCESS_SECRET" >/dev/null 2>&1; then
  set_secret "$ACCESS_SECRET" "$(LC_ALL=C tr -dc 'A-HJ-NP-Za-km-z2-9' </dev/urandom | head -c 32)"
  echo "Generated a new access key."
fi
grant "$ACCESS_SECRET"
SECRETS="DEX_API_KEY=${ACCESS_SECRET}:latest"
PROVIDER="template"
if [ -z "${NO_LLM:-}" ]; then
  if [ -n "${UPDATE_ANTHROPIC_KEY:-}" ] || ! gcloud secrets describe "$LLM_SECRET" >/dev/null 2>&1; then
    read -r -s -p "Paste your Anthropic API key (hidden): " AKEY; echo
    [ -n "$AKEY" ] || { echo "No key entered (use NO_LLM=1 to deploy without one)"; exit 1; }
    set_secret "$LLM_SECRET" "$AKEY"; unset AKEY
  fi
  grant "$LLM_SECRET"
  SECRETS="${SECRETS},ANTHROPIC_API_KEY=${LLM_SECRET}:latest"
  PROVIDER="auto"
fi

step "Building with Cloud Build and deploying to Cloud Run (5-10 min first time)"
gcloud run deploy "$SERVICE" --source . --region "$REGION" --quiet \
  --allow-unauthenticated --use-http2 --no-cpu-throttling --execution-environment gen2 \
  --cpu 2 --memory 8Gi --min-instances "$MIN_INSTANCES" --max-instances 1 --concurrency 40 --timeout 900 \
  --service-account "$SA_EMAIL" \
  --set-env-vars "DEX_ENVIRONMENT=production,DEX_STORAGE_MODE=ephemeral,DEX_LLM_PROVIDER=${PROVIDER},DEX_MAX_UPLOAD_MB=200" \
  --set-secrets "$SECRETS"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
KEY="$(gcloud secrets versions access latest --secret "$ACCESS_SECRET")"
step "Smoke test"
echo "  health         : $(curl -fsS "$URL/api/health")"
echo "  meta (no key)  : HTTP $(curl -s -o /dev/null -w '%{http_code}' "$URL/api/v1/meta") (expect 401)"
echo "  meta (key)     : HTTP $(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: $KEY" "$URL/api/v1/meta") (expect 200)"
printf '\nDEX Sentinel is live\n  URL        : %s\n  Access key : %s\n' "$URL" "$KEY"
