# Deployment Information

## Public URL

https://k5-l3a-day14-nguyenthithuydung-2a202603552-deplo-production.up.railway.app

## Platform

Railway. The deployed agent comes from source commit `02efc17` in `06-lab-complete/`. The Railway service uses that directory as its root and `/06-lab-complete/railway.toml` as its configuration path. Railway builds the Dockerfile and checks `/health`. The agent connects to a separate Railway Redis service.

## Acceptance tests

All four checks passed in the same run at `2026-11-25T23:53:26+07:00`.

| Request | HTTP | Observed result |
|---|---:|---|
| GET `/health` | 200 | `{"status":"ok"}` |
| GET `/ready` | 200 | `{"status":"ready"}` |
| POST `/ask` without a key | 401 | Invalid or missing API key |
| POST `/ask` with the valid key | 200 | Mock LLM answer for Hello |

## Test commands

Run in Bash. The final command reads the key silently and sends the header through standard input.

```bash
BASE=https://k5-l3a-day14-nguyenthithuydung-2a202603552-deplo-production.up.railway.app
curl -sS --max-time 30 -w '\nHTTP %{http_code}\n' "$BASE/health"
curl -sS --max-time 30 -w '\nHTTP %{http_code}\n' "$BASE/ready"
curl -sS --max-time 30 -w '\nHTTP %{http_code}\n' "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
(
  set +x
  read -rs -p 'Railway agent API key: ' AGENT_API_KEY
  printf '\n'
  printf 'X-API-Key: %s\n' "$AGENT_API_KEY" |
    curl -sS --max-time 30 -w '\nHTTP %{http_code}\n' "$BASE/ask" \
      -H @- -H 'Content-Type: application/json' -d '{"question":"Hello"}'
)
```

## Environment variables

| Variable | Source or role |
|---|---|
| `PORT` | Runtime port. The Dockerfile uses the platform value when provided and defaults to 8000. |
| `REDIS_URL` | Private connection setting for the Railway Redis service. |
| `AGENT_API_KEY` | Private Railway service variable used to authenticate `/ask`. |
| `ENVIRONMENT` | Deployment environment setting supported by the app. |
| `LOG_LEVEL` | The deployed code uses a fixed INFO level. There is no `LOG_LEVEL` setting in this implementation. |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png) shows the agent and Redis online.
- [Service running](screenshots/running.png) shows the active deployment and public domain.
- [Test results](screenshots/test.png) shows the timestamp, four HTTP results, and the mock response.
