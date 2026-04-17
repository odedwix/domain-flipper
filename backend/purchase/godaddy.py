"""
GoDaddy Aftermarket API — create a For Sale listing on Afternic/GoDaddy.

Works for domains registered at ANY registrar as long as their nameservers
point to ns1.afternic.com / ns2.afternic.com.

API docs: https://developer.godaddy.com/doc/endpoint/aftermarket
"""

import logging
import httpx
from config import get_settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    s = get_settings()
    if s.godaddy_environment == "production":
        return "https://api.godaddy.com"
    return "https://api.ote-godaddy.com"


def _headers() -> dict:
    s = get_settings()
    return {
        "Authorization": f"sso-key {s.godaddy_api_key}:{s.godaddy_api_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def create_aftermarket_listing(domain: str, price_usd: float) -> dict:
    """
    Create or update a For Sale listing on GoDaddy/Afternic.
    price_usd: asking price in USD (e.g. 500.0)
    Returns {"success": bool, "error": str|None, "listing": dict|None}
    """
    s = get_settings()
    if not s.godaddy_api_key or not s.godaddy_api_secret:
        return {"success": False, "error": "GoDaddy API credentials not configured", "listing": None}

    # GoDaddy aftermarket price is in USD (not cents)
    payload = [
        {
            "domain": domain,
            "price": int(price_usd),
            "fluid": False,
            "forSale": True,
        }
    ]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_base_url()}/v1/aftermarket/listings",
                headers=_headers(),
                json=payload,
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(f"GoDaddy aftermarket listing created for {domain} at ${price_usd:,.0f}")
            return {"success": True, "error": None, "listing": data}

        # Try to extract error message
        try:
            err_data = resp.json()
            msg = err_data.get("message") or err_data.get("error") or resp.text
        except Exception:
            msg = resp.text

        logger.error(f"GoDaddy aftermarket API {resp.status_code} for {domain}: {msg}")
        return {"success": False, "error": f"API {resp.status_code}: {msg}", "listing": None}

    except Exception as e:
        logger.exception(f"GoDaddy aftermarket listing failed for {domain}")
        return {"success": False, "error": str(e), "listing": None}


async def get_aftermarket_listing(domain: str) -> dict:
    """Check if a domain has an active aftermarket listing."""
    s = get_settings()
    if not s.godaddy_api_key or not s.godaddy_api_secret:
        return {"found": False, "error": "GoDaddy API credentials not configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_base_url()}/v1/aftermarket/listings/{domain}",
                headers=_headers(),
            )

        if resp.status_code == 200:
            return {"found": True, "listing": resp.json(), "error": None}
        if resp.status_code == 404:
            return {"found": False, "listing": None, "error": None}

        return {"found": False, "listing": None, "error": f"API {resp.status_code}: {resp.text}"}

    except Exception as e:
        return {"found": False, "listing": None, "error": str(e)}
