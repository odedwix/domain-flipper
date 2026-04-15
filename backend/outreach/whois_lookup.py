"""
WHOIS lookup to find original domain owner contact info.
Uses python-whois first, falls back to WhoisXML API for edge cases.
"""

import logging
import httpx
import whois
from typing import Optional
from config import get_settings

logger = logging.getLogger(__name__)


def _extract_from_whois(w) -> dict:
    """Extract owner info from python-whois result object."""
    def first(val):
        if isinstance(val, list):
            return val[0] if val else None
        return val

    emails = w.emails
    if isinstance(emails, str):
        emails = [emails]
    elif not emails:
        emails = []

    # Filter out privacy-proxy generic emails... but still keep them as fallback
    real_emails = [e for e in emails if e and "example.com" not in e]

    return {
        "registrant_name": first(w.name) or first(w.org),
        "registrant_email": first(real_emails) or first(emails),
        "registrar": first(w.registrar),
        "creation_date": str(first(w.creation_date)) if w.creation_date else None,
        "expiration_date": str(first(w.expiration_date)) if w.expiration_date else None,
        "all_emails": real_emails,
    }


async def lookup_whois(domain: str) -> dict:
    """
    Perform WHOIS lookup. Returns dict with owner info.
    Falls back to WhoisXML API if python-whois fails.
    """
    # Try python-whois (synchronous, run in thread)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        w = await loop.run_in_executor(None, whois.whois, domain)
        result = _extract_from_whois(w)
        result["source"] = "python-whois"
        result["domain"] = domain
        return result
    except Exception as e:
        logger.info(f"python-whois failed for {domain}: {e}. Trying WhoisXML API.")

    # Fallback: WhoisXML API
    settings = get_settings()
    if settings.whoisxml_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://www.whoisxmlapi.com/whoisserver/WhoisService",
                    params={
                        "apiKey": settings.whoisxml_api_key,
                        "domainName": domain,
                        "outputFormat": "JSON",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                rr = data.get("WhoisRecord", {})
                contact = rr.get("registrant", {})
                return {
                    "domain": domain,
                    "registrant_name": contact.get("name") or contact.get("organization"),
                    "registrant_email": contact.get("email"),
                    "registrar": rr.get("registrarName"),
                    "creation_date": rr.get("createdDate"),
                    "expiration_date": rr.get("expiresDate"),
                    "all_emails": [contact.get("email")] if contact.get("email") else [],
                    "source": "whoisxml",
                }
        except Exception as e:
            logger.error(f"WhoisXML API failed for {domain}: {e}")

    return {
        "domain": domain,
        "registrant_name": None,
        "registrant_email": None,
        "registrar": None,
        "creation_date": None,
        "expiration_date": None,
        "all_emails": [],
        "source": "failed",
    }
