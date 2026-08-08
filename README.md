# ai-voice-agent-ren

AI Voice Agent Hackathon, Team 22.

FastAPI backend that returns UAE credit card balance transfer offers, extracted live from
each bank's page with the [context.dev](https://docs.context.dev) Extract API. Responses are
shaped so a voice agent can read them aloud.

## Endpoint

```
GET /balance-transfer-offers?bank=Emirates%20NBD
```

Response:

```json
{
  "status": "ok",
  "bank": "Emirates NBD",
  "source_url": "https://www.emiratesnbd.com/en/cards/credit-cards/balance-transfer",
  "offers": {
    "headline_offer": "...",
    "max_repayment_period": "...",
    "minimum_transfer_amount": "...",
    "maximum_transfer_limit": "...",
    "early_settlement_fee": "..."
  },
  "cached": false
}
```

Bank names are matched case-insensitively. Unknown banks and upstream failures return
`{"status": "error", "message": "..."}` with a message written to be spoken aloud.

Results are cached in memory for 10 minutes per bank to conserve context.dev credits.

`GET /` lists the supported banks.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your real key in .env
uvicorn main:app --reload
```

Open http://localhost:8000/docs for the interactive API docs.

## Configuration

| Variable | Description |
| --- | --- |
| `CONTEXT_DEV_API_KEY` | context.dev API key (required) |
| `PORT` | Port to listen on (defaults to 8000) |

`.env` is gitignored — never commit a real key.

## Adding a bank

Add an entry to `BANK_URLS` in `main.py`, keyed by the lowercase bank name:

```python
BANK_URLS = {
    "emirates nbd": "https://www.emiratesnbd.com/en/cards/credit-cards/balance-transfer",
    "adcb": "https://www.adcb.com/...",
}
```

## Deploying on Replit

1. Import this repo into Replit.
2. Add `CONTEXT_DEV_API_KEY` under Tools → Secrets (not in a committed file).
3. Run — `.replit` starts `uvicorn main:app --host 0.0.0.0 --port $PORT` and Replit exposes it.
