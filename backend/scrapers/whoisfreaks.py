"""
WhoisFreaks Expired Domains API — real API, 10,000 free domains/month.

Get your free API key at: https://whoisfreaks.com/
Free tier: 10k expired domains/month, 100 cleaned domains/month.

This is a proper API (JSON, no scraping) and gives better data
than scraping expireddomains.net — includes registrar, age, and
proper expiry dates.
"""

import logging
import httpx
from config import get_settings

logger = logging.getLogger(__name__)

BASE = "https://api.whoisfreaks.com/v1"


async def fetch_whoisfreaks_domains(page: int = 1, page_size: int = 100) -> list[dict]:
    """
    Fetch expiring/dropped domains from WhoisFreaks API.
    Returns list of domain dicts compatible with our scoring pipeline.
    """
    settings = get_settings()
    api_key = getattr(settings, "whoisfreaks_api_key", "")

    if not api_key:
        logger.warning("WHOISFREAKS_API_KEY not set — skipping WhoisFreaks source")
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{BASE}/domains/expiring",
                params={
                    "apiKey": api_key,
                    "pageNo": page,
                    "pageSize": min(page_size, 100),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        raw = data.get("domains", []) or data.get("data", []) or []
        domains = []

        for item in raw:
            name = (item.get("domainName") or item.get("domain_name") or "").lower().strip()
            if not name or "." not in name:
                continue

            # Parse age from creation date
            created = item.get("createDate") or item.get("created_date") or ""
            age_years = None
            if created:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(created[:10], "%Y-%m-%d")
                    age_years = round((datetime.utcnow() - dt).days / 365.25, 1)
                except Exception:
                    pass

            domains.append({
                "name": name,
                "backlink_count": None,        # enriched later via Open PageRank
                "domain_age_years": age_years,
                "source": "whoisfreaks",
                "registrar": item.get("registrar"),
                "expiry_date": item.get("expiryDate") or item.get("expiry_date"),
            })

        logger.info(f"WhoisFreaks page {page}: {len(domains)} domains")
        return domains

    except Exception as e:
        logger.error(f"WhoisFreaks fetch failed: {e}")
        return []


async def fetch_all_whoisfreaks(max_pages: int = 5) -> list[dict]:
    """Fetch multiple pages from WhoisFreaks."""
    import asyncio
    all_domains = []
    for page in range(1, max_pages + 1):
        batch = await fetch_whoisfreaks_domains(page=page)
        if not batch:
            break
        all_domains.extend(batch)
        await asyncio.sleep(0.8)  # stay within rate limits
    return all_domains
