# Provider Notes

Records which external API contracts are **confirmed** (tested live or read from source) and which are **not confirmed** (taken from docs). Update this file whenever a live test confirms or refutes a contract.

The example-brand build's notes (Segmind, Vertex, supermemory) are kept verbatim in `PROVIDER_NOTES.example-brand.md` for reference.

---

## OpenRouter (chat + embeddings): status as of 2026-11-01

Source: OpenRouter docs and model pages (not yet tested live from this repo).

| Contract | Status |
|---|---|
| OpenAI-compatible `POST /api/v1/chat/completions` | from docs, not confirmed |
| OpenAI-compatible `POST /api/v1/embeddings` | from docs, not confirmed |
| `:free` suffix marks free model ids; `openrouter/free` router | from docs, not confirmed |
| `models: [...]` fallback array in request body | from docs, not confirmed |
| `usage.cost` present in responses | not confirmed |
| `response_format` JSON-schema support on free models | varies per model, not confirmed |
| Free-tier rate limits (429 behavior, daily caps) | not confirmed |
| `liquid/lfm-2.5-embedding-350m:free` → 1024-d | from model page, not confirmed |
| `nvidia/nemotron-3-embed-1b:free` dimension | unknown |

### Confirmed 2026-11-01 via public `GET /api/v1/models` and `GET /api/v1/embeddings/models` (no key)
- There are 452 models, 15 of them free chat models. Free models that support JSON output (`response_format` / `structured_outputs` listed in their supported parameters) include `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3.5-super-vl:free` and `openrouter/free`. Several free models (e.g. `nvidia/nemotron-3-ultra-550b-a55b:free`, `thinkingmachines/inkling:free`) do **not** list JSON support. The adapter falls back to prompt-only JSON for those.
- There are 38 embedding models, 5 of them free: `nvidia/nemotron-3.5-embed-1b:free`, `nvidia/nemotron-3.5-embed-8b:free`, `nvidia/nemotron-3-embed-1b:free`, `nvidia/llama-nemotron-embed-vl-1b-v2:free` and `liquid/lfm-2.5-embedding-350m:free`. The Liquid model is 1024-d per its description, but its **context is only 512 tokens**. That's fine for atomic claims and short queries; long search queries would be truncated or rejected.
- The defaults chosen in `.env.example` are chat `google/gemma-4-31b-it:free` (fallbacks: gemma-4-26b, `openrouter/free`) and embeddings `liquid/lfm-2.5-embedding-350m:free` (EMBED_DIM=1024).

**The free lineup changes often**: models are added during launch promotions and pulled afterwards. Check the current list on openrouter.ai/models before choosing defaults.

**Data:** free-model requests may be retained or used for training by the model vendors (see DECISIONS).

The live smoke test is planned for Milestone 2 (`make test-live`).
