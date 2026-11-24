# 0002: A SQLite call log for Gemini requests

- **Status:** Accepted, implemented 2026-11-24
- **Area:** `gemini_client.py`, `db.py`, `migrations/`

## Context

Gemini's free tier allows about **20 requests a day per model** for the Flash models.
One mined card can use 3 to 6 requests (analysis, persona sentence and its retries,
mnemonic), so a study session runs into the limit. On top of that, the popular models are
often overloaded and answer 503 after 15 to 60 seconds.

The app already falls back across models and remembers cooldowns. But it had no record
of what it had used, so it couldn't:

- tell how close each model is to its daily limit;
- route around a model before Google refuses it;
- report latency, failures and token use per model;
- keep cooldowns in anything better than an ad-hoc JSON file.

## Decision

Keep a local SQLite database, `leech_doctor.db`, accessed with SQLAlchemy 2.0 and
versioned with Alembic.

| Table | One row per | Used for |
|---|---|---|
| `gemini_calls` | request to one model | quota used today, latency, failures, tokens |
| `model_cooldowns` | model to avoid | skipping overloaded or out-of-quota models across restarts |
| `model_quotas` | model | the daily limit Google reports in a 429 (`quotaValue`) |

How the client uses it:

- Every attempt is logged, including failed ones, with its task (`mnemonic`, `sentence`,
  ...), outcome, HTTP status, latency and token counts. Logging failures never break a call.
- "Used today" counts HTTP 200 replies since midnight Pacific, when Google resets daily quotas.
- A model at its learned limit is **tried last, not skipped**. The count is an estimate:
  the same key may be used elsewhere, and limits change when a plan is upgraded. Google's
  own 429 remains the source of truth and puts the model in a hard cooldown.
- `GET /api/gemini/usage` and **Settings → Gemini Usage Today** show the result.

## Why SQLite, SQLAlchemy and Alembic

- **SQLite:** one local user, one process, small append-heavy data queried by time range.
  It ships with Python, needs no server, and WAL mode lets the usage page read while a call
  is being logged.
- **SQLAlchemy 2.0:** typed models (`Mapped[...]`), a `UTCDateTime` type that stores UTC
  and rejects naive datetimes, and queries that are easy to test.
- **Alembic:** the schema will grow (per-card generation history is a likely next table).
  Migrations run automatically on startup, `render_as_batch` handles SQLite's limited
  `ALTER TABLE`, and a test fails if a model changes without a migration.

## Alternatives considered

- **More JSON files.** Fine for one cooldown map, poor for "requests per model since
  midnight Pacific", and every writer has to handle atomic replacement itself.
- **The numpy store from [0001](0001-numpy-vector-index.md).** Built for fixed-size vectors
  read all at once, not for appending rows and querying by time.
- **No local tracking, rely on 429s only.** Simple, but every exhausted model costs a
  request before the app learns about it, and there is nothing to show the user.

## Trade-offs

- Two new dependencies (SQLAlchemy, Alembic, about 10 MB together).
- The log grows by a few hundred rows a day. That is negligible, but a retention policy
  (e.g. keep 90 days) is an easy follow-up if it ever matters.
