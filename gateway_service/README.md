# Gateway Service

## Health endpoint

The gateway exposes `GET /health` on port 9000. It returns JSON with:

- `status`, `uptime_s`, and `provider`
- `openclaw_reachable` based on a fast request to `OPENCLAW_URL` + `OPENCLAW_ROUTE`
- `db_writable` based on opening the SQLite DB and writing a temporary file in the DB directory
