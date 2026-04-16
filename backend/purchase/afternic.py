"""
Afternic auto-listing via Namecheap nameserver update.

After purchasing a domain, point its nameservers to Afternic.
This creates a "For Sale" landing page and distributes the domain
to GoDaddy, Network Solutions, and 100+ partner registrars automatically.

No Afternic API key needed — just a free Afternic account.
The nameserver trick works immediately after domain registration.
"""

import logging
import xml.etree.ElementTree as ET
import httpx
from config import get_settings

logger = logging.getLogger(__name__)

# Afternic's nameservers — pointing to these = listed for sale
AFTERNIC_NS = ["ns1.afternic.com", "ns2.afternic.com"]

NC_NS = "http://api.namecheap.com/xml.response"


def _get_url() -> str:
    s = get_settings()
    if s.namecheap_sandbox:
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


async def list_on_afternic(domain: str, asking_price: float) -> dict:
    """
    Point domain nameservers to Afternic to auto-list for sale.
    The asking_price is stored in our DB — you set the price in your
    Afternic dashboard (afternic.com) once, and it applies to all domains.

    Returns {"success": bool, "nameservers": list, "error": str|None}
    """
    settings = get_settings()
    if not settings.namecheap_api_key:
        return {
            "success": False,
            "nameservers": AFTERNIC_NS,
            "error": "Namecheap API not configured",
        }

    # Split domain into SLD and TLD for Namecheap API
    parts = domain.rsplit(".", 1)
    if len(parts) != 2:
        return {"success": False, "nameservers": [], "error": f"Invalid domain: {domain}"}

    sld, tld = parts[0], parts[1]

    params = _base_params()
    params["Command"] = "namecheap.domains.dns.setCustom"
    params["SLD"] = sld
    params["TLD"] = tld
    params["Nameservers"] = ",".join(AFTERNIC_NS)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(_get_url(), data=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)

        # Check for errors
        errors = root.find(f"{{{NC_NS}}}Errors")
        if errors is not None:
            msgs = [e.text for e in errors if e.text]
            if msgs:
                return {"success": False, "nameservers": AFTERNIC_NS, "error": " | ".join(msgs)}

        result = root.find(f".//{{{NC_NS}}}DomainDNSSetCustomResult")
        if result is not None:
            updated = result.get("Updated", "false").lower() == "true"
            if updated:
                logger.info(f"Afternic nameservers set for {domain} — listed for ${asking_price:,.0f}")
                return {"success": True, "nameservers": AFTERNIC_NS, "error": None}

        return {"success": False, "nameservers": AFTERNIC_NS, "error": "Nameserver update did not confirm"}

    except Exception as e:
        logger.exception(f"Error setting Afternic nameservers for {domain}")
        return {"success": False, "nameservers": AFTERNIC_NS, "error": str(e)}


async def get_current_nameservers(domain: str) -> list[str]:
    """Get current nameservers for a domain."""
    parts = domain.rsplit(".", 1)
    if len(parts) != 2:
        return []
    sld, tld = parts[0], parts[1]

    params = _base_params()
    params["Command"] = "namecheap.domains.dns.getList"
    params["SLD"] = sld
    params["TLD"] = tld

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_get_url(), params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns_list = []
        for ns in root.findall(f".//{{{NC_NS}}}Nameserver"):
            if ns.text:
                ns_list.append(ns.text.strip())
        return ns_list
    except Exception as e:
        logger.error(f"Error getting nameservers for {domain}: {e}")
        return []
