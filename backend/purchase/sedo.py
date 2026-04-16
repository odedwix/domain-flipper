"""
Sedo marketplace API integration.

Setup:
  1. Create account at sedo.com
  2. Go to Account → API Access → request API credentials
  3. Add SEDO_PARTNER_ID and SEDO_SIGN_KEY to .env

Sedo distributes to their own buyer network (~18M domains listed).
Combined with Afternic, you cover the two largest domain marketplaces.
"""

import hashlib
import logging
import httpx
from config import get_settings

logger = logging.getLogger(__name__)

SEDO_API = "https://api.sedo.com/api/v1/"


def _sign(partner_id: str, sign_key: str, action: str) -> str:
    raw = f"{partner_id}{sign_key}{action}"
    return hashlib.md5(raw.encode()).hexdigest()


async def list_on_sedo(domain: str, asking_price: float, currency: str = "USD") -> dict:
    """
    List a domain for sale on Sedo.
    Returns {"success": bool, "listing_id": str|None, "error": str|None}
    """
    settings = get_settings()
    partner_id = getattr(settings, "sedo_partner_id", "")
    sign_key = getattr(settings, "sedo_sign_key", "")
    username = getattr(settings, "sedo_username", "")
    password = getattr(settings, "sedo_password", "")

    if not partner_id or not sign_key:
        return {
            "success": False,
            "listing_id": None,
            "error": "Sedo not configured (set SEDO_PARTNER_ID and SEDO_SIGN_KEY in .env)",
        }

    action = "domainlist"
    sign = _sign(partner_id, sign_key, action)

    payload = {
        "partnerid": partner_id,
        "sign": sign,
        "username": username,
        "password": hashlib.md5(password.encode()).hexdigest(),
        "action": action,
        "domainname": domain,
        "price": str(int(asking_price)),
        "currency": currency,
        "minimumprice": str(int(asking_price * 0.6)),  # accept 60% of asking
        "type": "buynow",                               # fixed price + offers
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(SEDO_API, data=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("domainid"):
            logger.info(f"Listed {domain} on Sedo for ${asking_price:,.0f} (id={data['domainid']})")
            return {"success": True, "listing_id": str(data["domainid"]), "error": None}
        else:
            err = data.get("error", {}).get("msg", "Unknown Sedo error")
            return {"success": False, "listing_id": None, "error": err}

    except Exception as e:
        logger.exception(f"Sedo listing failed for {domain}")
        return {"success": False, "listing_id": None, "error": str(e)}
