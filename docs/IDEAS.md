# Ideas (not in v0 scope)

- Port the Vertex Gemini and Anthropic adapters from the example-brand build (`../brain/llm_gen.py`) as optional extras, for when we want vendor-native features (caching, thinking budgets) over OpenAI-compat.
- `make reembed`: re-embed claims whose `embed_model` differs from the current `EMBED_MODEL` (needed when switching embedding models or dimensions).
- A real `Search` provider for `market_scan`: a free search API, or a web-enabled OpenRouter model.
- Per-phase model routing: a cheap/fast free model for extraction, a stronger model for synthesis phases.
- `image.py` (ported from example-brand) has hard deps on `requests` / `google-genai`. Wrap it in the OpenAI-compat style, or drop it when the content builder moves over.
- Output store for generated content (campaign copy) separate from claims: `record_output` / `recent_outputs`, needed to migrate example-brand's anti-repetition (docs/example-brand_MIGRATION.md).
- IG performance digests → `propose(origin="ig_digest")` so the founder approves learnings.
- `vybd login --token` / token recovery (v0 signup is one-shot per email).
- Looping research phases that use the remaining budget (deeper market rounds) — the scaffolding supports long resumable runs.
- Per-phase partial checkpoints, so a budget stop mid-phase keeps partial work.
- Explicit `vybd admin resume <run>` instead of overloading `approve` for failed/paused runs.
