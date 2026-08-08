"""Voice-agent backend: UAE bank balance transfer offers via context.dev extract."""

import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

load_dotenv()

EXTRACT_URL = "https://api.context.dev/v1/web/extract"
CACHE_TTL_SECONDS = 10 * 60
REQUEST_TIMEOUT_SECONDS = 120

BANK_URLS: dict[str, str] = {
    "emirates nbd": "https://www.emiratesnbd.com/en/cards/credit-cards/balance-transfer",
}

FIELDS = [
    "headline_offer",
    "max_repayment_period",
    "minimum_transfer_amount",
    "maximum_transfer_limit",
    "early_settlement_fee",
]

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {name: {"type": "string"} for name in FIELDS},
    "required": FIELDS,
    "additionalProperties": False,
}

INSTRUCTIONS = (
    "Extract the credit card balance transfer offer details exactly as stated on the page. "
    "Keep each value short and natural enough to be read aloud over the phone."
)

app = FastAPI(title="Balance Transfer Offers", version="1.0.0")

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def normalize(bank: str) -> str:
    return " ".join(bank.lower().replace("-", " ").replace("_", " ").split())


def friendly_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "error", "message": message})


def cache_get(key: str) -> dict[str, Any] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if time.time() >= expires_at:
        _cache.pop(key, None)
        return None
    return payload


async def fetch_offers(url: str, api_key: str) -> dict[str, Any]:
    body = {
        "url": url,
        "schema": EXTRACT_SCHEMA,
        "instructions": INSTRUCTIONS,
        "factCheck": True,
        "maxPages": 1,
        "maxDepth": 0,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            EXTRACT_URL,
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    response.raise_for_status()
    return response.json()


@app.get("/")
async def root() -> dict[str, Any]:
    return {"status": "ok", "banks": sorted(BANK_URLS)}


@app.get("/balance-transfer-offers")
async def balance_transfer_offers(bank: str = Query(..., description="UAE bank name")):
    key = normalize(bank)
    source_url = BANK_URLS.get(key)
    if source_url is None:
        known = ", ".join(sorted(BANK_URLS))
        return friendly_error(
            f"Sorry, I don't have balance transfer details for {bank}. I can help with: {known}.",
            404,
        )

    cached = cache_get(key)
    if cached is not None:
        return {**cached, "cached": True}

    api_key = os.environ.get("CONTEXT_DEV_API_KEY")
    if not api_key:
        return friendly_error(
            "Sorry, the offers service isn't configured right now. Please try again later.",
            503,
        )

    try:
        result = await fetch_offers(source_url, api_key)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            return friendly_error(
                "Sorry, I'm being rate limited at the moment. Please try again in a minute.",
                429,
            )
        return friendly_error(
            "Sorry, I couldn't look up the latest balance transfer offers right now. "
            "Please try again shortly.",
            502,
        )
    except httpx.HTTPError:
        return friendly_error(
            "Sorry, the balance transfer offers service is taking too long to respond. "
            "Please try again shortly.",
            504,
        )

    data = result.get("data") or {}
    payload = {
        "status": "ok",
        "bank": bank,
        "source_url": source_url,
        "offers": {name: data.get(name) for name in FIELDS},
    }
    _cache[key] = (time.time() + CACHE_TTL_SECONDS, payload)
    return {**payload, "cached": False}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
