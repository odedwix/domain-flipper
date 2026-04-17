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


def _parse_leading_int(text: str) -> Optional[int]:
    """
    Extract backlink count from strings like:
      '87Majestic.com'   → 87
      '14.3 KMajestic.'  → 14300
      '1.5K'             → 1500
      '6Majestic.com SEOkic' → 6
    """
    # Match: optional decimal number, optional 'K' multiplier
    m = re.match(r"^\s*([\d]+(?:\.[\d]+)?)\s*([Kk])?", text)
    if not m:
        return None
    try:
        num = float(m.group(1))
        if m.group(2):
            num *= 1000
        return int(num)
    except (ValueError, TypeError):
        return None


def _parse_table(html: str) -> list[dict]:
    """Parse the HTML table on expireddomains.net and return list of domain dicts.

    Table columns (as of 2025):
      0: Domain, 1: BL (backlinks), 2: DP, 3: ABY (birth year), 4: ACR,
      5: Dmoz, 6-9: C/N/O/D availability, 10: Reg, 11: RDT, 12: Dropped, 13: Status
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    table = soup.find("table", class_="base1")
    if not table:
        table = soup.find("table", {"id": re.compile(r"table_")})
    if not table:
        return results

    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        # Column 0: domain name (inside an <a> tag)
        a_tag = cols[0].find("a")
        if not a_tag:
            continue
        domain_name = a_tag.text.strip().lower()
        if not domain_name or "." not in domain_name:
            continue

        # Column 1: BL — text like "6Majestic.com SEOkic", extract leading int
        bl = _parse_leading_int(cols[1].text) if len(cols) > 1 else None

        # Column 3: ABY — birth year as 4-digit integer, e.g. "2013"
        age_years = None
        if len(cols) > 3:
            aby_text = cols[3].text.strip()
            m = re.match(r"^(\d{4})$", aby_text)
            if m:
                birth_year = int(m.group(1))
                current_year = date.today().year
                if 1990 <= birth_year <= current_year:
                    age_years = round(current_year - birth_year + (date.today().month - 1) / 12, 1)

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


# Grace-period lists — these are better quality because the owner may still want the domain back
EXPIRING_LISTS = [
    ("expiring", f"{BASE_URL}/expiring-domains/"),      # just-expired, in 30-day grace period
    ("pending", f"{BASE_URL}/deleted-com-domains/"),    # deleted (current)
]


async def _fetch_list(path: str, source_label: str, max_pages: int) -> list[dict]:
    """Generic fetcher for any expireddomains.net list page."""
    settings = get_settings()
    session_cookie = settings.expireddomains_session_cookie
    if not session_cookie:
        return []

    cookies = {"ef_session": session_cookie}
    all_domains: list[dict] = []

    async with httpx.AsyncClient(
        headers=HEADERS, cookies=cookies,
        follow_redirects=True, timeout=30.0,
    ) as client:
        for page in range(max_pages):
            start = page * 25
            url = f"{BASE_URL}{path}?start={start}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                parsed = _parse_table(resp.text)
                if not parsed:
                    break
                for d in parsed:
                    d["source"] = source_label
                all_domains.extend(parsed)
                logger.info(f"{source_label} page {page + 1}: {len(parsed)} (total {len(all_domains)})")
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.error(f"Error fetching {source_label} page {page + 1}: {e}")
                break

    logger.info(f"Total {source_label} domains fetched: {len(all_domains)}")
    return all_domains


async def fetch_expiring_domains(max_pages: int = 10) -> list[dict]:
    """
    Fetch .com domains currently in the grace/redemption period.
    These are better quality — owner may still repurchase (great HOT candidates),
    and they haven't been drop-caught yet.
    """
    return await _fetch_list("/expired-domains/", "expiring", max_pages)


async def fetch_godaddy_auctions(max_pages: int = 5) -> list[dict]:
    """
    Fetch GoDaddy expired domain auctions WITH active bids.
    These are premium — real buyers have already validated they're worth something.
    """
    return await _fetch_list("/godaddy-domain-auctions-with-bids/", "godaddy_auction", max_pages)


async def fetch_dynadot_closeout(max_pages: int = 5) -> list[dict]:
    """
    Fetch Dynadot closeout domains — deeply discounted expiring domains from Dynadot's own registrar.
    Often include aged domains with decent backlinks.
    """
    return await _fetch_list("/dynadot-closeout-domains/", "dynadot_closeout", max_pages)


async def fetch_namecheap_auctions(max_pages: int = 5) -> list[dict]:
    """
    Fetch Namecheap expiring domain auctions.
    High-quality source — Namecheap customers often registered brandable names.
    Some have thousands of backlinks (e.g. SeoToolStation.com had 6,100 BL).
    """
    return await _fetch_list("/namecheap-auction-domains/", "namecheap_auction", max_pages)


async def fetch_sedo_expiring(max_pages: int = 5) -> list[dict]:
    """
    Fetch Sedo expiring domains — domains listed on Sedo marketplace that are expiring.
    Sedo domains tend to be previously monetized / parked with value.
    """
    return await _fetch_list("/sedo-expired-domains/", "sedo_expiring", max_pages)


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
