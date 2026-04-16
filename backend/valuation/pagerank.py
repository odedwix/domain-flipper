"""
Open PageRank API — free, no payment, 10,000 calls/hour.
Provides real PageRank scores for any domain.

Get your free API key at: https://www.domcop.com/openpagerank/
Takes 30 seconds to sign up.

PageRank 0 = no authority
PageRank 10 = Google/Facebook level

Most good expired domains: PageRank 1–4
"""

import logging
import httpx
from config import get_settings

logger = logging.getLogger(__name__)

OPR_URL = "https://openpagerank.com/api/v1.0/getPageRank"

# Rough DA proxy from PageRank integer
_PR_TO_DA = {0: 0, 1: 10, 2: 20, 3: 35, 4: 50, 5: 65, 6: 75, 7: 85, 8: 90, 9: 95, 10: 100}


async def get_pagerank_batch(domains: list[str]) -> dict[str, dict]:
    """
    Fetch PageRank for up to 100 domains in a single API call.
    Returns dict keyed by domain name:
      {"domain.com": {"page_rank_integer": 3, "page_rank_decimal": 3.14,
                      "rank": "1234567", "domain_authority_proxy": 35}}
    """
    settings = get_settings()
    api_key = getattr(settings, "openpagerank_api_key", "")

    if not api_key:
        return {d: _no_data(d) for d in domains}

    # API accepts up to 100 domains per call
    results = {}
    for i in range(0, len(domains), 100):
        batch = domains[i:i + 100]
        params = [("domains[]", d) for d in batch]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    OPR_URL,
                    params=params,
                    headers={"API-OPR": api_key},
                )
                resp.raise_for_status()
                data = resp.json()

            for item in data.get("response", []):
                domain = item.get("domain", "")
                pr_int = item.get("page_rank_integer", 0) or 0
                results[domain] = {
                    "page_rank_integer": pr_int,
                    "page_rank_decimal": item.get("page_rank_decimal", 0.0) or 0.0,
                    "rank": item.get("rank"),
                    "domain_authority_proxy": _PR_TO_DA.get(pr_int, 0),
                    "error": item.get("error") or None,
                    "source": "openpagerank",
                }

        except Exception as e:
            logger.error(f"Open PageRank batch failed: {e}")
            for d in batch:
                results[d] = _no_data(d, error=str(e))

    return results


async def get_pagerank(domain: str) -> dict:
    """Fetch PageRank for a single domain."""
    batch = await get_pagerank_batch([domain])
    return batch.get(domain, _no_data(domain))


def _no_data(domain: str, error: str = "OPENPAGERANK_API_KEY not set") -> dict:
    return {
        "page_rank_integer": None,
        "page_rank_decimal": None,
        "rank": None,
        "domain_authority_proxy": None,
        "error": error,
        "source": "openpagerank_unavailable",
    }


def pagerank_to_backlink_score(pr_int: int | None) -> float:
    """Convert PageRank integer (0-10) to our 0-100 backlink score."""
    if pr_int is None:
        return 0.0
    return float(_PR_TO_DA.get(int(pr_int), 0))
