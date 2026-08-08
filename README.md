# ai-voice-agent-ren

AI Voice Agent Hackathon, Team 22.

FastAPI backend serving the tools for **Ren**, a financial wellness voice coach for the GCC.
Balance transfer offers are extracted live from each bank's page with the
[context.dev](https://docs.context.dev) Extract API. Responses are shaped so a voice agent can
read them aloud.

## Endpoints

All tool endpoints require an `X-API-Key` header matching `TOOLS_API_KEY`.

### `GET /balance-transfer-offers?bank=ADCB`

```json
{
  "status": "ok",
  "bank": "ADCB",
  "source_url": "https://www.adcb.com/en/personal/cards/card-features/balance-transfer",
  "offers": {
    "headline_offer": "Transfer up to 80% of your ADCB credit card limit",
    "max_repayment_period": "48 months",
    "minimum_transfer_amount": "1000",
    "maximum_transfer_limit": "80% of ADCB credit card limit",
    "early_settlement_fee": "210"
  },
  "as_of": "2026-08-08",
  "fetched_at": "2026-08-08T09:20:52+00:00",
  "cached": false
}
```

Blank values are omitted so the agent never reads out an empty field. `as_of` exists so the
agent can honestly say "as of today" rather than implying freshness it can't prove.

### `GET /credit-basics?country=UAE`

Returns the credit bureau, regulator, currency, and debt burden cap for a GCC country.

Where a debt burden cap has **not** been verified against the regulator, the field is omitted
and replaced with `debt_burden_note` instructing the agent not to state a percentage. Only the
UAE figure is currently verified — see [Verifying credit basics](#verifying-credit-basics).

### `GET /` and `GET /healthz`

Public. `/` lists supported banks and countries; `/healthz` reports whether the keys are
configured and how many banks are cached.

## Coverage

| Bank | Status |
| --- | --- |
| Emirates NBD | supported |
| ADCB | supported |
| RAKBANK | supported |
| RAKBANK Islamic | supported (returns "profit rate" wording) |
| FAB, Mashreq, Dubai Islamic Bank | **unsupported** — terms are PDF-only |

Bank names are matched case-insensitively, with aliases (`enbd`, `rak`, `Abu Dhabi Commercial
Bank`, …). Banks that only publish balance transfer terms as PDFs return an explicit refusal
rather than empty values, because a coach guessing at financial figures is worse than a coach
admitting it doesn't know. Supporting them means switching to context.dev Parse Bytes.

## Caching

Results are cached in memory for 6 hours per bank to conserve context.dev credits (Extract
costs 10 credits per call).

**Known limitation:** the cache is a process-local dict. On Replit `autoscale` it is lost on
cold start and not shared between instances, so real-world hit rates will be lower than the
TTL suggests. Moving to Redis or a small persistent store is the fix if credit spend matters.

## Latency

Cold extracts have measured between 1s and 10s depending on the bank. That is too slow to sit
in silence during a call, so the agent is configured with `pre_tool_speech` and a 3 second soft
timeout to speak while the tool runs. `REQUEST_TIMEOUT_SECONDS` is 20 so a hung upstream fails
fast instead of stalling a live conversation.

## Setup

Requires **Python 3.10+** (the code uses `X | None` syntax). 3.11 matches `.replit`.

```bash
uv venv --python 3.11 .venv        # or: python3.11 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env               # then put your real keys in .env
./.venv/bin/uvicorn main:app --reload
```

Open http://localhost:8000/docs for the interactive API docs.

## Configuration

| Variable | Description |
| --- | --- |
| `CONTEXT_DEV_API_KEY` | context.dev API key (required) |
| `TOOLS_API_KEY` | Shared secret the voice agent sends as `X-API-Key` (required) |
| `PORT` | Port to listen on (defaults to 8000) |

`.env` is gitignored — never commit a real key.

`TOOLS_API_KEY` **fails closed**: if it isn't set, the tool endpoints return 503 rather than
serving traffic. The deployment URL is public and every call spends credits, so an unprotected
endpoint is a standing invitation to drain the account.

Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Adding a bank

Verify the bank publishes its balance transfer terms as **HTML** (not PDF), then add an entry
to `BANK_URLS` in `main.py`, keyed by the lowercase bank name:

```python
BANK_URLS = {
    "adcb": "https://www.adcb.com/en/personal/cards/card-features/balance-transfer",
}
```

Test the extract before committing it — a URL that loads is not the same as a URL that yields
usable fields.

## Verifying credit basics

`CREDIT_BASICS` in `main.py` carries `debt_burden_cap` and `verified_on` per country. Do not
populate a cap from memory. Confirm it against the regulator's own published rule, then set
both fields together. Unverified caps must stay `None` so the agent stays silent on the number.

## Deploying on Replit

1. Import this repo into Replit.
2. Add `CONTEXT_DEV_API_KEY` and `TOOLS_API_KEY` under Tools → Secrets (not in a committed file).
3. Run — `.replit` starts `uvicorn main:app --host 0.0.0.0 --port $PORT` and Replit exposes it.
