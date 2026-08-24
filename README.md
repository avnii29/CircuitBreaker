# CircuitBreaker

CircuitBreaker is a payment-failure recovery service. When a checkout fails because a simulated bank rail is unavailable, times out, or is blocked, the engine retries, reroutes, holds, or escalates the transaction so the original payment intent is preserved.

Bank rails and checkouts are simulated. The runtime is a durable service: FastAPI, PostgreSQL, Redis, authentication, idempotency, circuit breakers, adaptive routing, and audit logging.

Live dashboard: https://circuitbreaker-nine.vercel.app/

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
                  |     Render       |
                  +------+-----+-----+
                         |     |
                +--------+     +--------+
                v                       v
        +--------------+        +--------------+
        | PostgreSQL   |        |    Redis     |
        | Managed DB   |        | Managed Redis|
        +--------------+        +--------------+
```

Local development uses the same shape with Docker Compose: React (or Vite) to FastAPI to PostgreSQL and Redis.

## Local development

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- Dashboard: http://localhost:8080
- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs

Compose runs `alembic upgrade head` before the API starts. Postgres is the datastore. SQLite is only for local unit tests and single-process uvicorn.

### API without Compose

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Required environment is documented in `backend/.env.example`. There is no default database URL or API key in code.

### Dashboard without Compose

```bash
cp frontend/.env.example frontend/.env
# set VITE_API_BASE_URL and VITE_API_KEY to match the API
cd frontend && npm install && npm run dev
```

Mutating and read APIs require `X-API-Key`.

## Production deployment

Chosen target:

- Frontend: Vercel (`frontend/`)
- Backend: Render Docker web service (`render.yaml`)
- Database: Render managed PostgreSQL
- Cache: Render Key Value (Redis-compatible)

Do not deploy SQLite. Do not use `CORS_ORIGINS=*`. Do not connect real payment rails.

### Backend (Render)

1. Push this repository to GitHub.
2. Create a Render Blueprint from `render.yaml`, or create a Docker web service with context `backend/`.
3. Set the sync-false environment variables in the Render dashboard using placeholders from `deploy/production.env.example`.
4. Set `CORS_ORIGINS` to the Vercel origin, for example `https://<project>.vercel.app`.
5. Set `DATABASE_SSL=true`. Leave `AUTO_CREATE_SCHEMA=false` so schema changes go through Alembic.
6. Deploy. The container entrypoint runs `alembic upgrade head`, then starts uvicorn on `0.0.0.0:$PORT`.
7. Confirm `GET /health/ready` returns 200 before sending dashboard traffic.

Render health check path: `/health/ready`.

### Frontend (Vercel)

1. Import the GitHub repository in Vercel.
2. Set Root Directory to `frontend`.
3. Set:

```text
VITE_API_BASE_URL=https://<render-api-host>
VITE_API_KEY=<same write key as the API>
```

4. Deploy. The dashboard talks to the live API over HTTPS and uses real telemetry, not mock transactions.

The demo write key is visible in the browser bundle by design so the public dashboard can simulate checkouts. Rotate it after the hackathon.

### Demo failure injection

Use the dashboard simulation panel, or `POST /api/v1/payments/simulate-checkout` with `scenario`:

```text
TRANSIENT_FAILURE
BANK_OUTAGE
HARD_DECLINE
RISK_BLOCK
```

These map onto the existing simulated rails. There is no real bank or UPI switch.

## Environment variables

See:

- `.env.example` for Docker Compose
- `backend/.env.example` for local uvicorn
- `frontend/.env.example` for Vite
- `deploy/production.env.example` for Render / Vercel

Never commit `.env` or real secrets.

## API documentation

FastAPI OpenAPI UI:

- Local: http://localhost:8000/docs
- Production: `https://<api-host>/docs`

Health:

```text
GET /api/v1/health
GET /api/v1/health/live
GET /api/v1/health/ready
GET /health/live
GET /health/ready
```

Liveness is process-alive. Readiness checks PostgreSQL, and Redis when `REDIS_URL` is set.

## Checks

```bash
cd backend && pytest -q && ruff check app tests
cd frontend && npm run build
```

CI runs lint, unit/integration tests, the frontend production build, and the backend Docker image build. A failed CI run must not be deployed.

## Live demo

- Dashboard: set after the Vercel project is connected
- API: set after the Render service is live
- OpenAPI: `https://<api-host>/docs`

## Notes

- Cart hold SLA defaults to 180s (`MAX_CART_HOLD_SECONDS` / `RECOVERY_WINDOW_SECONDS`). Demo mode compresses that window.
- Rails trip OPEN above a 30% failure rate in a 60s window, or earlier on a z-score spike (`GET /api/v1/payments/telemetry-dashboard` -> `circuit_breakers`).
- Escalations are listed at `GET /api/v1/payments/manual-review-queue`.
- Adaptive policy: `GET /api/v2/policy`, rollback `POST /api/v2/policy/rollback/{version}`.
- Job priority: realtime recovery > batch > retrain. Set `WORKER_ENABLED=true` and `REDIS_URL` in production.
- `/metrics` is Prometheus.
- Breaking response changes go under `/api/v2/...`; v1 remains mounted.
