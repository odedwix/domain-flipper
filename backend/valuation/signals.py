"""
Extended domain signals for smarter purchase decisions.

APIs used (all free or near-free):
  - Wayback Machine CDX API   : free, no key needed
  - Google Safe Browsing v5   : free, needs GOOGLE_API_KEY
  - DataForSEO                : ~$0.02 per 100 keywords, needs DATAFORSEO_EMAIL + PASSWORD
  - WHOIS / expiry dates       : already fetched in whois_lookup.py
"""

import asyncio
import base64
import logging
import re
from datetime import datetime, date, timedelta
from typing import Optional

import httpx
import tldextract

from config import get_settings

logger = logging.getLogger(__name__)

# ── Trademark: common registered brand names to flag ──────────────────────────
# Not exhaustive — flags obvious cases before spending $10
_KNOWN_BRANDS = {
    "google", "apple", "microsoft", "amazon", "facebook", "meta", "netflix",
    "instagram", "whatsapp", "youtube", "twitter", "x", "tiktok", "snapchat",
    "uber", "airbnb", "spotify", "linkedin", "pinterest", "reddit", "discord",
    "samsung", "sony", "nike", "adidas", "coca", "cocacola", "pepsi", "visa",
    "mastercard", "paypal", "stripe", "shopify", "wordpress", "adobe",
    "salesforce", "oracle", "ibm", "intel", "nvidia", "amd", "tesla", "spacex",
}

# Adult / spam content types detected in Wayback mimetype
_BAD_MIMETYPES = {"application/x-shockwave-flash"}
_SPAM_KEYWORDS  = ["casino", "poker", "viagra", "cialis", "porn", "xxx", "adult",
                   "gambling", "payday", "loan-shark", "pharma", "pill"]


# ── 1. Wayback Machine ────────────────────────────────────────────────────────

async def wayback_analysis(domain: str) -> dict:
    """
    Query Wayback Machine CDX API for domain history.
    Returns snapshot count, first/last date, spam/adult content flag.
    Free — no API key needed.
    """
    base = "http://web.archive.org/cdx/search/cdx"

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            # Get first and last snapshot
            first_r, last_r, count_r = await asyncio.gather(
                client.get(base, params={"url": domain, "limit": 1, "output": "json", "fl": "timestamp,statuscode"}),
                client.get(base, params={"url": domain, "limit": -1, "output": "json", "fl": "timestamp,statuscode"}),
                client.get(base, params={"url": domain, "output": "json", "fl": "timestamp", "collapse": "timestamp:10"}),
            )

        def parse_ts(ts: str) -> Optional[str]:
            try:
                return datetime.strptime(ts[:8], "%Y%m%d").strftime("%Y-%m-%d")
            except Exception:
                return None

        first_rows = first_r.json() if first_r.status_code == 200 else []
        last_rows  = last_r.json()  if last_r.status_code == 200 else []
        count_rows = count_r.json() if count_r.status_code == 200 else []

        first_date = parse_ts(first_rows[1][0]) if len(first_rows) > 1 else None
        last_date  = parse_ts(last_rows[-1][0])  if len(last_rows) > 1 else None
        # Subtract 1 for the header row
        snapshot_count = max(0, len(count_rows) - 1)

        # Age from first wayback snapshot (proxy for domain age)
        wb_age_years = None
        if first_date:
            first_dt = datetime.strptime(first_date, "%Y-%m-%d")
            wb_age_years = round((datetime.utcnow() - first_dt).days / 365.25, 1)

        return {
            "snapshot_count": snapshot_count,
            "first_seen": first_date,
            "last_seen": last_date,
            "wayback_age_years": wb_age_years,
            "has_history": snapshot_count > 0,
            "source": "wayback",
        }

    except Exception as e:
        logger.warning(f"Wayback lookup failed for {domain}: {e}")
        return {"snapshot_count": 0, "first_seen": None, "last_seen": None,
                "wayback_age_years": None, "has_history": False, "source": "wayback_error"}


