# Vybd Brand Builder: working notes for Claude Code

Founders finish a guided ~10-minute brand brief through the `vybd` CLI, then submit it for a budgeted, checkpointed background "Brand Brain run". The run returns a report plus proposed brief changes. The v0 spec is the contract; `docs/DECISIONS.md` records where we deviate from it.

## Layout
- `packages/brain`: brand knowledge library (claims, brief, retrieval, proposals, providers). **Never imports server/runner/cli** (import-linter).
- `packages/server`: FastAPI. Users, brands, challenges, scoring, runs. The HTTP API is the only interface.
- `packages/runner`: background worker. Phases, budget, checkpoints.
- `packages/cli`: `vybd`, a thin HTTP client. **Never imports brain/server/runner.**
- `content/`: challenge YAMLs and global agent instructions.
- `docs/`: DECISIONS (log every choice the spec doesn't cover), IDEAS (out-of-scope ideas go here, not into code), PROVIDER_NOTES.

## Commands
```bash
uv sync               # install
cp .env.example .env  # then edit
make db               # postgres + pgvector on :5433 (needs Docker Desktop)
make migrate          # both alembic histories
make dev              # db + migrate + server (:8000) + worker
make test             # fake providers; db tests skip if postgres is down
make test-live        # real OpenRouter calls (LLM_API_KEY)
make lint             # ruff + import-linter
make e2e-fake         # scripted clear-founder run: server + worker + CLI, fake providers
scripts/curl_brief.sh # complete the whole brief over HTTP (needs a running server)
```

## Rules
- Build milestone by milestone and stop after each one with a summary: what was built, what was stubbed, how to try it.
- Mark every stub `# STUB:` with one line saying what the real version should do.
- Models are OpenRouter `:free` only, behind `brain.providers` (OpenAI-compatible). No vendor SDKs outside `providers/`.
- Use fake providers in tests by default; mark real calls `@pytest.mark.live`.
- Prefer boring, explicit code. The interfaces in the spec are the contract.

## Driving the CLI (agents)
- Always pass `--json`; read `agent_instructions` and `next_actions` from every response.
- Loop: `vybd --json challenge next` → ask the founder (follow `agent_instructions`) → `vybd --json challenge answer <id> --text "<their words>"`.
- Exit 1 = error envelope (read `errors[0].code`); exit 2 = local problem (server down, no brand).
- Isolate state with `VYBD_HOME=/tmp/somewhere` and point at a server with `VYBD_API_URL`.

## Milestone status
- [x] M1: repo skeleton
- [x] M2: brain v0 (live OpenRouter test pending an API key)
- [x] M3: server core
- [x] M4: CLI
- [x] M5: scoring + submit
- [x] M6: runner
- [x] M7: persona e2e (Claude-driven persona runs: see below)
- [x] M8: example-brand as tenant (`make seed`, docs/example-brand_MIGRATION.md)

## Persona run
Use this to test the whole product as a founder would experience it. You play **both** roles: the agent driving the CLI (follow `agent_instructions` exactly) and the founder (answer only as the persona file says).

1. **Start the stack** (fake providers are fine for plumbing; use `LLM_PROVIDER=openai_compat` + key for a real-quality run):
   ```bash
   make db && make migrate
   AUTO_APPROVE_RUNS=true make dev   # server :8000 + worker; leave running
   ```
2. **Fresh user and brand** (isolated config):
   ```bash
   export VYBD_HOME=$(mktemp -d) VYBD_API_URL=http://localhost:8000
   uv run vybd --json signup --email "<persona>-$(date +%s)@example.com"
   uv run vybd --json brand create "<persona's brand>"
   ```
3. **Role-play the brief** with `evals/personas/<persona>.md`:
   - Loop: `uv run vybd --json challenge next`, then ask the "founder" the question the way `agent_instructions` says, then answer *as the persona* (including their vagueness or rambling), then `uv run vybd --json challenge answer <id> --text "<persona's words>"`.
   - Handle `answer_too_short` and other errors as the envelope instructs. Never invent answers the persona wouldn't give.
   - Use `vybd note` for off-topic but useful detail. For `changes_mind`, re-answer `positioning` when the persona says so.
4. **Submit and wait:** `vybd --json run submit`, then poll `vybd --json run status` until `completed`, then read `vybd --json run report`.
5. **Proposals:** `vybd --json proposals`; accept or reject each as the persona would (`--reason` in their words), then `vybd --json brief`.
6. **Save a transcript** to `evals/runs/<persona>-<YYYYmmdd-HHMMSS>.md`: every command, the key parts of each response, and what the "founder" said.
7. **Report at the top of the transcript, and to the user:**
   - time to complete the brief (wall clock, and number of follow-ups asked);
   - whether the flow got stuck anywhere (errors, confusing next_actions, loops);
   - whether `agent_instructions` were clear and sufficient, and what you'd change;
   - quality of the brief, report and proposals (with real models).

`make e2e-fake` is the scripted, non-Claude version of the clear-founder path (runs in CI).
