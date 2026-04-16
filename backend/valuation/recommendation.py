"""
Buy/Skip recommendation engine.

Produces a BUY / MAYBE / SKIP decision with:
- Confidence score (0–100)
- Liquidity estimate (days to sell)
- Risk factors (what could go wrong)
- Expected ROI after all costs
- Clear reasoning the user can act on
"""

import tldextract
from typing import Optional
from valuation.scorer import score_domain, HIGH_VALUE_KEYWORDS, _load_words

# ── Constants ──────────────────────────────────────────────────────────────────

REGISTRATION_COST = 10.98   # .com standard price
RENEWAL_COST = 10.98        # per year
AFTERNIC_COMMISSION = 0.20  # 20% of sale price
SEDO_COMMISSION = 0.15

# Sectors ordered by current market liquidity (2026 data)
LIQUIDITY_MAP = {
    # (keyword_substring, expected_days_to_sell, sector_name)
    "ai": (30, "AI/ML"),
    "gpt": (25, "AI/ML"),
    "llm": (35, "AI/ML"),
    "saas": (45, "SaaS"),
    "cloud": (50, "SaaS"),
    "fintech": (40, "Fintech"),
    "pay": (40, "Fintech"),
    "crypto": (60, "Crypto"),
    "defi": (60, "Crypto"),
    "loan": (35, "Finance"),
    "insurance": (40, "Finance"),
    "invest": (45, "Finance"),
    "lawyer": (35, "Legal"),
    "legal": (40, "Legal"),
    "health": (50, "Health"),
    "medical": (55, "Health"),
    "dental": (50, "Health"),
    "realty": (55, "Real Estate"),
    "homes": (60, "Real Estate"),
    "rent": (55, "Real Estate"),
}

TLD_LIQUIDITY = {
    "com": 1.0, "ai": 0.85, "io": 0.70, "co": 0.65,
    "app": 0.60, "net": 0.55, "org": 0.45,
}


def _estimate_days_to_sell(sld: str, tld: str, score: float) -> tuple[int, str]:
    """Returns (estimated_days, sector)."""
    sld_lower = sld.lower()
    base_days = 120  # default for average domain
    sector = "General"

    for kw, (days, sec) in LIQUIDITY_MAP.items():
        if kw in sld_lower:
            base_days = days
            sector = sec
            break

    # Adjust for TLD
    tld_mult = TLD_LIQUIDITY.get(tld.lower(), 1.5)
    adjusted = int(base_days / tld_mult)

    # Score adjustment: higher score = faster sale
    if score >= 75:
        adjusted = int(adjusted * 0.7)
    elif score >= 60:
        adjusted = int(adjusted * 0.85)
    elif score < 45:
        adjusted = int(adjusted * 1.5)

    # Single dictionary word .com = fastest
    words = _load_words()
    if sld_lower in words and tld == "com":
        adjusted = min(adjusted, 45)

    return max(7, adjusted), sector


def _net_profit(sale_price: float, years_held: float = 1.0) -> float:
    """Calculate net profit after all costs."""
    renewal_costs = RENEWAL_COST * max(0, years_held - 1)  # first year covered by registration
    marketplace_fee = sale_price * AFTERNIC_COMMISSION
    net = sale_price - REGISTRATION_COST - renewal_costs - marketplace_fee
    return round(net, 2)


def _roi(sale_price: float, years_held: float = 1.0) -> float:
    total_cost = REGISTRATION_COST + RENEWAL_COST * max(0, years_held - 1)
    net = _net_profit(sale_price, years_held)
    return round((net / total_cost) * 100, 1) if total_cost > 0 else 0


