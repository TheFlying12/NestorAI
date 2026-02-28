# AGENTS.md — NestorAI Codex Operating Manual

This repository uses Codex CLI. Agents must follow these rules to ship production-quality changes.
If instructions conflict: (1) PLAN.md (2) this file (3) local directory AGENTS.md (4) task prompt.

---

## 0) Prime Directive

Your job is not just to “make code changes.”
Your job is to **make correct product decisions**, implement them, and leave behind a **clear audit trail**
so a human can trust, review, and extend the system.

If you are uncertain about a requirement, do not invent. Surface assumptions explicitly.

---

## 1) Read Before Writing Code

Before making changes, always read:
- PLAN.md (current phase + acceptance criteria)
- README / docs relevant to the touched area
- Existing patterns in the repo (how config/logging/errors are done)

If the repository is missing run/test commands, propose a minimal “Quickstart” section update.

---

## 2) Required Output Format (Every Task)

You must produce:
1) **Plan** (before edits)
2) **Implementation Notes** (during/after edits)
3) **Verification Evidence** (what you ran / what passed)
4) **Decision Report** (required; see section 8)

If the user asks for only code, still keep Decision Report concise, but include it.

---

## 3) Work Style & Hygiene (Do Not Skip)

### Minimize diff surface
- Smallest change that satisfies requirements.
- Prefer extending existing modules over introducing new frameworks.
- Avoid “drive-by refactors.” If needed, separate into a distinct commit.

### Preserve repository conventions
- Naming, folder layout, error handling, logging style.
- Do not add a second competing pattern (e.g., two config systems).

### Determinism
- Avoid nondeterministic tests and time-based flakiness.
- Seed randomness where appropriate.

### Security basics (always-on)
- No secrets committed.
- No logging of tokens, pairing codes, or sensitive user payloads.
- Validate external input; set timeouts on all network calls.
- Device-side design must remain outbound-only unless PLAN.md changes.

---

## 4) Git / Patch Discipline (Codex CLI)

- Keep commits logically grouped (one feature/fix per commit if possible).
- Write commit messages that explain intent:
  - `feat(gateway): add telegram webhook healthcheck`
  - `fix(device-agent): reconnect backoff + jitter`
- Do not reformat unrelated files.
- If a large rename/move is required, justify it in the Decision Report.

If you are working in a worktree or parallel agent setup:
- Avoid editing the same files as other agents.
- Prefer additive changes and stable interfaces.

---

## 5) Code Standards (Concrete, Not Vibes)

### Error handling
- Never swallow exceptions silently.
- Convert errors into clear, actionable messages.
- Include context in logs (component, request id if available), but never secrets.

### Timeouts and retries
- Every external call needs a timeout.
- Retries require:
  - bounded attempts
  - exponential backoff (with jitter where relevant)
  - idempotency consideration (don’t retry non-idempotent ops blindly)

### Logging
- Use structured logging where possible (json logs preferred).
- Log important state transitions:
  - device connect/disconnect
  - skill install start/success/failure
  - token rotation
  - webhook received/processed
- Avoid noisy logs in hot paths.

### Configuration
- Config must come from environment variables or documented config files.
- Provide `.env.example` or documented env var list when adding new config.
- Fail fast on missing required config with explicit error.

### API boundaries
- Keep provider adapters (Telegram/WhatsApp) separate from OpenClaw logic.
- Cloud<->Device contract changes must update both sides and be documented.

---

## 6) Testing & Verification (Must Be Demonstrated)

### Minimum verification for any change
- Run the “fast path” checks (lint/unit) if available.
- Run targeted tests for touched modules.
- If tests don’t exist, add them (or add a minimal smoke test).

### Evidence
In your response, include:
- Commands you ran
- What passed/failed
- Any important output (short excerpts only)

If you cannot run commands (missing tooling, no test suite), say so and provide a safe alternative:
- static checks
- mocked/unit tests
- a smoke script
- exact manual verification steps

---

## 7) Documentation Requirements

Whenever you change:
- env vars → update `.env.example` / docs
- architecture/contracts → update PLAN.md and any API docs
- setup steps → update README or create `docs/`

Docs must include “how to reproduce” for developer workflows.

---

## 8) Decision Report (REQUIRED)

For every task, include a **Decision Report** section in your final answer.

### Format
#### Decision Report
- **Context:** 2–5 bullets describing the problem and constraints.
- **Options considered:** at least 2 options unless truly trivial.
- **Chosen approach:** what you did.
- **Why this approach:** tie back to PLAN.md constraints, reliability, simplicity.
- **Tradeoffs:** explicit pros/cons, what you are giving up.
- **Risks:** what could go wrong, how mitigated.
- **Follow-ups:** what to do next, what you intentionally deferred.

### Examples of acceptable tradeoffs
- “Used websocket with reconnect logic vs polling because… tradeoff: requires stateful connection mgmt.”
- “Used SHA256 integrity check now; deferred signature verification until Phase 2 hardening.”

If you made assumptions, list them explicitly.

---

## 9) Escalation When Blocked (No Guessing)

If you are stuck, produce:
- What you tried
- Exact error and where it occurs
- Hypothesis
- Smallest next step to validate
- What info you need from the user (only if unavoidable)

Prefer making progress with safe partial work rather than stalling.

---

## 10) Repository Quickstart (Fill In / Keep Updated)

This section should be kept accurate. If missing, add it.

### Common commands (example template)
- Install:
  - `<command>`
- Run dev:
  - `<command>`
- Run tests (fast):
  - `<command>`
- Run tests (full):
  - `<command>`
- Lint/format/typecheck:
  - `<command>`
- Healthcheck:
  - `./scripts/healthcheck.sh`

Agents must update this section when they introduce new workflows.

---

## 11) NestorAI invariants (Do not violate unless PLAN.md changes)

- Device remains headless; no device UI.
- Device connectivity is outbound-only.
- Skills install into `/data/skills` and are managed via catalog.
- Provider abstraction must isolate Telegram/WhatsApp from core skill engine.
- Every network edge has timeouts + error handling.

---

## 12) What “Done” Means Here

A change is done only when:
- It satisfies the relevant phase acceptance criteria in PLAN.md
- It is tested or has clear verification steps
- It includes an explicit Decision Report
- It does not introduce hidden maintenance burden without justification
