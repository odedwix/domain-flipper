"""
Domain valuation scorer.
Returns a 0–100 score plus an estimated resale value in USD.
"""

import json
import re
import tldextract
from typing import Optional

# High-value keywords with approximate commercial value multipliers
HIGH_VALUE_KEYWORDS = {
    # Finance
    "loan": 3.0, "loans": 3.0, "mortgage": 3.5, "insurance": 3.5,
    "credit": 2.5, "finance": 2.5, "invest": 2.0, "investing": 2.0,
    "crypto": 2.0, "bitcoin": 2.0, "trading": 2.0, "forex": 2.5,
    "bank": 2.5, "banking": 2.5, "wealth": 2.0, "fund": 2.0,
    # Legal
    "lawyer": 3.0, "legal": 2.5, "attorney": 3.0, "law": 2.5,
    "divorce": 2.5, "injury": 3.0, "accident": 2.5, "claim": 2.0,
    # Health
    "health": 2.5, "medical": 2.5, "clinic": 2.0, "doctor": 2.0,
    "therapy": 2.0, "dental": 2.0, "rehab": 2.0, "drug": 1.5,
    # Tech
    "ai": 2.5, "saas": 2.0, "software": 2.0, "cloud": 2.0,
    "app": 1.5, "tech": 1.5, "data": 1.5, "cyber": 2.0,
    "api": 1.5, "code": 1.2, "dev": 1.2, "web": 1.2,
    # Real estate
    "realty": 2.5, "homes": 2.0, "house": 1.8, "property": 2.0,
    "rent": 1.8, "lease": 1.8, "estate": 2.0,
    # Israel specific
    "israel": 1.8, "telaviv": 2.0, "startup": 1.5, "hebrew": 1.3,
}

# TLD value table (0–100)
TLD_SCORES = {
    "com": 100, "io": 75, "co": 70, "ai": 80, "net": 65,
    "org": 60, "app": 65, "dev": 60, "tech": 55, "me": 50,
    "info": 35, "biz": 30, "xyz": 25, "online": 25, "site": 20,
}

ENGLISH_WORDS: Optional[set] = None


def _load_words() -> set:
    global ENGLISH_WORDS
    if ENGLISH_WORDS is not None:
        return ENGLISH_WORDS
    try:
        import nltk
        from nltk.corpus import words as nltk_words
        try:
            ENGLISH_WORDS = set(w.lower() for w in nltk_words.words())
        except LookupError:
            nltk.download("words", quiet=True)
            ENGLISH_WORDS = set(w.lower() for w in nltk_words.words())
    except Exception:
        # Fallback: basic wordlist
        ENGLISH_WORDS = {
            "the", "app", "buy", "sell", "get", "best", "top", "new", "pro",
            "max", "hub", "lab", "net", "web", "pay", "go", "my", "now",
            "fast", "easy", "smart", "quick", "safe", "free", "real", "live",
        }
    return ENGLISH_WORDS


def score_tld(tld: str) -> float:
    return TLD_SCORES.get(tld.lower().lstrip("."), 15)


def score_length(sld: str) -> float:
    """Score based on second-level domain length (shorter = better)."""
    n = len(sld)
    if n <= 4:
        return 100
    elif n == 5:
        return 90
    elif n == 6:
        return 80
    elif n == 7:
        return 70
    elif n == 8:
        return 58
    elif n == 9:
        return 46
    elif n == 10:
        return 36
    elif n <= 12:
        return 25
    elif n <= 15:
        return 15
    else:
        return 5


def score_word(sld: str) -> float:
    """Score based on real dictionary words present."""
    words = _load_words()
    sld_lower = sld.lower()

    # Exact match
    if sld_lower in words:
        return 100

    # Contains a high-value keyword
    for kw in HIGH_VALUE_KEYWORDS:
        if kw in sld_lower:
            return 80

    # Contains any English word >= 4 chars
    for length in range(len(sld_lower), 3, -1):
        for start in range(len(sld_lower) - length + 1):
            substr = sld_lower[start:start + length]
            if substr in words:
                return 55

    # Gibberish
    return 10


