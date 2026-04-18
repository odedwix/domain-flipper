"""
Liquidity scoring — predicts how fast a domain will sell.
Score 0–100. Domains scoring ≥ 65 are "liquid" (likely to sell within days–weeks).

Signals (validated by domain broker community):
  - .com TLD only: the only TLD with a deep liquid secondary market
  - Length: 4–7 chars sell fastest; 8–10 ok; 11+ slow
  - Single common English word: highest liquidity class
  - CPC/commercial keywords: buyers need it for business
  - Niche targeting: hot verticals have active buyers RIGHT NOW
  - No numbers: numbers kill liquidity on branded domains
  - Clean brandable: easy to pronounce, spell, remember
"""

import re
from wordfreq import word_frequency

# Verticals with active buyer pools and few good .com alternatives
HOT_NICHES = {
    # AI / tech
    "ai", "bot", "gpt", "llm", "ml", "neural", "model", "agent", "chat", "prompt",
    "copilot", "autopilot", "automate", "automation", "vision", "detect", "predict",
    "analytics", "data", "cloud", "saas", "api", "stack", "code", "dev", "deploy",
    "monitor", "alert", "insight", "dashboard", "metric",
    # Finance / fintech
    "loan", "lend", "credit", "fund", "invest", "capital", "wealth", "asset",
    "trade", "pay", "wallet", "bank", "finance", "cash", "money", "earn",
    "income", "tax", "audit", "ledger", "invoice", "budget", "saving",
    # Health / wellness
    "health", "care", "med", "clinic", "doctor", "therapy", "mental", "fit",
    "diet", "weight", "sleep", "wellness", "heal", "bio", "gene", "pharma",
    "dental", "vision", "drug", "dose", "patient", "nurse", "hospital",
    # Real estate / property
    "home", "house", "realty", "property", "rent", "lease", "mortgage", "land",
    "estate", "move", "reloc", "buy", "sell", "list", "agent", "build",
    # Legal / professional
    "legal", "law", "attorney", "counsel", "contract", "comply", "audit",
    "secure", "safe", "trust", "verify", "sign", "notary",
    # Ecommerce / retail
    "shop", "store", "market", "cart", "order", "ship", "deliver", "track",
    "price", "deal", "sale", "buy", "resell", "supply", "vendor",
    # HR / recruiting
    "hire", "recruit", "talent", "staff", "team", "work", "job", "career",
    "remote", "freelance", "payroll", "benefit", "onboard",
    # Climate / sustainability
    "solar", "green", "clean", "carbon", "energy", "power", "electric",
    "sustain", "recycle", "eco", "net", "zero", "renew",
    # Crypto / Web3
    "crypto", "coin", "token", "nft", "defi", "chain", "block", "web3",
    "stake", "yield", "swap", "bridge", "vault",
}

# Brands known to aggressively acquire defensive domains (high urgency)
BRAND_SENSITIVE_TERMS = {
    "apple", "google", "meta", "microsoft", "amazon", "tesla", "nvidia",
    "openai", "anthropic", "stripe", "shopify", "uber", "airbnb", "netflix",
    "spotify", "tiktok", "snap", "twitter", "x", "linkedin", "salesforce",
    "oracle", "sap", "adobe", "zoom", "slack", "notion", "figma", "canva",
    "coinbase", "binance", "robinhood", "revolut", "wise", "paypal",
    "samsung", "huawei", "alibaba", "tencent", "bytedance",
}


def liquidity_score(name: str, tld: str, sld: str, backlink_count: int = 0,
                    domain_age_years: float = 0) -> dict:
    """
    Returns {"liquidity_score": int, "liquidity_label": str, "liquidity_reasons": list}
    label: LIQUID | MODERATE | SLOW | ILLIQUID
    """
    score = 0
    reasons = []
    penalties = []

    # ── TLD: .com is the only liquid TLD ──────────────────────────────────────
    if tld == "com":
        score += 30
        reasons.append(".com (+30)")
    elif tld in ("io", "ai"):
        score += 10
        reasons.append(f".{tld} (+10)")
    else:
        penalties.append(f".{tld} is hard to sell (−20)")
        score -= 20

    # ── Length: sweet spot is 4–9 chars ───────────────────────────────────────
    n = len(sld)
    if n <= 5:
        score += 25
        reasons.append(f"{n} chars — very short (+25)")
    elif n <= 7:
        score += 20
        reasons.append(f"{n} chars — short (+20)")
    elif n <= 9:
        score += 12
        reasons.append(f"{n} chars — ok (+12)")
    elif n <= 11:
        score += 5
    else:
        score -= 10
        penalties.append(f"{n} chars — too long (−10)")

    # ── Real English word (wordfreq) ──────────────────────────────────────────
    freq = word_frequency(sld, "en")
    if freq > 1e-4:
        score += 20
        reasons.append("common English word (+20)")
    elif freq > 1e-5:
        score += 12
        reasons.append("known English word (+12)")
    elif freq > 1e-6:
        score += 5

    # ── Hot niche keyword ─────────────────────────────────────────────────────
    sld_lower = sld.lower()
    matched_niches = [kw for kw in HOT_NICHES if kw in sld_lower]
    if matched_niches:
        score += 15
        reasons.append(f"hot niche: {', '.join(matched_niches[:3])} (+15)")

    # ── Pronounceable (no consecutive consonant clusters) ─────────────────────
    vowels = set("aeiou")
    consonant_run = 0
    max_run = 0
    for ch in sld_lower:
        if ch not in vowels:
            consonant_run += 1
            max_run = max(max_run, consonant_run)
        else:
            consonant_run = 0
    if max_run <= 2:
        score += 10
        reasons.append("easy to pronounce (+10)")
    elif max_run >= 4:
        score -= 8
        penalties.append("hard to pronounce consonant cluster (−8)")

    # ── Numbers kill brandability ─────────────────────────────────────────────
    if any(c.isdigit() for c in sld):
        score -= 10
        penalties.append("contains number (−10)")

    # ── Brand conflict flag ───────────────────────────────────────────────────
    brand_hit = next((b for b in BRAND_SENSITIVE_TERMS if b in sld_lower), None)
    brand_conflict = brand_hit is not None

    # Backlinks signal past traffic (secondary)
    if backlink_count and backlink_count > 50:
        score += 5
        reasons.append(f"{backlink_count} backlinks (+5)")

    score = max(0, min(100, score))

    if score >= 65:
        label = "LIQUID"
    elif score >= 45:
        label = "MODERATE"
    elif score >= 25:
        label = "SLOW"
    else:
        label = "ILLIQUID"

    return {
        "liquidity_score": score,
        "liquidity_label": label,
        "liquidity_reasons": reasons + penalties,
        "brand_conflict": brand_conflict,
        "brand_conflict_term": brand_hit,
        "hot_niches": matched_niches,
    }
