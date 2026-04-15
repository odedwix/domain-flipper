"""
Scraper for expireddomains.net — the free public list of dropped .com domains.

How to get your session cookie:
  1. Go to https://www.expireddomains.net and log in (or register free)
  2. Open DevTools → Application → Cookies
  3. Copy the value of the "ef_session" cookie
  4. Paste it into your .env as EXPIREDDOMAINS_SESSION_COOKIE
"""

import asyncio
import logging
import re
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, date
from typing import Optional
from config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.expireddomains.net"
LIST_URL = f"{BASE_URL}/deleted-com-domains/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": BASE_URL,
}


def _parse_age(birth_str: str) -> Optional[float]:
    """Parse domain age from birth date string like '2012-03-15'."""
    if not birth_str or birth_str.strip() in ("-", ""):
        return None
    try:
        birth = datetime.strptime(birth_str.strip(), "%Y-%m-%d").date()
        years = (date.today() - birth).days / 365.25
        return round(years, 1)
    except Exception:
        return None


def _parse_int(val: str) -> Optional[int]:
    val = val.strip().replace(",", "")
    if not val or val == "-":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_table(html: str) -> list[dict]:
    """Parse the HTML table on expireddomains.net and return list of domain dicts."""
    soup = BeautifulSoup(html, "lxml")
    results = []

    table = soup.find("table", class_="base1")
    if not table:
        # Try alternate selector
        table = soup.find("table", {"id": re.compile(r"table_")})
    if not table:
        return results

    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        # Column 0: domain name (contains an <a> tag)
        domain_td = cols[0]
        a_tag = domain_td.find("a")
        if not a_tag:
            continue
        domain_name = a_tag.text.strip().lower()
        if not domain_name or "." not in domain_name:
            continue

        # Column 1 or 2: backlink count — varies by list type
        # Try to extract a number from columns 1–3
        bl = None
        for i in range(1, min(5, len(cols))):
            bl = _parse_int(cols[i].text)
            if bl is not None:
                break

        # Birth date — look for date-like pattern in any col
        age_years = None
        birth_str = None
        for col in cols:
            text = col.text.strip()
            if re.match(r"\d{4}-\d{2}-\d{2}", text):
                birth_str = text
                age_years = _parse_age(text)
                break

        results.append({
            "name": domain_name,
            "backlink_count": bl,
            "domain_age_years": age_years,
            "source": "expireddomains",
        })

    return results


async def fetch_expired_domains(max_pages: int = 5) -> list[dict]:
    """
    Fetch up to max_pages of dropped .com domains from expireddomains.net.
    Returns a list of domain dicts ready for scoring.
    """
    settings = get_settings()
    session_cookie = settings.expireddomains_session_cookie

    if not session_cookie:
        logger.warning(
            "EXPIREDDOMAINS_SESSION_COOKIE not set — using unauthenticated scrape "
            "(may return limited or no results)."
        )

    cookies = {}
    if session_cookie:
        cookies["ef_session"] = session_cookie

    all_domains: list[dict] = []

    async with httpx.AsyncClient(
        headers=HEADERS,
        cookies=cookies,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        for page in range(max_pages):
            start = page * 25
            url = f"{LIST_URL}?start={start}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                parsed = _parse_table(resp.text)
                if not parsed:
                    logger.info(f"No more results at page {page + 1}, stopping.")
                    break
                all_domains.extend(parsed)
                logger.info(f"Page {page + 1}: got {len(parsed)} domains (total {len(all_domains)})")
                # Be polite to the server
                await asyncio.sleep(2.5)
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} fetching {url}")
                if e.response.status_code == 403:
                    logger.error(
                        "Access denied. Your session cookie may be expired. "
                        "Please refresh it in EXPIREDDOMAINS_SESSION_COOKIE."
                    )
                break
            except Exception as e:
                logger.error(f"Error fetching page {page + 1}: {e}")
                break

    logger.info(f"Total domains fetched: {len(all_domains)}")
    return all_domains


async def fetch_demo_domains() -> list[dict]:
    """
    Returns a hardcoded list of demo domains when no session cookie is set.
    Useful for testing the scoring and UI without scraping.
    """
    return [
        {"name": "loanpro.com", "backlink_count": 42, "domain_age_years": 8.2, "source": "demo"},
        {"name": "aihealthhub.com", "backlink_count": 5, "domain_age_years": 2.1, "source": "demo"},
        {"name": "quickbuyer.com", "backlink_count": 120, "domain_age_years": 11.5, "source": "demo"},
        {"name": "zxvqtrp.com", "backlink_count": 0, "domain_age_years": 0.5, "source": "demo"},
        {"name": "telAviv.tech", "backlink_count": 0, "domain_age_years": 1.0, "source": "demo"},
        {"name": "cyberdefend.io", "backlink_count": 8, "domain_age_years": 3.4, "source": "demo"},
        {"name": "investwise.net", "backlink_count": 65, "domain_age_years": 6.7, "source": "demo"},
        {"name": "legalaid24.com", "backlink_count": 12, "domain_age_years": 4.1, "source": "demo"},
        {"name": "rentflow.app", "backlink_count": 3, "domain_age_years": 1.8, "source": "demo"},
        {"name": "safedriveai.com", "backlink_count": 0, "domain_age_years": 0.3, "source": "demo"},
        {"name": "dentistfinder.com", "backlink_count": 88, "domain_age_years": 9.0, "source": "demo"},
        {"name": "cryptosafe.io", "backlink_count": 31, "domain_age_years": 2.9, "source": "demo"},
        {"name": "realty360.com", "backlink_count": 200, "domain_age_years": 14.2, "source": "demo"},
        {"name": "myfundapp.com", "backlink_count": 6, "domain_age_years": 1.2, "source": "demo"},
        {"name": "insureme.net", "backlink_count": 55, "domain_age_years": 7.5, "source": "demo"},
    ]