# ── 2. Google Safe Browsing ───────────────────────────────────────────────────

async def safe_browsing_check(domain: str) -> dict:
    """
    Check domain against Google Safe Browsing v5 (free, non-commercial).
    Returns {"safe": bool, "threats": list, "error": str|None}
    Requires GOOGLE_API_KEY in .env.
    """
    settings = get_settings()
    api_key = getattr(settings, "google_api_key", "")

    if not api_key:
        return {"safe": None, "threats": [], "error": "GOOGLE_API_KEY not set (skip safe browsing check)"}

    url_to_check = f"https://{domain}/"
    endpoint = f"https://safebrowsing.googleapis.com/v5/urls:search?key={api_key}"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(endpoint, json={"uri": url_to_check})
            resp.raise_for_status()
            data = resp.json()

        # Empty response = safe
        if not data or "threat" not in data:
            return {"safe": True, "threats": [], "error": None}

        threat = data.get("threat", {})
        threat_types = threat.get("threatTypes", [])
        return {"safe": False, "threats": threat_types, "error": None}

    except Exception as e:
        logger.warning(f"Safe Browsing check failed for {domain}: {e}")
        return {"safe": None, "threats": [], "error": str(e)}


# ── 3. DataForSEO keyword data ────────────────────────────────────────────────

