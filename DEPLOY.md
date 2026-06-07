# agreed — Google Cloud Run + Supabase deployment

Deploys two Cloud Run services (backend API + Next.js frontend) backed by Supabase Postgres.

## Architecture

```
Browser → Cloud Run (frontend) → Cloud Run (backend) → Supabase Postgres
```

## Prerequisites

1. [Google Cloud](https://cloud.google.com/) project with billing enabled
2. [Supabase](https://supabase.com/) project
3. `gcloud` CLI authenticated: `gcloud auth login`
4. Docker (for local builds) or Cloud Build (remote builds)

## 1. Supabase database

1. Create a Supabase project.
2. Open **SQL Editor** and run migrations in order:
   - `supabase/migrations/001_initial_schema.sql`
   - `supabase/migrations/002_chat_conversations.sql`
3. Copy the **connection string** from **Project Settings → Database**:
   - Use the **Transaction pooler** URI (port `6543`) for Cloud Run.
   - Example: `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require`

The backend sets `agreed.user_id` on each connection so row-level security isolates user data.

## 2. Configure environment

Copy and fill in deployment variables:

```bash
cp deploy/.env.deploy.example deploy/.env.deploy
# edit deploy/.env.deploy
```

Required:

| Variable | Description |
|----------|-------------|
| `GCP_PROJECT` | Google Cloud project ID |
| `GCP_REGION` | e.g. `us-west1` |
| `DATABASE_URL` | Supabase Postgres connection string |
| `OPENAI_API_KEY` | Optional; enables LLM negotiators |
| `WANDB_API_KEY` | Optional; enables Weave tracing |

## 3. Deploy to Google Cloud

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

The script will:

1. Enable Cloud Run, Cloud Build, and Artifact Registry APIs
2. Create an Artifact Registry repository (`agreed`)
3. Build and push backend + frontend container images
4. Deploy `agreed-api` and `agreed-web` to Cloud Run
5. Wire frontend → backend URL and CORS on the API

After deploy, URLs are printed for the frontend and API.

## 4. Local container testing

Run with Supabase (set `DATABASE_URL` in `.env`):

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8080

Without `DATABASE_URL`, the backend falls back to SQLite inside the container.

## 5. Manual Cloud Build

```bash
gcloud builds submit --config deploy/cloudbuild.yaml \
  --substitutions=_REGION=us-west1,_DATABASE_URL="$DATABASE_URL"
```

## 6. Updating secrets

Re-run `./deploy/deploy.sh` after changing `deploy/.env.deploy`, or update Cloud Run env vars:

```bash
gcloud run services update agreed-api \
  --region=us-west1 \
  --update-env-vars DATABASE_URL=...,OPENAI_API_KEY=...
```

## Files

| Path | Purpose |
|------|---------|
| `backend/Dockerfile` | FastAPI API container |
| `frontend/Dockerfile` | Next.js standalone container |
| `docker-compose.yml` | Local prod-like stack |
| `deploy/cloudbuild.yaml` | GCP Cloud Build pipeline |
| `deploy/deploy.sh` | One-command deploy script |
| `supabase/migrations/` | Postgres schema + RLS |
