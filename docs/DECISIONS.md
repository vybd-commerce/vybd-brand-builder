# Decisions

Choices not covered by the v0 spec (2026-11-01). Newest last.

## 2026-11-01: Models go through OpenRouter, free models only, provider-agnostic
- **Overrides** spec §3 and §13 (Vertex Gemini default, Claude switch, Vertex `text-embedding-005`).
- There is one OpenAI-compatible adapter for chat and one for embeddings, configured by `LLM_BASE_URL`, `LLM_MODEL`, `EMBED_BASE_URL` and `EMBED_MODEL`. The default base URL is OpenRouter. Pointing them at Ollama, vLLM, OpenAI or similar needs no code change.
- `LLM_PROVIDER` / `EMBED_PROVIDER` take `fake | openai_compat`, replacing `gemini | claude | vertex`.
- A guard rejects any OpenRouter model id without the `:free` suffix (except `openrouter/free`) unless `ALLOW_PAID_MODELS=true`.
- The Vertex and Anthropic adapters from the example-brand build are **not** ported (see IDEAS).

## 2026-11-01: Embedding dimension is configurable, default 1024
- The spec says `vector(768)`. Free OpenRouter embedding models vary (e.g. `liquid/lfm-2.5-embedding-350m:free` is 1024-d).
- `EMBED_DIM` sets the pgvector column size when the brain migration runs. Claims also store `embed_model` so a model switch can re-embed them later.

## 2026-11-01: Data caveat for free models
- Free-model requests may be retained or used for training by the model vendors. Founder briefs will go to those vendors.
- Acceptable for v0. Check the OpenRouter account privacy toggles, and revisit before real customers.

## 2026-11-01: Spec ambiguities
- **9 challenges, 8 required.** `competitors` is optional, which matches the `required: 8` in the envelope example.
- **`product_price` covers two brief sections.** `section_hint="product"`; the curator may tag individual claims `price`.
- **Supersede on re-answer goes by origin, not section.** Only claims from earlier answers to *that challenge* are superseded (raw_input `source_type=challenge_answer`, `source_ref=<challenge_id>`). Notes in the same section survive.
- **Tests need real Postgres** (pgvector, `SKIP LOCKED`). There's no sqlite fallback. DB tests skip locally when Postgres is down and fail in CI (`REQUIRE_DB_TESTS=1`).

## 2026-11-01: Repo mechanics
- The root `pyproject.toml` is a non-package uv workspace root. Packages are named `vybd-brain`, `vybd-server`, `vybd-runner` and `vybd-cli`; their import names are `brain`, `server`, `runner` and `vybd_cli`.
- Each package has its own Alembic history, with its version table in its own schema (`brain.alembic_version`, `app.alembic_version`).
- A second import-linter contract (not in the spec) forbids `vybd_cli` from importing `brain`, `server` or `runner`. This keeps the CLI a pure HTTP client.
- `pytest --import-mode=importlib`, so test modules in different packages can share basenames.

## 2026-11-01: Local DB port is 5433
- A native Postgres on this machine already listens on 5432 and would shadow the container. Compose maps `${VYBD_DB_PORT:-5433}:5432`. CI still uses 5432 through env vars.

