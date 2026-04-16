"""
Bulk enrichment endpoints.

POST /api/enrich/pagerank  — run Open PageRank on all domains in DB
GET  /api/enrich/status    — how many domains have PageRank data
"""

import logging
import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import Domain
from valuation.pagerank import get_pagerank_batch, pagerank_to_backlink_score
from valuation.scorer import score_domain
import json

router = APIRouter(prefix="/api/enrich", tags=["enrich"])
logger = logging.getLogger(__name__)

_enriching = False


async def _run_pagerank_enrichment():
    global _enriching
    if _enriching:
        return
    _enriching = True
    db = SessionLocal()

    try:
        domains = db.query(Domain).all()
        names = [d.name for d in domains]
        logger.info(f"Starting Open PageRank enrichment for {len(names)} domains")

        # Process in batches of 100 (API limit per call)
        updated = 0
        for i in range(0, len(names), 100):
            batch_names = names[i:i + 100]
            pr_data = await get_pagerank_batch(batch_names)

            for domain in domains[i:i + 100]:
                pr = pr_data.get(domain.name, {})
                pr_int = pr.get("page_rank_integer")
                da = pr.get("domain_authority_proxy")

                if pr_int is not None:
                    domain.domain_authority = da
                    # Update backlink score via re-scoring
                    new_score = score_domain(
                        domain.name,
                        age_years=domain.domain_age_years,
                        backlink_count=domain.backlink_count,
                        domain_authority=float(da) if da is not None else None,
                    )
                    domain.score = new_score["total_score"]
                    domain.estimated_value = new_score["estimated_value"]
                    domain.score_breakdown = json.dumps({
                        k: v for k, v in new_score.items() if k.endswith("_score")
                    })
                    updated += 1

            db.commit()
            logger.info(f"PageRank enriched {min(i+100, len(names))}/{len(names)} domains")

            # Small delay between batches to be polite
            if i + 100 < len(names):
                await asyncio.sleep(0.5)

        logger.info(f"PageRank enrichment complete — updated {updated} domains")

    except Exception as e:
        logger.exception("PageRank enrichment error")
    finally:
        _enriching = False
        db.close()


@router.post("/pagerank")
async def enrich_pagerank(background_tasks: BackgroundTasks):
    """
    Run Open PageRank on all domains in the database.
    Updates domain_authority, score, and estimated_value for every domain.
    Requires OPENPAGERANK_API_KEY in .env (free at domcop.com/openpagerank).
    """
    if _enriching:
        return {"status": "already_running"}
    background_tasks.add_task(_run_pagerank_enrichment)
    return {
        "status": "started",
        "message": "Open PageRank enrichment started in background. Scores will update as it runs.",
    }


@router.get("/status")
async def enrich_status(db: Session = Depends(get_db)):
    total = db.query(Domain).count()
    with_da = db.query(Domain).filter(Domain.domain_authority.isnot(None)).count()
    with_bl = db.query(Domain).filter(Domain.backlink_count.isnot(None)).count()
    no_data = total - with_da

    return {
        "total_domains": total,
        "with_pagerank": with_da,
        "with_backlinks": with_bl,
        "missing_data": no_data,
        "enrichment_running": _enriching,
        "coverage_pct": round(with_da / total * 100, 1) if total else 0,
    }
