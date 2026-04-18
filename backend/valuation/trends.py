"""
Google Trends scoring via pytrends.
Returns a 0–100 trend score for a keyword (SLD of the domain).
Caches results in memory to avoid hammering Google.
"""

import asyncio
import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory cache: keyword → (score, rising)
_cache: dict[str, dict] = {}


def _fetch_trend_sync(keyword: str) -> dict:
    """Synchronous trend fetch — run in thread pool."""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=1, backoff_factor=0.5)
        pytrends.build_payload([keyword], cat=0, timeframe="today 12-m", geo="")
        df = pytrends.interest_over_time()
        if df.empty or keyword not in df.columns:
            return {"trend_score": 0, "trend_rising": False, "trend_error": "no data"}

        series = df[keyword].dropna()
        avg = float(series.mean())

        # Rising = last 3 months avg > overall avg
        recent = float(series.tail(13).mean())  # ~3 months of weekly data
        rising = recent > avg * 1.1

        # Normalize to 0–100
        score = min(100, int(avg))
        return {"trend_score": score, "trend_rising": rising, "trend_error": None}

    except Exception as e:
        logger.warning(f"pytrends error for '{keyword}': {e}")
        return {"trend_score": 0, "trend_rising": False, "trend_error": str(e)[:80]}


async def get_trend_score(keyword: str) -> dict:
    """Async wrapper — runs pytrends in a thread to avoid blocking."""
    if keyword in _cache:
        return _cache[keyword]

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch_trend_sync, keyword)
    _cache[keyword] = result
    return result


async def score_domains_trends(slds: list[str]) -> dict[str, dict]:
    """
    Batch-score a list of SLDs for Google Trends.
    Rate-limited to avoid Google bans: 1 request per 2 seconds.
    Returns {sld: trend_result}
    """
    results = {}
    for sld in slds:
        if sld in _cache:
            results[sld] = _cache[sld]
            continue
        results[sld] = await get_trend_score(sld)
        await asyncio.sleep(2.0)   # be polite to Google
    return results
