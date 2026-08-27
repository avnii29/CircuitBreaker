# CircuitBreaker

CircuitBreaker is an AI revenue recovery engine.

It finds revenue slipping away, explains why, chooses the highest-value safe intervention, executes it, and measures net revenue protected. Payment failure recovery is the first capability. The same decision pipeline also handles checkout abandonment, subscription failure, and overdue receivables in simulation.

Bank rails, messages, and recoveries are simulated. No real money moves.

Live dashboard: https://circuitbreaker-nine.vercel.app
Live API: https://circuitbreaker-api.vercel.app

## Architecture

```text
                         INTERNET
                            |
                            v
                  +------------------+
                  | React Dashboard  |
                  |     Vercel       |
                  +--------+---------+
                           | HTTPS
                           v
                  +------------------+
                  |   FastAPI API    |
                  |     Vercel       |
                  +------------------+
```

The public demo runs entirely on Vercel. It does not need this laptop, localhost, Docker, or a tunnel.

Local development can still use Docker Compose or Vite plus uvicorn.

## Product loop

```text
Revenue event
  -> revenue at risk
  -> root cause
  -> candidate interventions
  -> economic evaluation
  -> guardrails
  -> ACT / DO NOTHING / ESCALATE
  -> recover
  -> measure
  -> learn
```

The engine optimizes net revenue protected (recovered amount minus simulated intervention cost), not just payment success.

## Local development

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- Dashboard: http://localhost:8080
- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs

### API without Compose

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Dashboard without Compose

```bash
cp frontend/.env.example frontend/.env
# set VITE_API_BASE_URL and VITE_API_KEY to match the local API
cd frontend && npm install && npm run dev
```

Mutating and read APIs require `X-API-Key`.

## Production (current)

Public hosting:

- Frontend Vercel project: `circuitbreaker` -> https://circuitbreaker-nine.vercel.app
- API Vercel project: `circuitbreaker-api` -> https://circuitbreaker-api.vercel.app

Frontend production environment:

```text
VITE_API_BASE_URL=https://circuitbreaker-api.vercel.app
VITE_API_KEY=<same write key as the API>
```

API production environment (see `deploy/production.env.example`):

```text
DATABASE_URL=sqlite+aiosqlite:////tmp/circuitbreaker.db
AUTO_CREATE_SCHEMA=true
API_KEY_READ=...
API_KEY_WRITE=...
CORS_ORIGINS=https://circuitbreaker-nine.vercel.app
CORS_ORIGIN_REGEX=https://.*\.vercel\.app
DEMO_MODE=true
WORKER_ENABLED=false
LLM_PROVIDER=simulated
```

Do not set `VITE_API_BASE_URL` to localhost, 127.0.0.1, or 0.0.0.0 in a production build.

The dashboard `/api/*` paths also rewrite to the hosted API so same-origin calls work.

The demo write key is visible in the browser bundle so the public dashboard can run simulations. Rotate it after the hackathon.

Optional longer-running Postgres/Redis hosting is described in `render.yaml` and `docker-compose.yml`. The live demo does not depend on them.

## Demo

Open the dashboard and click Start live demo.

That resets the store, creates a deterministic mix of revenue events, runs recovery, and shows:

- revenue at risk
- recovered revenue
- net revenue protected
- ACT / DO NOTHING / ESCALATE
- simulated baseline vs simulated intervention

Single scenarios (payment outage, checkout abandonment, subscription failure, overdue receivable, low-value skip) are on the Recovery page.

## Environment variables

- `.env.example` for Docker Compose
- `backend/.env.example` for local uvicorn
- `frontend/.env.example` for local Vite
- `deploy/production.env.example` for Vercel

Never commit `.env` or real secrets.

## API

OpenAPI:

- Local: http://localhost:8000/docs
- Production: https://circuitbreaker-api.vercel.app/docs

Health:

```text
GET /api/v1/health
GET /api/v1/health/live
GET /api/v1/health/ready
GET /health/live
GET /health/ready
```

v1 contracts stay compatible. Breaking changes go under `/api/v2/`.

## Checks

```bash
cd backend && pytest -q && ruff check app tests
cd frontend && npm run build
```

CI runs lint, tests, the frontend production build, and the backend Docker image build.
