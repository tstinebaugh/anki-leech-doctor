# 0003: Gemini model list and a measured fallback order

Status: accepted, 2026-11-24

## Context

The fallback list was a hard-coded order in `gemini_client.py`. On 2026-11-24 the call log
showed it was out of date:

| Model | Calls | Answered | Overloaded | Timed out | Median answer |
|---|---|---|---|---|---|
| gemini-flash-lite-latest | 93 | 72 | 20 | 1 | 5.7s |
| gemini-3-flash-preview | 36 | 35 | 0 | 0 | 13.3s |
| gemini-flash-latest | 28 | **0** | 20 | 7 | – |
| gemini-3.1-flash-lite | 27 | 13 | 10 | 4 | 9.0s |
| gemini-3.6-flash | 20 | 6 | 2 | 11 | 16.6s |

`gemini-flash-latest` was still in Gemini's model list, so it hadn't been retired. A 429 from it
named `gemini-3.8-flash`: the alias had moved to the newest Flash, which was overloaded and
had used its free quota. `gemini-flash-lite-latest` replied with `modelVersion:
gemini-3.5-flash-lite`, and `gemini-3.5-flash` was silently served by `gemini-3.6-flash`.

Gemini's model list (`GET /v1beta/models`) says which models exist, but not where an alias
points, how busy a model is, or when it will be retired.

## Decision

`model_catalog.py`, with two additions to the database (migration 0002):

| Change | Used for |
|---|---|
| `gemini_models` table | the model list, fetched again when over 7 days old; a model the latest fetch didn't return is treated as removed |
| `gemini_calls.model_version` | the model that served each call: the reply's `modelVersion`, or the model a quota error names |

The order a call tries models in:

1. The configured model, always first: it's the user's choice. The dashboard notes if it has left the model list.
2. The fallbacks (`fallbackModels` in config, default `FALLBACK_MODELS`), sorted by
   **time spent per answer** over the last 7 days: `(time on answers + time on failures + 10s) / (answers + 1)`.
   This is the classic order for trying options one after another (cost of an attempt over
   its chance of success). The `+ 10s / + 1` prior puts an untried model in the middle
   rather than first or last, and with no history the configured order is kept.
3. A fallback is skipped if the model list no longer has it, or if it points at a model
   already in the order. Two names for one model share its quota and its overload.

ModelHealth cooldowns and the daily-limit demotion apply on top, as before.

The refresh needs no scheduler. A Gemini call that finds the list stale starts a
background refresh, and opening the dashboard refreshes before answering. A failed refresh
keeps the old list and waits an hour before trying again. New text Flash models are listed
in Settings with an *Add* button, but are never added automatically: a new model may
need different settings or write worse Japanese.

## Alternatives considered

- **A cron job or scheduler thread.** The app only needs a current list when it is in use,
  and a scheduler adds a moving part to a single-user local app.
- **Use the newest Flash from the model list automatically.** The newest model is the
  most overloaded (see `gemini-flash-latest` above), and newer isn't always better at
  JLPT-level Japanese.
- **Rank by success rate, then latency.** Doesn't count a 25s timeout as worse than an
  instant 503, which is what the user actually feels.