def score_brandability(sld: str) -> float:
    """Score domain for brandability."""
    s = sld.lower()

    # Deduct for hyphens and numbers
    if "-" in s or any(c.isdigit() for c in s):
        base = 20
    else:
        base = 60

    # Vowel/consonant analysis
    vowels = sum(1 for c in s if c in "aeiou")
    consonants = sum(1 for c in s if c.isalpha() and c not in "aeiou")
    total_alpha = vowels + consonants
    if total_alpha > 0:
        ratio = vowels / total_alpha
        # Ideal ratio ~0.35–0.45
        ratio_score = max(0, 40 - abs(ratio - 0.40) * 100)
    else:
        ratio_score = 0

    # Syllable estimate (every vowel cluster = 1 syllable)
    syllables = len(re.findall(r"[aeiou]+", s))
    if 2 <= syllables <= 3:
        syl_score = 30
    elif syllables == 1 or syllables == 4:
        syl_score = 15
    else:
        syl_score = 5

    # Short bonus
    length_bonus = max(0, 20 - len(s) * 2)

    return min(100, base + ratio_score * 0.3 + syl_score + length_bonus)


def score_age(age_years: Optional[float]) -> float:
    if age_years is None:
        return 0
    if age_years < 1:
        return 5
    elif age_years < 3:
        return 20
    elif age_years < 5:
        return 40
    elif age_years < 8:
        return 60
    elif age_years < 12:
        return 80
    else:
        return 100


def score_backlinks(backlink_count: Optional[int], domain_authority: Optional[float]) -> float:
    if domain_authority is not None:
        return min(100, domain_authority)
    if backlink_count is None:
        return 0
    if backlink_count == 0:
        return 0
    elif backlink_count < 10:
        return 15
    elif backlink_count < 50:
        return 30
    elif backlink_count < 200:
        return 50
    elif backlink_count < 1000:
        return 70
    else:
        return 90


def score_keyword(sld: str) -> float:
    sld_lower = sld.lower()
    best = 0.0
    for kw, mult in HIGH_VALUE_KEYWORDS.items():
        if kw in sld_lower:
            val = min(100, mult * 30)
            best = max(best, val)
    return best


def estimate_value(total_score: float, sld: str, tld: str) -> float:
    """Rough USD resale value estimate based on score and signals."""
    if total_score < 35:
        base = 20
    elif total_score < 45:
        base = 50
    elif total_score < 55:
        base = 150
    elif total_score < 65:
        base = 400
    elif total_score < 75:
        base = 1200
    elif total_score < 85:
        base = 4000
    else:
        base = 12000

    words = _load_words()
    if sld.lower() in words:
        base *= 2.0
    if tld == "com" and len(sld) <= 6:
        base *= 1.8
    elif tld == "com":
        base *= 1.3

    for kw, mult in HIGH_VALUE_KEYWORDS.items():
        if kw in sld.lower():
            base *= (1 + (mult - 1) * 0.4)
            break

    return round(base, -1)  # Round to nearest $10


def score_domain(
    name: str,
    age_years: Optional[float] = None,
    backlink_count: Optional[int] = None,
    domain_authority: Optional[float] = None,
) -> dict:
    """
    Score a domain name. Returns dict with per-signal scores, total, and estimated value.
    """
    ext = tldextract.extract(name)
    sld = ext.domain
    tld = ext.suffix

    tld_s = score_tld(tld)
    len_s = score_length(sld)
    word_s = score_word(sld)
    brand_s = score_brandability(sld)
    age_s = score_age(age_years)
    bl_s = score_backlinks(backlink_count, domain_authority)
    kw_s = score_keyword(sld)

    # Weighted total
    total = (
        tld_s * 0.25
        + len_s * 0.20
        + word_s * 0.20
        + brand_s * 0.15
        + bl_s * 0.10
        + age_s * 0.05
        + kw_s * 0.05
    )
    total = round(min(100, max(0, total)), 1)

    ev = estimate_value(total, sld, tld)

    return {
        "sld": sld,
        "tld": tld,
        "tld_score": round(tld_s, 1),
        "length_score": round(len_s, 1),
        "word_score": round(word_s, 1),
        "brand_score": round(brand_s, 1),
        "backlink_score": round(bl_s, 1),
        "age_score": round(age_s, 1),
        "keyword_score": round(kw_s, 1),
        "total_score": total,
        "estimated_value": ev,
    }
