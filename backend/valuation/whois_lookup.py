"""
WHOIS company lookup — identifies the previous owner of an expired domain.

Uses python-whois (free, no API key) for current/recent WHOIS data.
Also queries the RDAP protocol (free, maintained by IANA) as a fallback.

Returns registrant company, email, country, and a "lapsed_by_mistake" score
that estimates how likely it is the owner forgot to renew vs. intentionally dropped.
"""

import asyncio
import logging
import re
from datetime import datetime, date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ── RDAP lookup (free, no library needed) ────────────────────────────────────

async def rdap_lookup(domain: str) -> dict:
    """
    Query IANA RDAP for structured registration data.
    Free, no API key, returns JSON with registrant entity info.
    """
    url = f"https://rdap.org/domain/{domain}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {}
            data = resp.json()

        result = {}

        # Extract registrant from entities
        for entity in data.get("entities", []):
            roles = entity.get("roles", [])
            if "registrant" not in roles:
                continue

            vcard = entity.get("vcardArray", [])
            if len(vcard) < 2:
                continue

            for prop in vcard[1]:
                ptype = prop[0] if prop else ""
                val = prop[3] if len(prop) > 3 else ""

                if ptype == "fn":
                    result["registrant_name"] = val
                elif ptype == "org":
                    result["registrant_org"] = val
                elif ptype == "email":
                    result["registrant_email"] = val
                elif ptype == "adr":
                    # val is a list: [po_box, ext, street, city, region, postal, country]
                    if isinstance(val, list) and len(val) >= 7:
                        result["registrant_country"] = val[6]
                        result["registrant_city"] = val[3]

            break  # only first registrant entity

        # Dates
        for event in data.get("events", []):
            action = event.get("eventAction", "")
            dt = event.get("eventDate", "")[:10]
            if action == "registration":
                result["creation_date"] = dt
            elif action == "expiration":
                result["expiration_date"] = dt
            elif action == "last changed":
                result["updated_date"] = dt

        result["registrar"] = (data.get("entities") or [{}])[0].get("handle", "")
        for entity in data.get("entities", []):
            if "registrar" in entity.get("roles", []):
                vcard = entity.get("vcardArray", [None, []])[1]
                for prop in vcard:
                    if prop[0] == "fn":
                        result["registrar"] = prop[3]
                        break
                break

        result["status"] = data.get("status", [])
        result["source"] = "rdap"
        return result

    except Exception as e:
        logger.debug(f"RDAP lookup failed for {domain}: {e}")
        return {}


def _whois_sync(domain: str) -> dict:
    """Run python-whois synchronously (called in thread pool)."""
    try:
        import whois
        w = whois.whois(domain)
        if not w:
            return {}

        def _first(val):
            if isinstance(val, list):
                return val[0] if val else None
            return val

        def _fmt_date(val):
            v = _first(val)
            if isinstance(v, datetime):
                return v.strftime("%Y-%m-%d")
            if isinstance(v, str):
                return v[:10]
            return None

        result = {
            "registrant_org": _first(w.get("org")) or _first(w.get("organization")),
            "registrant_name": _first(w.get("name")),
            "registrant_email": _first(w.get("emails")),
            "registrant_country": _first(w.get("country")),
            "registrant_city": _first(w.get("city")),
            "registrar": _first(w.get("registrar")),
            "creation_date": _fmt_date(w.get("creation_date")),
            "expiration_date": _fmt_date(w.get("expiration_date")),
            "updated_date": _fmt_date(w.get("updated_date")),
            "status": w.get("status") or [],
            "source": "python-whois",
        }
        return {k: v for k, v in result.items() if v}

    except Exception as e:
        logger.debug(f"python-whois failed for {domain}: {e}")
        return {}


async def whois_lookup(domain: str) -> dict:
    """
    Fetch WHOIS data using RDAP (fast, structured) then python-whois as fallback.
    Returns a normalized dict with registrant info.
    """
    # Try RDAP first (async, fast)
    rdap = await rdap_lookup(domain)
    if rdap.get("registrant_name") or rdap.get("registrant_org"):
        return rdap

    # Fallback: python-whois in thread pool (blocking IO)
    loop = asyncio.get_event_loop()
    whois_data = await loop.run_in_executor(None, _whois_sync, domain)
    return whois_data


# ── Lapsed-by-mistake scoring ─────────────────────────────────────────────────