## 2026-11-01: Brain v0 details (Milestone 2)
- **`brain.brand_spaces` table.** The spec has no brain-side tenancy table. `create_brand_space` inserts a row, and every brain call raises `BrandSpaceNotFound` for unknown brands.
- **`authority` values** (the spec doesn't define them): `user` for challenge answers, notes, imports and rejection decisions; `user_approved` for accepted proposals.
- **`ingest` source types:** `challenge_answer`, `note` and `import`, which all become `accepted` claims. Any other value raises and points to `propose()`.
- **Proposal decisions are stored as raw inputs** (`proposal_accept` / `proposal_reject`) so every claim has evidence.
- **Rejection reasons are written directly**, without the LLM, as `Rejected suggestion "<text>". Reason: <reason>` (kind `decision`, same section as the proposal).
- **Supersede on re-answer doesn't set `supersedes_id`.** One answer can replace N claims with M claims. `IngestResult.superseded_claim_ids` lists what was replaced.
- **Curator fallback.** If the LLM returns zero claims, the whole input is kept as one low-confidence `fact`, so a founder's words are never dropped.
- **Curator excerpt.** The LLM is asked for a verbatim excerpt; if none comes back, the first 500 characters of the input are used.
- **`context_pack`** returns the whole brief if it fits. Otherwise it keeps decisions and constraints first, then claims by relevance to `purpose`, and adds an "N omitted" note.
- **`brief.version`** is a hash of the (id, updated_at) pairs of the accepted claims.
- **Defaults in `.env.example`:** chat `google/gemma-4-31b-it:free` with fallbacks, embeddings `liquid/lfm-2.5-embedding-350m:free`. These came from the live public model listing on 2026-11-01 (see PROVIDER_NOTES).
- **Structured output:** request `response_format: json_schema` (non-strict). On HTTP 400, retry once with a prompt-only request and remember that for the rest of the process. If the result fails validation, make one repair call that includes the validation error.

## 2026-11-01: Server core details (Milestone 3)
- **Answer flow order is ingest first, then save the attempt** (the spec saves the attempt first). If the LLM or embedder fails, the API returns `502 provider_unavailable` with a "retry" instruction and records no attempt, so progress doesn't count an answer that never reached the brain. The unprocessed raw input stays in `brain.raw_inputs` (`processed_at` is null).
- **Signup with an existing email returns `409 email_taken`.** Returning a new token would let anyone take over an account, since there is no verification yet. Login and token recovery are `# STUB:` for later.
- **Tokens:** `vybd_` + 32 random url-safe bytes, stored as sha256. Each request updates `last_used_at`.
- **`brand_id` shared with the brain** is `str(brands.id)` (UUID). The brain space is created in the same request as the brand.
- **Unowned and unknown brands both return 404**, so brand existence doesn't leak.
- **Every response, errors included, is the §8 envelope.** Error codes so far: `unauthorized`, `not_found`, `email_taken`, `invalid_email`, `answer_too_short`, `invalid_request`, `empty_note`, `already_decided`, `provider_unavailable`.
- **Progress `score` / `eligible` are null until the Milestone 5 scorer exists.** Progress adds `est_minutes_left` (the sum over unanswered challenges, both required and optional).
- **Next-action guidance:** once all required challenges are done, the optional `competitors` challenge is still offered first, alongside `run.submit`.
- **`LLM_PROVIDER=fake` now uses the curator-aware fake** (one claim per sentence, in the hinted section), so a dev server with fake providers produces a readable brief.
- **The test session truncates the `app` and `brain` tables once at start**, so fixed-email tests can be repeated.
- **Challenge content:** total estimated time is 10.5 minutes. Examples cite only commonly documented brand facts (Warby Parker tagline, Spanx origin, Dollar Shave Club, Oatly tagline, Allbirds' $95 Wool Runner, Glossier/Into The Gloss). The spec's own Body Glide example is kept as written.

## 2026-11-01: CLI details (Milestone 4)
- **Exit codes:** `0` ok, `1` the server returned an error envelope, `2` a local problem (server unreachable, no current brand, no recent run). With `--json`, local problems also print an envelope (codes `unreachable`, `no_brand`, `no_run`), so agents always get JSON.
- **`--json`** works both globally (`vybd --json challenge next`) and per command (`vybd challenge next --json`).
- **Config** lives at `~/.vybd/config.toml` (override the directory with `VYBD_HOME`), mode 0600. It holds `token`, `email`, `current_brand`, `last_run`, and optionally `api_url`. `VYBD_API_URL` takes precedence over the config value.
- **Local state is saved before printing,** so a closed pipe (`vybd brand create X | head`) can't lose the token or current brand.
- **`signup` and `brand create` reset `current_brand` / `last_run`.**
- **`brand use` checks the id against the server's brand list** before switching.
- **`--text -` and `vybd note -` read from stdin**, for long answers.
- **`run status|events|report` default to the last submitted run.**
- **`proposals` with no subcommand lists them** (`--status pending` by default).
- **Commands for Milestones 5 and 6 (score, run, proposals, admin) exist already.** Until those endpoints land they get the server's `404 not_found` envelope. Their data shapes (`data.score`, `data.run`, `data.events`, `data.report_md`, `data.proposals`, `data.runs`) are the contract M5 and M6 will implement.

## 2026-11-01: Scoring + submit (Milestone 5)
- **A score snapshot is written** on every answer, every `GET score` and every submit. Progress in every envelope now carries `score` and `eligible`.
- **Optional bonus:** each answered optional challenge adds +5. The total is capped at 100. `Attempt.score` stores that challenge's points.
- **Feedback** is one LLM call returning `{note, suggestion}`. It never raises (failure gives an empty note). The agent is told to pass it on in one line and move on.
- **Submit gates:** not eligible → `409 not_eligible` (with next_actions); another active run (`requested|approved|queued|running|paused`) → `409 run_active`.
- **The frozen snapshot** goes in `runs.checkpoint.frozen`: `brief_version`, `context_pack` (6000 tokens, purpose "Brand Brain run: grow this brand"), brand name and score. `budget` stays `{}` until approval, which copies `RUN_BUDGET_*`.
- **Approval goes straight from `requested` to `queued`** (with `approved_at` / `approved_by`). The `approved` status exists but is unused. `AUTO_APPROVE_RUNS=true` queues at submit with `approved_by="auto"`.
- **`admin approve` also re-queues `failed` / `paused` runs** (resume from checkpoint). The spec has no separate resume command.
- **Run visibility:** the brand owner or an admin. Everyone else gets 404.
- **The report endpoint returns `409 report_not_ready`** until the run has a report.
- **Proposal endpoints** (list/accept/reject) also landed here; `status=all` lists all of them.

## 2026-11-01: Runner (Milestone 6)
- **Budget:** a step is counted before each LLM call, so `max_steps=N` allows exactly N calls. Wall time accumulates across resumes (`spent.wall_seconds`). Spent is persisted after every call, with an `llm_call` event recording tokens, cost and the model that actually answered.
- **Budget stop:** skip the remaining research phases, still run `report` (no LLM), complete the run with `spent.stopped_by`. The report says "Stopped early" and marks unreached sections. The interrupted phase's partial work is lost. "Finish the current write-up if possible" is approximated by the report covering finished phases only.
- **Phase exceptions** mark the run `failed` (error + traceback event). Completed phases stay in the checkpoint. A worker that dies mid-run is handled by lease expiry: any worker reclaims `running` runs whose lease is past.
- **Cancellation:** the heartbeat's lease renewal fails once the status isn't `running`, and the worker checks status before each phase. A phase that is already running finishes first.
- **Proposals** are only created at the end, from the report phase's de-duplicated drafts. They are skipped if a proposal with the same text and `origin_ref=run_id` already exists, so a crash between proposing and completing can't duplicate them.
- **Phases read the frozen `context_pack`**, not the live brief, so a run is reproducible against what was submitted.
- **Proposal drafts** constrain `section` to the 10 brief sections.
- **Phase prompts put the TASK first, then the brief and earlier phases, then repeat the instruction.** This also makes fake output differ per phase.
- **Search:** the `fake` provider only, with clearly labelled placeholder results, and the report notes it. A real provider is `# STUB:`.
- **Fake LLM change:** `build_default` now also fills non-Optional `str` fields that have defaults (so fake feedback has a note). Optional fields stay `None`.

## 2026-11-01: Persona e2e (Milestone 7) and example-brand (Milestone 8)
- **`make e2e-fake`** starts a real uvicorn server and worker as subprocesses on a free port, drives the real CLI with `--json` (`python -m vybd_cli.main`), runs the clear-founder answers, waits for the run, accepts one proposal and rejects one, and writes `evals/runs/clear_founder-fake-<ts>.md`. `evals/runs/` is gitignored.
- **Persona files** contain the persona's answers and a "what to watch" section, so a Claude-driven run has a grading rubric.
- **The example-brand import** uses `source_type="import"` (accepted claims, `authority=user`), skips "Example copy" and images, and refuses to import twice without `--force`. `make seed` runs it. See `docs/example-brand_MIGRATION.md`.