def analyze(
    domain: str,
    age_years: Optional[float] = None,
    backlink_count: Optional[int] = None,
    domain_authority: Optional[float] = None,
    comparable_avg: Optional[float] = None,
    weekly_budget_remaining: Optional[float] = None,
    domains_owned: int = 0,
) -> dict:
    """
    Full buy/skip analysis for a domain.
    Returns a structured recommendation with reasoning.
    """
    ext = tldextract.extract(domain)
    sld = ext.domain
    tld = ext.suffix

    # Base score
    score_data = score_domain(domain, age_years, backlink_count, domain_authority)
    score = score_data["total_score"]
    est_value = score_data["estimated_value"]

    # If we have comparable sales, prefer that over our estimate
    if comparable_avg and comparable_avg > 0:
        # Weight: 60% comparables, 40% our model
        blended_value = round(comparable_avg * 0.6 + est_value * 0.4, -1)
    else:
        blended_value = est_value

    days_to_sell, sector = _estimate_days_to_sell(sld, tld, score)
    years_held = days_to_sell / 365

    net = _net_profit(blended_value, years_held)
    roi = _roi(blended_value, years_held)

    # ── Risk factors ───────────────────────────────────────────────────────────
    risks = []
    positives = []

    if tld != "com":
        risks.append(f".{tld} domains sell slower than .com — expect 30–50% longer hold time")
    else:
        positives.append(".com — highest liquidity TLD")

    if len(sld) > 10:
        risks.append(f"Long name ({len(sld)} chars) — harder to brand, slower to sell")
    elif len(sld) <= 6:
        positives.append(f"Short name ({len(sld)} chars) — premium signal")

    if "-" in sld or any(c.isdigit() for c in sld):
        risks.append("Hyphens or numbers reduce value by 40–60% — most buyers avoid them")

    words = _load_words()
    if sld.lower() in words:
        positives.append("Single dictionary word — top tier, highest buyer demand")
    elif any(kw in sld.lower() for kw in HIGH_VALUE_KEYWORDS):
        positives.append(f"Contains commercial keyword — active buyer pool in {sector}")

    if blended_value < 150:
        risks.append("Low estimated value — margin after fees may not justify the purchase")

    if domains_owned > 20:
        risks.append(f"You already own {domains_owned} domains — each costs $10/yr to hold. Be selective.")

    if not comparable_avg:
        risks.append("No comparable sales data — value estimate is model-based, not market-verified")
    else:
        positives.append(f"Comparable sales avg: ${comparable_avg:,.0f} — market-validated")

    holding_cost_1yr = REGISTRATION_COST + RENEWAL_COST
    if blended_value < holding_cost_1yr * 3:
        risks.append(f"Low margin of safety — domain must sell within months or renewal erodes profit")

    if weekly_budget_remaining is not None and weekly_budget_remaining < REGISTRATION_COST:
        risks.append("You've hit your weekly budget — skip this to avoid overexposure")

    # ── Decision logic ────────────────────────────────────────────────────────
    # Hard stops → SKIP
    if "-" in sld and any(c.isdigit() for c in sld):
        decision = "SKIP"
        confidence = 90
        reason = "Hyphens AND numbers — virtually unsellable at a profit"
    elif blended_value < 80:
        decision = "SKIP"
        confidence = 85
        reason = "Estimated value too low to cover fees and break even"
    elif weekly_budget_remaining is not None and weekly_budget_remaining < REGISTRATION_COST:
        decision = "SKIP"
        confidence = 95
        reason = "Weekly budget exhausted — protect your capital"
    elif score >= 65 and len(risks) <= 1 and net > 200:
        decision = "BUY"
        confidence = min(95, int(score + len(positives) * 5))
        reason = f"Strong signals: {', '.join(positives[:2])}. Est. {days_to_sell}d to sell, ${net:,.0f} net profit."
    elif score >= 50 and net > 50:
        decision = "MAYBE"
        confidence = min(70, int(score))
        reason = f"Decent domain but {len(risks)} risk factor(s). Only buy if you have strong conviction on the sector."
    else:
        decision = "SKIP"
        confidence = min(85, 100 - int(score))
        reason = f"Too many risk factors ({len(risks)}) relative to upside. Capital better deployed elsewhere."

    return {
        "domain": domain,
        "decision": decision,            # BUY / MAYBE / SKIP
        "confidence": confidence,        # 0–100
        "reason": reason,
        "score": score,
        "sector": sector,
        "estimated_value": blended_value,
        "days_to_sell_estimate": days_to_sell,
        "net_profit_estimate": net,
        "roi_estimate_pct": roi,
        "registration_cost": REGISTRATION_COST,
        "marketplace_fee_pct": int(AFTERNIC_COMMISSION * 100),
        "positives": positives,
        "risks": risks,
        "score_breakdown": score_data,
        "comparable_avg": comparable_avg,
    }


def portfolio_health(domains: list[dict]) -> dict:
    """
    Analyze a portfolio of purchased domains for concentration risk and holding costs.
    domains: list of {"name", "purchase_price", "days_held", "status"}
    """
    if not domains:
        return {"status": "empty", "warnings": [], "monthly_burn": 0}

    monthly_burn = len(domains) * (RENEWAL_COST / 12)
    warnings = []

    # Concentration by TLD
    tld_counts = {}
    sector_counts = {}
    for d in domains:
        ext = tldextract.extract(d.get("name", ""))
        tld = ext.suffix
        tld_counts[tld] = tld_counts.get(tld, 0) + 1

        sld = ext.domain.lower()
        for kw, (_, sector) in LIQUIDITY_MAP.items():
            if kw in sld:
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
                break

    total = len(domains)
    for tld, count in tld_counts.items():
        if count / total > 0.7 and tld != "com":
            warnings.append(f"70%+ of portfolio is .{tld} — diversify into .com")

    # Stale domains (held > 1 year unsold)
    stale = [d for d in domains if d.get("days_held", 0) > 365 and d.get("status") == "purchased"]
    if stale:
        stale_cost = len(stale) * RENEWAL_COST
        warnings.append(
            f"{len(stale)} domain(s) unsold after 1 year — consider dropping them to save ${stale_cost:.0f}/yr in renewals"
        )

    if total > 30:
        warnings.append(
            f"Large portfolio ({total} domains) — at ${monthly_burn:.0f}/month burn. "
            "Focus on selling, not buying, until you've cleared inventory."
        )

    return {
        "total_domains": total,
        "monthly_burn": round(monthly_burn, 2),
        "annual_burn": round(monthly_burn * 12, 2),
        "tld_breakdown": tld_counts,
        "sector_breakdown": sector_counts,
        "stale_count": len(stale),
        "warnings": warnings,
    }
