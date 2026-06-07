#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/deploy/.env.deploy"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy deploy/.env.deploy.example and fill it in."
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

: "${GCP_PROJECT:?Set GCP_PROJECT in deploy/.env.deploy}"
: "${GCP_REGION:?Set GCP_REGION in deploy/.env.deploy}"
: "${DATABASE_URL:?Set DATABASE_URL (Supabase pooler URL) in deploy/.env.deploy}"

echo "==> Configuring gcloud project: $GCP_PROJECT"
gcloud config set project "$GCP_PROJECT"

echo "==> Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --quiet

echo "==> Creating Artifact Registry repo (if needed)"
if ! gcloud artifacts repositories describe agreed \
  --location="$GCP_REGION" &>/dev/null; then
  gcloud artifacts repositories create agreed \
    --repository-format=docker \
    --location="$GCP_REGION" \
    --description="agreed container images"
fi

gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev" --quiet

BACKEND_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/agreed/backend:latest"
FRONTEND_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/agreed/frontend:latest"

echo "==> Building backend image"
docker build -t "$BACKEND_IMAGE" "${ROOT}/backend"
docker push "$BACKEND_IMAGE"

echo "==> Deploying backend (agreed-api)"
gcloud run deploy agreed-api \
  --image="$BACKEND_IMAGE" \
  --region="$GCP_REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="DATABASE_URL=${DATABASE_URL},OPENAI_API_KEY=${OPENAI_API_KEY:-},WANDB_API_KEY=${WANDB_API_KEY:-},WANDB_ENTITY=${WANDB_ENTITY:-},WANDB_PROJECT=${WANDB_PROJECT:-agreed},WEAVE_PROJECT=${WEAVE_PROJECT:-agreed},AGREED_LLM_BACKEND=${AGREED_LLM_BACKEND:-},NEGOTIATOR_MODEL=${NEGOTIATOR_MODEL:-gpt-4o-mini},E2B_API_KEY=${E2B_API_KEY:-},EXA_API_KEY=${EXA_API_KEY:-}"

BACKEND_URL="$(gcloud run services describe agreed-api \
  --region="$GCP_REGION" \
  --format='value(status.url)')"

echo "==> Building frontend image (API: $BACKEND_URL)"
docker build \
  --build-arg "NEXT_PUBLIC_API_BASE=${BACKEND_URL}" \
  -t "$FRONTEND_IMAGE" \
  "${ROOT}/frontend"
docker push "$FRONTEND_IMAGE"

echo "==> Deploying frontend (agreed-web)"
gcloud run deploy agreed-web \
  --image="$FRONTEND_IMAGE" \
  --region="$GCP_REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="OPENAI_API_KEY=${OPENAI_API_KEY:-}"

FRONTEND_URL="$(gcloud run services describe agreed-web \
  --region="$GCP_REGION" \
  --format='value(status.url)')"

echo "==> Updating backend CORS for frontend"
gcloud run services update agreed-api \
  --region="$GCP_REGION" \
  --update-env-vars="CORS_ORIGINS=${FRONTEND_URL}"

echo ""
echo "Deploy complete."
echo "  Frontend: $FRONTEND_URL"
echo "  Backend:  $BACKEND_URL"
