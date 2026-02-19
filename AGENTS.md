# Repository Guidelines

## Project Structure & Module Organization
- `gateway_service/app/main.py` is the FastAPI gateway service entrypoint.
- `gateway_service/requirements.txt` defines Python runtime dependencies.
- `gateway_service/Dockerfile` builds the gateway container.
- `docker-compose.yml` orchestrates `gateway`, `openclaw`, and `ollama`.
- `.env.example` lists required runtime secrets and model configuration.

## Build, Test, and Development Commands
- `docker compose up --build` builds and runs all services defined in `docker-compose.yml`.
- `docker compose up gateway` runs only the gateway service and its dependencies.
- `pip install -r gateway_service/requirements.txt` installs Python deps for local runs.
- `uvicorn app.main:app --reload --host 0.0.0.0 --port 9000` starts the gateway locally from `gateway_service/`.

## Coding Style & Naming Conventions
- Python code uses 4-space indentation and standard PEP 8 naming.
- Prefer descriptive function names like `_dispatch_to_openclaw` and constants in `UPPER_SNAKE_CASE`.
- No formatter or linter config is present; keep changes small and consistent with existing style.

## Testing Guidelines
- No automated tests are currently included.
- If you add tests, prefer `tests/` with `test_*.py` naming and document how to run them.

## Commit & Pull Request Guidelines
- Recent commit messages are short and descriptive (e.g., “Update .env.example”).
- Keep commits focused and use brief, sentence-style summaries.
- Pull requests should include:
  - A clear summary of behavior changes.
  - Linked issues or context.
  - Configuration updates (e.g., `.env.example`) when new env vars are introduced.

## Security & Configuration Tips
- Never commit secrets; use `.env` and keep `.env.example` in sync.
- Gateway only allows local OpenClaw targets; `OPENCLAW_URL` must resolve to a local host.
- Ensure `TELEGRAM_WEBHOOK_SECRET` and `OPENCLAW_GATEWAY_TOKEN` are set for production.
