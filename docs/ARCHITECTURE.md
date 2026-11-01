# Vybd Brand Builder: architecture (as built, 2026-11-01)

A founder completes a guided ~10-minute brand brief through the `vybd` CLI, driven by Claude Code or typed by hand. They then submit it for a budgeted, checkpointed background **Brand Brain run**, which returns a report plus proposed brief changes. The founder accepts or rejects each proposal.

There are four packages in one uv workspace. Postgres has two schemas, and models are reached through OpenRouter (free models only, behind an OpenAI-compatible adapter).

## System overview

```mermaid
flowchart TB
    %% ---------- clients ----------
    subgraph Clients["Clients"]
        CC["Claude Code<br/>(agent drives CLI, --json)"]
        Human["Founder in terminal"]
        Browser["Browser<br/>/ui brand view (read-only, polls 3s)"]
    end

    CLI["vybd CLI<br/>packages/cli · Typer + httpx + rich<br/>~/.vybd/config.toml (token, current brand)"]

    CC --> CLI
    Human --> CLI

    %% ---------- server ----------
    subgraph Server["server · FastAPI (packages/server)"]
        direction TB
        Auth["auth<br/>bearer tokens (sha256)"]
        Routes["routes<br/>auth · brands · brief · challenges<br/>notes · score · runs · proposals · admin"]
        Env["envelope<br/>ok · data · agent_instructions<br/>next_actions · progress · errors"]
        Chal["challenge catalog<br/>content/challenges/brief_v1/*.yaml<br/>+ agent_instructions.md"]
        Scorer["Scorer protocol<br/>CompletenessScorerV0<br/>score · eligibility · LLM feedback"]
        UI["/ui<br/>static HTML page"]
        Routes --> Env
        Routes --> Chal
        Routes --> Scorer
        Auth --> Routes
    end

    CLI -- "HTTP /v1 (only interface)" --> Auth
    Browser -- "HTTP /v1 + bearer token" --> Auth
    Browser --> UI

    %% ---------- brain ----------
    subgraph Brain["brain · library (packages/brain), imports nothing from server/runner/cli"]
        direction TB
        BB["BrandBrain API<br/>create_brand_space · ingest · brief · search<br/>context_pack · propose · accept / reject"]
        Curator["curator v0<br/>1 LLM call → atomic claims<br/>(section, kind, confidence, excerpt)"]
        BriefB["brief builder<br/>sections → accepted claims + version hash"]
        Retr["retrieval<br/>pgvector cosine search<br/>context_pack (decisions first)"]
        Store["store<br/>all brain SQL"]
        Prov["providers<br/>LLMProvider · Embedder<br/>OpenAICompat (OpenRouter) · Fake"]
        BB --> Curator --> Prov
        BB --> BriefB
        BB --> Retr --> Prov
        BB --> Store
    end

    Routes -- "library calls" --> BB
    Scorer -- "feedback call" --> Prov

    %% ---------- runner ----------
    subgraph Runner["runner · worker (packages/runner)"]
        direction TB
        Worker["worker<br/>FOR UPDATE SKIP LOCKED claim<br/>5-min lease + heartbeat · cancel check"]
        Budget["budget<br/>BudgetedLLM: steps · tokens · $ · wall time"]
        Pipe["pipeline (checkpoint after each phase)<br/>understand → market_scan → customer_insight<br/>→ opportunities → focus_plan → report"]
        Search["Search protocol<br/>FakeSearch (real = stub)"]
        Worker --> Pipe --> Budget
        Pipe --> Search
    end

    Budget --> Prov
    Pipe -- "frozen context_pack · propose()" --> BB

    %% ---------- data ----------
    subgraph PG["Postgres 16 + pgvector (docker, :5433)"]
        AppS[("app schema<br/>users · api_tokens · brands · attempts<br/>score_snapshots · runs · run_events")]
        BrainS[("brain schema<br/>brand_spaces · raw_inputs · claims (vector)<br/>claim_evidence · proposals")]
    end

    Routes --> AppS
    Worker --> AppS
    Store --> BrainS

    %% ---------- external ----------
    OR["OpenRouter API<br/>free models only (:free guard)<br/>chat: nemotron-3.5-lightning / super, gemma fallbacks<br/>embeddings: lfm-2.5-embedding-350m (1024-d)"]
    Prov -- "HTTPS, retries, fallbacks" --> OR
```

**Layering rules** (enforced by import-linter in `make lint`):
- `brain` never imports `server`, `runner` or `vybd_cli`.
- `vybd_cli` never imports `brain`, `server` or `runner`; it talks HTTP only.
- `runner` may use `brain` and `server`'s models (the `runs` table).

## The Brand Brain (knowledge model)

```mermaid
flowchart LR
    subgraph In["Inputs"]
        A["challenge answer<br/>source_type=challenge_answer"]
        N["note<br/>source_type=note"]
        I["import (example-brand)<br/>source_type=import"]
        R["run output"]
    end

    Raw[("raw_inputs<br/>verbatim text, author, source_ref")]
    Cur["curator v0<br/>extract 1–6 atomic claims"]
    Claims[("claims<br/>text · section · kind · status<br/>authority · confidence · embedding")]
    Ev[("claim_evidence<br/>claim ↔ raw_input + excerpt")]
    Prop[("proposals<br/>pending → accepted / rejected")]

    A --> Raw
    N --> Raw
    I --> Raw
    Raw --> Cur --> Claims
    Claims --- Ev --- Raw

    R -- "propose() only, never claims" --> Prop
    Prop -- "accept → new accepted claim<br/>(authority=user_approved)" --> Claims
    Prop -- "reject → decision claim<br/>'Rejected X. Reason: Y'" --> Claims

    Claims --> Brief["BriefView<br/>10 sections + Other<br/>version hash"]
    Claims --> Pack["context_pack(purpose, max_tokens)<br/>brief, trimmed by relevance"]
```

