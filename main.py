"""Voice-agent backend: GCC bank card offers and credit basics via context.dev."""

import os
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse

load_dotenv()

EXTRACT_URL = "https://api.context.dev/v1/web/extract"
CACHE_TTL_SECONDS = 6 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 20

BANK_URLS: dict[str, str] = {
    "emirates nbd": "https://www.emiratesnbd.com/en/cards/credit-cards/balance-transfer",
    "adcb": "https://www.adcb.com/en/personal/cards/card-features/balance-transfer",
    "rakbank": "https://www.rakbank.ae/en/cards/credit-card-services/balance-transfer",
    "rakbank islamic": "https://www.rakbank.ae/en/islamic/personal/cards/credit-card-services/balance-transfer",
}

BANK_ALIASES: dict[str, str] = {
    "enbd": "emirates nbd",
    "emirates nbd bank": "emirates nbd",
    "abu dhabi commercial bank": "adcb",
    "rak bank": "rakbank",
    "rak": "rakbank",
    "national bank of ras al khaimah": "rakbank",
}

# Banks whose balance transfer terms are only published as PDFs. Extract targets HTML,
# so these are deliberately unsupported rather than silently returning empty values.
KNOWN_UNSUPPORTED = {"fab", "first abu dhabi bank", "mashreq", "dubai islamic bank", "dib"}

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

# Regulator and credit bureau facts per country. `debt_burden_cap` is only populated where
# the figure has been verified against the regulator; None means the agent must not state a
# number. Never fill these in from memory -- verify against source_url first.
CREDIT_BASICS: dict[str, dict[str, Any]] = {
    "uae": {
        "country": "United Arab Emirates",
        "currency": "AED",
        "currency_spoken": "dirhams",
        "credit_bureau": "Al Etihad Credit Bureau",
        "regulator": "Central Bank of the UAE",
        "debt_burden_cap": "50% of income",
        "source_url": "https://www.centralbank.ae/en/",
        "verified_on": "2026-08-08",
    },
    "qatar": {
        "country": "Qatar",
        "currency": "QAR",
        "currency_spoken": "riyals",
        "credit_bureau": "Qatar Credit Bureau",
        "regulator": "Qatar Central Bank",
        "debt_burden_cap": None,
        "source_url": "https://www.qcb.gov.qa/en",
        "verified_on": None,
    },
    "saudi arabia": {
        "country": "Saudi Arabia",
        "currency": "SAR",
        "currency_spoken": "riyals",
        "credit_bureau": "SIMAH",
        "regulator": "SAMA",
        "debt_burden_cap": None,
        "source_url": "https://www.sama.gov.sa/en-US/Pages/default.aspx",
        "verified_on": None,
    },
    "kuwait": {
        "country": "Kuwait",
        "currency": "KWD",
        "currency_spoken": "dinars",
        "credit_bureau": "Ci-Net",
        "regulator": "Central Bank of Kuwait",
        "debt_burden_cap": None,
        "source_url": "https://www.cbk.gov.kw/en",
        "verified_on": None,
    },
    "bahrain": {
        "country": "Bahrain",
        "currency": "BHD",
        "currency_spoken": "dinars",
        "credit_bureau": "BENEFIT Credit Reference Bureau",
        "regulator": "Central Bank of Bahrain",
        "debt_burden_cap": None,
        "source_url": "https://www.cbb.gov.bh/",
        "verified_on": None,
    },
    "oman": {
        "country": "Oman",
        "currency": "OMR",
        "currency_spoken": "rials",
        "credit_bureau": "Mala'a",
        "regulator": "Central Bank of Oman",
        "debt_burden_cap": None,
        "source_url": "https://cbo.gov.om/",
        "verified_on": None,
    },
}

COUNTRY_ALIASES: dict[str, str] = {
    "united arab emirates": "uae",
    "u a e": "uae",
    "dubai": "uae",
    "abu dhabi": "uae",
    "sharjah": "uae",
    "ksa": "saudi arabia",
    "saudi": "saudi arabia",
    "doha": "qatar",
}

app = FastAPI(title="Ren Tools API", version="2.0.0")

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def friendly_error(message: str, status_code: int) -> JSONResponse:
    """Errors are phrased to be read aloud, since the agent speaks them verbatim."""
    return JSONResponse(status_code=status_code, content={"status": "error", "message": message})


def check_auth(provided: str | None) -> JSONResponse | None:
    """Fail closed: without a configured secret the endpoints stay shut, because every
    call costs context.dev credits and the deployment URL is public."""
    expected = os.environ.get("TOOLS_API_KEY")
    if not expected:
        return friendly_error(
            "Sorry, the lookup service isn't configured right now. Let's keep going without it.",
            503,
        )
    if provided != expected:
        return friendly_error(
            "Sorry, I couldn't reach the lookup service just now. Let's keep going without it.",
            401,
        )
    return None


def cache_get(key: str) -> dict[str, Any] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if time.time() >= expires_at:
        _cache.pop(key, None)
        return None
    return payload


def resolve_bank(bank: str) -> str:
    key = normalize(bank)
    return BANK_ALIASES.get(key, key)


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
    return {
        "status": "ok",
        "banks": sorted(BANK_URLS),
        "countries": sorted(CREDIT_BASICS),
    }


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "configured": bool(os.environ.get("CONTEXT_DEV_API_KEY")),
        "auth_configured": bool(os.environ.get("TOOLS_API_KEY")),
        "cached_banks": len(_cache),
    }


@app.get("/credit-basics")
async def credit_basics(
    country: str = Query(..., description="GCC country name"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    denied = check_auth(x_api_key)
    if denied is not None:
        return denied

    key = normalize(country)
    key = COUNTRY_ALIASES.get(key, key)
    basics = CREDIT_BASICS.get(key)
    if basics is None:
        known = ", ".join(sorted(b["country"] for b in CREDIT_BASICS.values()))
        return friendly_error(
            f"Sorry, I don't have credit bureau details for {country}. I can help with: {known}.",
            404,
        )

    payload = {k: v for k, v in basics.items() if v is not None}
    if basics.get("debt_burden_cap") is None:
        payload["debt_burden_note"] = (
            "The debt burden cap for this country has not been verified. "
            "Do not state a percentage. Say the rule exists and move on."
        )
    return {"status": "ok", **payload, "as_of": date.today().isoformat()}


@app.get("/balance-transfer-offers")
async def balance_transfer_offers(
    bank: str = Query(..., description="GCC bank name"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    denied = check_auth(x_api_key)
    if denied is not None:
        return denied

    key = resolve_bank(bank)

    if key in KNOWN_UNSUPPORTED:
        return friendly_error(
            f"{bank} only publishes its balance transfer terms in a PDF, so I can't read you "
            "today's numbers. I'd rather not guess.",
            404,
        )

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
    # Drop blank values so the agent never reads out an empty field.
    offers = {name: data[name] for name in FIELDS if data.get(name)}
    if not offers:
        return friendly_error(
            f"I reached {bank}'s page but couldn't read the balance transfer numbers off it. "
            "I'd rather not guess at them.",
            502,
        )

    payload = {
        "status": "ok",
        "bank": bank,
        "source_url": source_url,
        "offers": offers,
        "as_of": date.today().isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _cache[key] = (time.time() + CACHE_TTL_SECONDS, payload)
    return {**payload, "cached": False}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
