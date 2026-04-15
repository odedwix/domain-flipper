"""
Namecheap XML API wrapper for domain availability check and registration.

Setup:
  1. Log into namecheap.com → Profile → Tools → Namecheap API
  2. Enable API access, whitelist your IP
  3. For sandbox testing: sandbox.namecheap.com (separate account)
  4. Set NAMECHEAP_SANDBOX=true in .env until you are ready to spend real money
"""

import logging
import xml.etree.ElementTree as ET
import httpx
from config import get_settings
from typing import Optional

logger = logging.getLogger(__name__)

NC_NS = "http://api.namecheap.com/xml.response"


def _get_url() -> str:
    settings = get_settings()
    if settings.namecheap_sandbox:
        return "https://api.sandbox.namecheap.com/xml.response"
    return "https://api.namecheap.com/xml.response"


def _base_params() -> dict:
    s = get_settings()
    return {
        "ApiUser": s.namecheap_api_user,
        "ApiKey": s.namecheap_api_key,
        "UserName": s.namecheap_api_user,
        "ClientIp": s.namecheap_client_ip,
    }


def _check_errors(root: ET.Element) -> Optional[str]:
    """Return error message string if API returned errors, else None."""
    errors = root.find(f"{{{NC_NS}}}Errors")
    if errors is not None:
        msgs = [e.text for e in errors if e.text]
        if msgs:
            return " | ".join(msgs)
    status = root.get("Status", "")
    if status == "ERROR":
        return "API returned ERROR status"
    return None


async def check_availability(domain: str) -> dict:
    """
    Check if a domain is available for registration.
    Returns {"available": bool, "premium": bool, "price": float|None, "error": str|None}
    """
    settings = get_settings()
    if not settings.namecheap_api_key:
        return {
            "available": None,
            "premium": False,
            "price": None,
            "error": "Namecheap API not configured (set NAMECHEAP_API_KEY in .env)",
        }

    params = _base_params()
    params["Command"] = "namecheap.domains.check"
    params["DomainList"] = domain

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_get_url(), params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        err = _check_errors(root)
        if err:
            return {"available": None, "premium": False, "price": None, "error": err}

        command_response = root.find(f".//{{{NC_NS}}}CommandResponse")
        result = root.find(f".//{{{NC_NS}}}DomainCheckResult")
        if result is None:
            return {"available": None, "premium": False, "price": None, "error": "No result in response"}

        available = result.get("Available", "false").lower() == "true"
        is_premium = result.get("IsPremiumName", "false").lower() == "true"
        price_str = result.get("PremiumRegistrationPrice", None)
        price = float(price_str) if price_str else None

        return {"available": available, "premium": is_premium, "price": price, "error": None}

    except Exception as e:
        logger.exception(f"Error checking availability for {domain}")
        return {"available": None, "premium": False, "price": None, "error": str(e)}


async def register_domain(domain: str, years: int = 1) -> dict:
    """
    Register a domain via Namecheap API.
    WARNING: This spends real money when NAMECHEAP_SANDBOX=false.
    Returns {"success": bool, "order_id": str|None, "error": str|None}
    """
    settings = get_settings()
    if not settings.namecheap_api_key:
        return {"success": False, "order_id": None, "error": "Namecheap API not configured"}

    # Build contact info (same for all 4 required contact types)
    contact = {
        "FirstName": settings.namecheap_reg_first_name,
        "LastName": settings.namecheap_reg_last_name,
        "Address1": settings.namecheap_reg_address,
        "City": settings.namecheap_reg_city,
        "StateProvince": settings.namecheap_reg_state,
        "PostalCode": settings.namecheap_reg_postal,
        "Country": settings.namecheap_reg_country,
        "Phone": settings.namecheap_reg_phone,
        "EmailAddress": settings.namecheap_reg_email,
    }

    params = _base_params()
    params["Command"] = "namecheap.domains.create"
    params["DomainName"] = domain
    params["Years"] = str(years)
    params["AddFreeWhoisguard"] = "yes"
    params["WGEnabled"] = "yes"

    # Apply contact info for all 4 contact types
    for prefix in ["AuxBilling", "Tech", "Admin", "Registrant"]:
        for key, val in contact.items():
            params[f"{prefix}{key}"] = val

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_get_url(), data=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        err = _check_errors(root)
        if err:
            return {"success": False, "order_id": None, "error": err}

        result = root.find(f".//{{{NC_NS}}}DomainCreateResult")
        if result is None:
            return {"success": False, "order_id": None, "error": "No result in response"}

        registered = result.get("Registered", "false").lower() == "true"
        order_id = result.get("OrderID", None)

        if registered:
            mode = "SANDBOX" if settings.namecheap_sandbox else "PRODUCTION"
            logger.info(f"[{mode}] Domain registered: {domain} (order {order_id})")
            return {"success": True, "order_id": order_id, "error": None}
        else:
            return {"success": False, "order_id": None, "error": "Registration failed (not registered)"}

    except Exception as e:
        logger.exception(f"Error registering {domain}")
        return {"success": False, "order_id": None, "error": str(e)}


async def get_domain_list() -> list[dict]:
    """List all domains in the Namecheap account."""
    settings = get_settings()
    if not settings.namecheap_api_key:
        return []

    params = _base_params()
    params["Command"] = "namecheap.domains.getList"
    params["PageSize"] = "100"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_get_url(), params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        err = _check_errors(root)
        if err:
            logger.error(f"getList error: {err}")
            return []

        domains = []
        for d in root.findall(f".//{{{NC_NS}}}Domain"):
            domains.append({
                "name": d.get("Name"),
                "expires": d.get("Expires"),
                "is_expired": d.get("IsExpired"),
                "auto_renew": d.get("AutoRenew"),
            })
        return domains

    except Exception as e:
        logger.exception("Error fetching domain list")
        return []