def lapsed_by_mistake_score(whois_data: dict, wayback_data: dict) -> dict:
    """
    Estimate whether a domain was let lapse BY MISTAKE (owner forgot to renew)
    vs. intentionally dropped (project ended, domain was junk).

    Score 0–100:
      80–100 = Almost certainly a mistake — contact the owner ASAP
      50–79  = Probably a mistake — worth reaching out
      30–49  = Unclear — might be abandoned on purpose
      0–29   = Probably intentional — business shut down, or was a spam domain

    High score = high chance of a sale back to the original owner.
    """
    score = 0
    signals = []
    owner_type = "unknown"

    snapshot_count = wayback_data.get("snapshot_count", 0)
    first_seen = wayback_data.get("first_seen")
    last_seen = wayback_data.get("last_seen")
    has_history = wayback_data.get("has_history", False)

    registrant_org = whois_data.get("registrant_org", "")
    registrant_name = whois_data.get("registrant_name", "")
    registrant_email = whois_data.get("registrant_email", "")
    creation_date = whois_data.get("creation_date", "")

    # ── Signal 1: Had a real website (Wayback snapshots) ─────────────────────
    if snapshot_count >= 500:
        score += 30
        signals.append(f"Very active site — {snapshot_count} archived snapshots")
    elif snapshot_count >= 100:
        score += 22
        signals.append(f"Active site — {snapshot_count} archived snapshots")
    elif snapshot_count >= 20:
        score += 14
        signals.append(f"Some activity — {snapshot_count} archived snapshots")
    elif snapshot_count >= 5:
        score += 6
        signals.append(f"Minimal history — {snapshot_count} snapshots")
    else:
        signals.append("No archived website — was likely never actively used")

    # ── Signal 2: Recently active (last seen within 3 years) ─────────────────
    if last_seen:
        try:
            last_dt = datetime.strptime(last_seen, "%Y-%m-%d").date()
            days_since = (date.today() - last_dt).days
            years_since = days_since / 365.25

            if years_since <= 1:
                score += 30
                signals.append(f"Last seen {int(days_since)}d ago — recently active, likely a mistake")
            elif years_since <= 2:
                score += 22
                signals.append(f"Last seen ~{years_since:.1f}yr ago — may have lapsed by mistake")
            elif years_since <= 4:
                score += 12
                signals.append(f"Last seen ~{years_since:.1f}yr ago — owner may still want it")
            elif years_since <= 7:
                score += 4
                signals.append(f"Last seen {int(years_since)}yr ago — possibly abandoned")
            else:
                signals.append(f"Last seen {int(years_since)}yr ago — likely intentionally abandoned")
        except Exception:
            pass

    # ── Signal 3: Real company registrant (not a privacy shield or investor) ──
    company_indicators = ["inc", "llc", "ltd", "corp", "co.", "gmbh", "srl",
                          "pvt", "limited", "company", "group", "agency",
                          "solutions", "services", "studio", "labs", "tech"]
    investor_indicators = ["domain", "invest", "privacy", "whoisguard",
                           "perfect privacy", "domains by proxy", "contact privacy",
                           "registrant", "withheld"]

    combined_name = f"{registrant_org} {registrant_name}".lower()

    is_company = any(ind in combined_name for ind in company_indicators)
    is_investor = any(ind in combined_name for ind in investor_indicators)

    if is_company and not is_investor:
        score += 20
        owner_name = registrant_org or registrant_name
        signals.append(f"Registered to a real company: {owner_name}")
        owner_type = "company"
    elif registrant_email and not is_investor:
        score += 10
        signals.append(f"Individual registrant with contact email — reachable")
        owner_type = "individual"
    elif is_investor:
        score -= 10
        signals.append("Looks like a domain investor — unlikely to repurchase at premium")
        owner_type = "investor"
    elif combined_name.strip():
        score += 5
        owner_type = "individual"

    # ── Signal 4: Long registration history = they cared about it ────────────
    if creation_date and has_history:
        try:
            created = datetime.strptime(creation_date, "%Y-%m-%d").date()
            years_held = (date.today() - created).days / 365.25
            if years_held >= 10:
                score += 15
                signals.append(f"Held the domain for {int(years_held)} years — very likely a mistake")
            elif years_held >= 5:
                score += 10
                signals.append(f"Held for {int(years_held)} years — probably a mistake")
            elif years_held >= 2:
                score += 5
                signals.append(f"Held for {int(years_held)} years")
        except Exception:
            pass

    # ── Signal 5: Contact email available = you can actually reach them ───────
    if registrant_email and "@" in registrant_email:
        score += 5
        signals.append(f"Contact email available: {registrant_email}")

    # ── Clamp and classify ───────────────────────────────────────────────────
    score = max(0, min(100, score))

    if score >= 75:
        verdict = "Almost certainly a mistake — reach out immediately"
        label = "HOT"
    elif score >= 50:
        verdict = "Probably forgot to renew — worth contacting"
        label = "WARM"
    elif score >= 30:
        verdict = "Unclear — may have been abandoned on purpose"
        label = "LUKEWARM"
    else:
        verdict = "Likely intentionally dropped or junk domain"
        label = "COLD"

    return {
        "lapsed_score": score,
        "label": label,
        "verdict": verdict,
        "signals": signals,
        "owner_type": owner_type,
        "registrant_org": registrant_org or None,
        "registrant_name": registrant_name or None,
        "registrant_email": registrant_email or None,
        "registrant_country": whois_data.get("registrant_country"),
        "registrant_city": whois_data.get("registrant_city"),
        "registrar": whois_data.get("registrar"),
        "creation_date": creation_date or None,
        "expiration_date": whois_data.get("expiration_date"),
    }