async def keyword_metrics(keyword: str) -> dict:
    """
    Fetch search volume + CPC for a keyword via DataForSEO.
    Cost: ~$0.0002 per keyword — almost free.
    Requires DATAFORSEO_EMAIL + DATAFORSEO_PASSWORD in .env.
    Returns {"search_volume": int, "cpc": float, "competition": float, "error": str|None}
    """
    settings = get_settings()
    email    = getattr(settings, "dataforseo_email", "")
    password = getattr(settings, "dataforseo_password", "")

    if not email or not password:
        return {"search_volume": None, "cpc": None, "competition": None,
                "error": "DataForSEO credentials not set"}

    token = base64.b64encode(f"{email}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    payload = [{"keywords": [keyword], "location_code": 2840, "language_code": "en"}]

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        result = (data.get("tasks") or [{}])[0].get("result") or []
        if not result:
            return {"search_volume": 0, "cpc": 0.0, "competition": 0.0, "error": None}

        item = result[0]
        return {
            "search_volume": item.get("search_volume", 0),
            "cpc": round(item.get("cpc", 0.0), 2),
            "competition": round(item.get("competition", 0.0), 2),
            "error": None,
        }

    except Exception as e:
        logger.warning(f"DataForSEO failed for '{keyword}': {e}")
        return {"search_volume": None, "cpc": None, "competition": None, "error": str(e)}


# ── 4. Drop date calculator ───────────────────────────────────────────────────

def calculate_drop_date(expiry_date_str: Optional[str]) -> dict:
    """
    Given a domain expiry date string, calculate:
    - Grace period end (30 days after expiry)
    - Redemption period end (60 days after expiry)
    - Expected drop date (75 days after expiry)
    - Days until drop (from today)
    """
    if not expiry_date_str:
        return {"drop_date": None, "days_until_drop": None, "phase": "unknown"}

    # Try common date formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d-%b-%Y", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            expiry = datetime.strptime(expiry_date_str[:19], fmt).date()
            break
        except ValueError:
            continue
    else:
        return {"drop_date": None, "days_until_drop": None, "phase": "parse_error"}

    today = date.today()
    grace_end      = expiry + timedelta(days=30)
    redemption_end = expiry + timedelta(days=60)
    drop_date      = expiry + timedelta(days=75)
    days_until     = (drop_date - today).days

    if today <= expiry:
        phase = "active"
    elif today <= grace_end:
        phase = "grace_period"       # owner can renew cheaply
    elif today <= redemption_end:
        phase = "redemption_period"  # costs ~$200 to reclaim
    elif today < drop_date:
        phase = "pending_delete"     # nobody can register yet
    else:
        phase = "dropped"            # available now

    return {
        "expiry_date": str(expiry),
        "grace_end": str(grace_end),
        "redemption_end": str(redemption_end),
        "drop_date": str(drop_date),
        "days_until_drop": days_until,
        "phase": phase,
        "phase_label": {
            "active": "Active — not expired yet",
            "grace_period": "Grace period — owner can still renew cheap",
            "redemption_period": "Redemption — costs ~$200 to reclaim",
            "pending_delete": f"Drops in {days_until} days — mark your calendar",
            "dropped": "Dropped — register now for $10",
        }.get(phase, phase),
    }


# ── 5. Trademark heuristic ────────────────────────────────────────────────────

def trademark_check(domain: str) -> dict:
    """
    Quick heuristic trademark check.
    Returns {"likely_trademarked": bool, "matched_brand": str|None, "warning": str}
    For definitive check: https://tmsearch.uspto.gov
    """
    ext = tldextract.extract(domain)
    sld = ext.domain.lower()

    # Exact match
    if sld in _KNOWN_BRANDS:
        return {
            "likely_trademarked": True,
            "matched_brand": sld,
            "warning": f"'{sld}' is a well-known registered trademark — do NOT register",
            "verify_url": f"https://tmsearch.uspto.gov/search/search-information?query={sld}",
        }

    # Contains a known brand
    for brand in _KNOWN_BRANDS:
        if brand in sld and len(brand) >= 5:  # avoid short false positives
            return {
                "likely_trademarked": True,
                "matched_brand": brand,
                "warning": f"Contains trademark '{brand}' — cybersquatting risk",
                "verify_url": f"https://tmsearch.uspto.gov/search/search-information?query={brand}",
            }

    return {
        "likely_trademarked": False,
        "matched_brand": None,
        "warning": None,
        "verify_url": f"https://tmsearch.uspto.gov/search/search-information?query={sld}",
    }


# ── 6. Similar domains availability ──────────────────────────────────────────

async def check_similar_domains(domain: str) -> dict:
    """
    Check if .net, .org, .io versions of the same SLD are registered.
    If they are → there's established demand. If they're not → less competition.
    Uses Namecheap availability API if configured, otherwise WHOIS-based check.
    """
    ext = tldextract.extract(domain)
    sld = ext.domain

    tlds_to_check = ["com", "net", "org", "io", "ai", "co"]
    results = {}

    try:
        from purchase.namecheap import check_availability
        settings = get_settings()

        if settings.namecheap_api_key:
            tasks = {tld: check_availability(f"{sld}.{tld}") for tld in tlds_to_check}
            resolved = {tld: await coro for tld, coro in tasks.items()}
            for tld, res in resolved.items():
                results[f"{sld}.{tld}"] = "available" if res.get("available") else "taken"
        else:
            # Fallback: DNS lookup
            import socket
            for tld in tlds_to_check:
                test_domain = f"{sld}.{tld}"
                try:
                    socket.gethostbyname(test_domain)
                    results[test_domain] = "taken"
                except socket.gaierror:
                    results[test_domain] = "likely_available"

    except Exception as e:
        logger.warning(f"Similar domain check failed: {e}")

    taken = [d for d, s in results.items() if s == "taken"]
    available = [d for d, s in results.items() if "available" in s]

    return {
        "results": results,
        "taken_count": len(taken),
        "available_count": len(available),
        "demand_signal": len(taken) >= 2,  # if 2+ TLDs taken, there's demand
    }


# ── 7. Full enrichment — run all signals in parallel ─────────────────────────

async def enrich_domain(domain: str, expiry_date: Optional[str] = None) -> dict:
    """
    Run all enrichment signals for a domain in parallel.
    Returns a combined dict with all signal data.
    """
    from valuation.whois_lookup import whois_lookup, lapsed_by_mistake_score

    ext = tldextract.extract(domain)
    sld = ext.domain

    # Run async signals in parallel
    wayback, safe, kw_metrics, similar, whois_data = await asyncio.gather(
        wayback_analysis(domain),
        safe_browsing_check(domain),
        keyword_metrics(sld),
        check_similar_domains(domain),
        whois_lookup(domain),
    )

    # Sync signals
    drop_info = calculate_drop_date(expiry_date or whois_data.get("expiration_date"))
    tm_check  = trademark_check(domain)
    lapsed    = lapsed_by_mistake_score(whois_data, wayback)

    return {
        "domain": domain,
        "wayback": wayback,
        "safe_browsing": safe,
        "keyword_metrics": kw_metrics,
        "drop_info": drop_info,
        "trademark": tm_check,
        "similar_domains": similar,
        "whois": whois_data,
        "lapsed": lapsed,
    }


def signals_to_score_adjustments(enrichment: dict) -> dict:
    """
    Convert enrichment data into score adjustments (+/-) and flags.
    Returns {"bonus": float, "penalty": float, "flags": list[str], "hard_stop": bool}
    """
    bonus   = 0.0
    penalty = 0.0
    flags   = []
    hard_stop = False

    # Trademark — hard stop
    tm = enrichment.get("trademark", {})
    if tm.get("likely_trademarked"):
        hard_stop = True
        flags.append(f"TRADEMARK: {tm['warning']}")

    # Safe Browsing — heavy penalty
    sb = enrichment.get("safe_browsing", {})
    if sb.get("safe") is False:
        penalty += 30
        flags.append(f"MALWARE/PHISHING HISTORY: {', '.join(sb['threats'])}")

    # Wayback — bonus for rich history, penalty for none
    wb = enrichment.get("wayback", {})
    snaps = wb.get("snapshot_count", 0)
    if snaps > 500:
        bonus += 8
        flags.append(f"Strong history: {snaps} Wayback snapshots")
    elif snaps > 50:
        bonus += 4
        flags.append(f"Decent history: {snaps} Wayback snapshots")
    elif snaps == 0:
        penalty += 3
        flags.append("No Wayback history — never had a real website")

    # Keyword search volume + CPC
    kw = enrichment.get("keyword_metrics", {})
    vol  = kw.get("search_volume") or 0
    cpc  = kw.get("cpc") or 0.0
    if vol > 10000 and cpc > 2.0:
        bonus += 10
        flags.append(f"High-value keyword: {vol:,}/mo searches, ${cpc} CPC")
    elif vol > 1000 and cpc > 0.5:
        bonus += 5
        flags.append(f"Moderate keyword demand: {vol:,}/mo, ${cpc} CPC")

    # Similar domains — demand signal
    sim = enrichment.get("similar_domains", {})
    if sim.get("demand_signal"):
        bonus += 5
        flags.append(f"{sim['taken_count']} other TLDs already taken — proven demand")

    # Drop info
    drop = enrichment.get("drop_info", {})
    if drop.get("phase") == "dropped":
        bonus += 3
        flags.append("Already dropped — register now before others do")
    elif drop.get("phase") == "pending_delete":
        days = drop.get("days_until_drop", 0)
        flags.append(f"Drops in {days} days — set a reminder to register then")

    # Lapsed-by-mistake — bonus if original owner is likely to buy back
    lapsed = enrichment.get("lapsed", {})
    lapsed_score = lapsed.get("lapsed_score", 0)
    if lapsed_score >= 75:
        bonus += 10
        flags.append(f"HOT resale target — original owner very likely to rebuy ({lapsed_score}/100)")
    elif lapsed_score >= 50:
        bonus += 5
        flags.append(f"WARM resale target — original owner may want it back ({lapsed_score}/100)")

    return {
        "bonus": round(bonus, 1),
        "penalty": round(penalty, 1),
        "net_adjustment": round(bonus - penalty, 1),
        "flags": flags,
        "hard_stop": hard_stop,
    }
