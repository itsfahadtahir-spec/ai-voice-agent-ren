# Ren — a voice financial wellness coach for the GCC

AI Voice Agent Hackathon, Team 22.

Ren is a voice-first financial coach for young professionals in the Gulf carrying credit card debt.
It runs an hour-long coaching session — check in, set an agenda, work a positive-psychology
technique, build a plan with real numbers, then close by showing the person how far they moved.

When the conversation reaches a real product question ("should I move my balance to ADCB?"), Ren
fetches **today's actual offer** from that bank's website through [context.dev](https://docs.context.dev)
and reads it back with the date attached. When it can't get a number, it says so instead of guessing.

This repository is the **backend**: the tool API the voice agent calls, plus the system prompt that
defines the agent. There is no frontend — the demo runs on the ElevenLabs widget. See
[TECH-SPEC.md](TECH-SPEC.md) for the engineering reasoning.

## What it does

- **Live balance transfer lookups** for 6 GCC banks, extracted from the bank's own page at call time
- **Credit bureau and regulator facts** for all 6 GCC countries
- **Refuses to guess.** Banks whose terms are PDF-only, and debt burden caps that haven't been
  verified, return an explicit refusal. The agent is instructed to admit the gap and keep coaching.
- **Sharia-aware.** RAKBANK's Islamic page extracts as "0% *profit rate*", and the prompt switches
  vocabulary to match.
- **Voice-shaped responses.** Values are kept short enough to read aloud, blank and placeholder
  values are stripped so nothing empty is spoken, and every response carries `as_of`.

## Architecture

```
Browser (ElevenLabs widget)  --WebRTC-->  ElevenLabs Agent "Ren"
                                                |
                                                |  webhook tool + X-API-Key
                                                v
                                        FastAPI  (main.py)
                                                |
                                                |  POST /v1/web/extract
                                                v
                                        context.dev  -->  bank's live page
```

ElevenLabs runs speech, turn-taking and the LLM. Two webhook tools point at this FastAPI service,
which resolves the bank name, checks a 6-hour cache, and on a miss calls context.dev Extract with a
five-field JSON Schema. Because a cold lookup takes 1–10 seconds, the agent is configured to speak
while the request is in flight (`pre_tool_speech: force`) with a 3-second filler behind it.

The system prompt lives at [`prompts/ren-system-prompt.md`](prompts/ren-system-prompt.md) and is the
source of truth for Ren's behaviour.

## Setup

Assumes a clean machine. Requires **Python 3.10+** (the code uses `X | None`); 3.11 matches `.replit`.

```bash
git clone https://github.com/itsfahadtahir-spec/ai-voice-agent-ren
cd ai-voice-agent-ren

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in the values below
uvicorn main:app --reload
```

Interactive API docs: <http://localhost:8000/docs>

### Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `CONTEXT_DEV_API_KEY` | yes | context.dev API key. Starts `ctxt_secret_`. Get one at [context.dev](https://context.dev/dashboard). |
| `TOOLS_API_KEY` | yes | Shared secret the agent sends as `X-API-Key`. Generate with the command below. |
| `ELEVENLABS_API_KEY` | for `/session-token` | ElevenLabs key. Starts `sk_`. Shown **only once**, when the key is created. |
| `ELEVENLABS_AGENT_ID` | for `/session-token` | The agent id, e.g. `agent_5601kzg...` |
| `ALLOWED_ORIGINS` | no | Comma-separated CORS allowlist. Defaults to `http://localhost:5173`. |
| `CACHE_FILE` | no | Cache path. Defaults to `/tmp/ren_offers_cache.json`. |
| `PORT` | no | Defaults to 8000. |

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # TOOLS_API_KEY
```

`.env` is gitignored. `TOOLS_API_KEY` **fails closed** — if it isn't set, the tool endpoints return
503 rather than serving traffic, because every Extract call spends 10 context.dev credits and a
deployed URL is public.

## Endpoints

Tool endpoints require `X-API-Key`.

```bash
curl -H "X-API-Key: $TOOLS_API_KEY" \
  "http://localhost:8000/balance-transfer-offers?bank=ADCB"
```

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
  "fetched_at": "2026-08-08T09:41:11+00:00",
  "cached": false
}
```

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /balance-transfer-offers?bank=` | `X-API-Key` | Live balance transfer offer for a bank |
| `GET /credit-basics?country=` | `X-API-Key` | Bureau, regulator, currency, debt burden cap |
| `GET /session-token` | none (CORS) | Short-lived ElevenLabs token so a browser can start a call |
| `GET /` | none | Supported banks and countries |
| `GET /healthz` | none | Whether keys are configured, cache size |

## Coverage

| Bank | Country | Status |
| --- | --- | --- |
| Emirates NBD | UAE | supported |
| ADCB | UAE | supported |
| RAKBANK | UAE | supported |
| RAKBANK Islamic | UAE | supported — returns "profit rate" wording |
| Doha Bank | Qatar | supported |
| Arab Bank Qatar | Qatar | supported |
| FAB, Mashreq, Dubai Islamic Bank | UAE | refused — terms are PDF-only |
| Al Rajhi, SNB, Riyad Bank | Saudi | refused — no scrapable page |
| NBK, Gulf Bank, BBK, AUB, Bank Muscat, NBO | KW/BH/OM | refused — no scrapable page |

Every supported URL was confirmed against a live Extract call before being committed. The refusals
are deliberate: extracting from PDF terms produced mis-mapped figures (Al Rajhi yielded a repayment
period of "164 months", FAB "55 days"), and an agent stating those aloud is worse than one admitting
it doesn't know. `credit-basics` still covers all six countries.

## Connecting the agent

The agent needs a **public HTTPS URL** — ElevenLabs calls the webhook from its own servers, so
`localhost` is unreachable. Either deploy (below) or tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Then register two webhook tools on the agent pointing at `/balance-transfer-offers` and
`/credit-basics`, each with an `X-API-Key` header set to `TOOLS_API_KEY`. Set
`execution_mode: immediate` and `pre_tool_speech: force` so the agent talks while the fetch runs.

## Deploying on Replit

1. Import this repo into Replit.
2. Tools → Secrets: add `CONTEXT_DEV_API_KEY`, `TOOLS_API_KEY`, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_AGENT_ID`.
3. Run. `.replit` starts `uvicorn main:app --host 0.0.0.0 --port $PORT`.

**Caching caveat:** the cache is a disk-backed dict. On `autoscale` it is per-instance and lost on
cold start, so credit spend will be higher than the 6-hour TTL suggests. Redis is the fix.

## Adding a bank

1. Confirm the bank publishes balance transfer terms as **HTML**, not PDF.
2. Add the URL to `BANK_URLS` in `main.py`, keyed lowercase.
3. Run a live Extract against it and check at least three of the five fields come back real — not
   `"null"`, not `"not mentioned"`. A URL that loads is not a URL that yields data.

## Known issues

- No frontend. The demo runs on the ElevenLabs widget, which shows a chat-style surface rather than
  a call screen.
- No cross-session memory, so Ren cannot recall a previous session's commitment.
- Debt burden caps are only verified for the UAE. The other five countries deliberately return no
  percentage.
- `/session-token` is not behind user auth. CORS limits which pages call it, but not direct requests.
- Agent is English-only (`eleven_flash_v2`), so Arabic bank names lean on an English model's
  pronunciation.
