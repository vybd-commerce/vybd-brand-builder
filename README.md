# Vybd Brand Builder

Research service behind [Vybd](https://www.vybd.ai). A founder (or their AI agent) completes a guided brand brief, then submits it for a budgeted, checkpointed research run. The run returns a report and proposed changes to the brief, each backed by evidence.

The [vybd-agent](https://github.com/vybd-commerce/vybd-agent) app calls this service for its `brand_research` job.

## How it is built

| Package | What it does |
|---|---|
| `packages/brain` | Brand knowledge: claims with evidence, the brief, retrieval, proposals, model providers |
| `packages/server` | FastAPI HTTP API: users, brands, brief challenges, scoring, runs |
| `packages/runner` | Background worker: research phases (understand, market scan, customer insight, opportunities, focus plan, report), budget and checkpoints |
| `packages/cli` | `vybd`, a thin HTTP client designed to be driven by an AI agent (`--json`, `next_actions`) |
| `content/` | Brief questions and agent instructions as YAML |

Models are any OpenAI-compatible provider (OpenRouter by default). Postgres with pgvector stores claims and embeddings.

## Run it

```bash
uv sync
cp .env.example .env   # set LLM_API_KEY for real model calls
make dev               # Postgres + pgvector, migrations, API on :8000, worker
make test              # uses fake providers; no keys needed
make e2e-fake          # scripted founder run end to end
```

`make help` lists every command. `CLAUDE.md` explains how to drive the CLI from a coding agent.

## Status

Early. Web search is a placeholder (`packages/runner/src/runner/search.py`), so market research is not yet real. See `docs/BACKLOG.md`.

## Contributing

Read the [contributing guide](https://github.com/vybd-commerce/.github/blob/main/CONTRIBUTING.md). Report security problems privately as described in [SECURITY.md](https://github.com/vybd-commerce/.github/blob/main/SECURITY.md).

## Licence

[Apache-2.0](LICENSE). The licence does not cover the Vybd name or logo.