- **Claim kinds:** fact, decision, constraint, hypothesis, idea, preference.
- **Statuses:** accepted, proposed, rejected, superseded, parked.
- **Re-answering a challenge** supersedes only the claims from that challenge's earlier answers. Notes in the same section survive.
- **Brief sections:** `one_liner, customer, problem, alternative, positioning, product, price, channels, competitors, goals`. Unknown sections show under "Other".

## Answer flow

```mermaid
sequenceDiagram
    autonumber
    participant F as Founder
    participant CC as Claude Code
    participant CLI as vybd CLI
    participant S as Server
    participant B as Brain
    participant OR as OpenRouter

    CC->>CLI: vybd --json challenge next
    CLI->>S: GET /v1/brands/{id}/challenges/next
    S-->>CC: challenge + agent_instructions + next_actions
    CC->>F: lesson (1–2 sentences) + question
    F->>CC: answer in their words
    CC->>CLI: vybd --json challenge answer <id> --text "..."
    CLI->>S: POST .../answer
    S->>B: ingest(source_type=challenge_answer, section_hint)
    B->>OR: curator: extract claims (structured JSON)
    B->>OR: embed claims
    B-->>S: claims (+ superseded ids)
    S->>OR: scorer feedback (never blocks)
    S->>S: save attempt · score snapshot
    S-->>CC: claims · feedback · progress(score, eligible) · next challenge
    CC->>F: one-line feedback, next question
```

If the LLM fails during ingest, the server returns `502 provider_unavailable` with a retry instruction and records no attempt.

## Run lifecycle

```mermaid
stateDiagram-v2
    [*] --> requested: run.submit (eligible, no other active run)<br/>brief frozen into checkpoint
    requested --> queued: admin.approve (or AUTO_APPROVE_RUNS)<br/>budget copied from RUN_BUDGET_*
    requested --> cancelled: admin.cancel
    queued --> running: worker claims (SKIP LOCKED, lease)
    running --> running: lease expired → another worker reclaims<br/>completed phases skipped
    running --> completed: all phases done<br/>or budget limit hit (report still written)
    running --> failed: phase exception (checkpoint kept)
    running --> cancelled: admin.cancel (stops before next phase)
    failed --> queued: admin.approve (resume from checkpoint)
    completed --> [*]
    cancelled --> [*]
```

`paused` and `approved` exist in the schema but nothing uses them yet.

## Data model

```mermaid
erDiagram
    USERS ||--o{ API_TOKENS : has
    USERS ||--o{ BRANDS : owns
    BRANDS ||--o{ ATTEMPTS : "challenge answers"
    BRANDS ||--o{ SCORE_SNAPSHOTS : scored
    BRANDS ||--o{ RUNS : runs
    RUNS ||--o{ RUN_EVENTS : logs
    BRANDS ||--|| BRAND_SPACES : "brand_id (str uuid)"
    BRAND_SPACES ||--o{ RAW_INPUTS : stores
    BRAND_SPACES ||--o{ CLAIMS : knows
    BRAND_SPACES ||--o{ PROPOSALS : suggested
    CLAIMS ||--o{ CLAIM_EVIDENCE : "backed by"
    RAW_INPUTS ||--o{ CLAIM_EVIDENCE : supports
    PROPOSALS |o--o| CLAIMS : "resulting_claim"
```

The left side is the `app` schema (owned by the server); the right side is the `brain` schema (owned by the brain library). They are joined only by `brand_id`.

## Configuration

| Setting | Current local value | Notes |
|---|---|---|
| `LLM_PROVIDER` / `EMBED_PROVIDER` | `openai_compat` | `fake` for tests and CI |
| `LLM_MODEL` / `LLM_MODELS` | nemotron-3.5-lightning, then fallbacks | interactive calls (curator, feedback) |
| `RUNNER_LLM_MODEL` / `RUNNER_LLM_MODELS` | nemotron-3.5-super, then fallbacks | background run phases |
| `LLM_MIN_MAX_TOKENS` / `LLM_REASONING_EFFORT` | 4000 / low | protection against reasoning models returning empty output |
| `ALLOW_PAID_MODELS` | false | refuses any non-`:free` OpenRouter model |
| `EMBED_MODEL` / `EMBED_DIM` | lfm-2.5-embedding-350m / 1024 | dimension is fixed when the brain migration runs |
| `SEARCH_PROVIDER` | fake | the real provider is a stub |
| `AUTO_APPROVE_RUNS` | true (dev only) | false in normal use; admins approve |
| `RUN_BUDGET_*` | 10h · 2M tokens · $25 · 400 steps | placeholders |

## Where things live

| Path | What |
|---|---|
| `packages/brain/src/brain/` | `api.py` (BrandBrain), `curator.py`, `store.py`, `brief.py`, `retrieval.py`, `providers/` |
| `packages/server/src/server/` | `main.py`, `routes/`, `envelope.py`, `challenges.py`, `scoring/`, `ui/index.html` |
| `packages/runner/src/runner/` | `worker.py`, `budget.py`, `pipeline.py`, `phases/`, `search.py` |
| `packages/cli/src/vybd_cli/` | `main.py`, `client.py`, `config.py`, `render.py` |
| `content/` | challenge YAMLs and the global agent instructions |
| `evals/personas/` | 4 founder personas for end-to-end tests |
| `scripts/` | `e2e_fake.py`, `curl_brief.sh`, `import_example-brand.py` |
| `docs/` | DECISIONS, IDEAS, PROVIDER_NOTES, example-brand_MIGRATION, BACKLOG |

See [BACKLOG.md](BACKLOG.md) for what's next.
