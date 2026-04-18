"""
Bulk enrichment endpoints.

POST /api/enrich/pagerank  — run Open PageRank on all domains in DB
POST /api/enrich/lapsed    — run Wayback + WHOIS lapsed-by-mistake scoring for all domains
GET  /api/enrich/status    — coverage stats
"""

import logging
import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import Domain
from valuation.pagerank import get_pagerank_batch, pagerank_to_backlink_score
from valuation.scorer import score_domain
from valuation.whois_lookup import whois_lookup, lapsed_by_mistake_score
from valuation.signals import wayback_analysis
import json

router = APIRouter(prefix="/api/enrich", tags=["enrich"])
logger = logging.getLogger(__name__)

_enriching = False
_lapsed_enriching = False
_lapsed_progress = {"done": 0, "total": 0}


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


async def _run_lapsed_enrichment():
    global _lapsed_enriching, _lapsed_progress
    if _lapsed_enriching:
        return
    _lapsed_enriching = True
    db = SessionLocal()

    try:
        domains = db.query(Domain).all()
        _lapsed_progress = {"done": 0, "total": len(domains)}
        logger.info(f"Starting lapsed enrichment for {len(domains)} domains")

        # Process in small parallel batches to avoid hammering APIs
        BATCH = 5
        for i in range(0, len(domains), BATCH):
            batch = domains[i:i + BATCH]

            async def enrich_one(d):
                wb, wh = await asyncio.gather(
                    wayback_analysis(d.name),
                    whois_lookup(d.name),
                )
                lapsed = lapsed_by_mistake_score(wh, wb)
                d.lapsed_score = lapsed["lapsed_score"]
                d.lapsed_label = lapsed["label"]
                d.wayback_snapshots = wb.get("snapshot_count")
                d.wayback_first_seen = wb.get("first_seen")
                d.wayback_last_seen = wb.get("last_seen")
                d.prev_owner_name = lapsed.get("registrant_org") or lapsed.get("registrant_name")
                d.prev_owner_email = lapsed.get("registrant_email")
                d.prev_owner_country = lapsed.get("registrant_country")

            await asyncio.gather(*[enrich_one(d) for d in batch])
            db.commit()
            _lapsed_progress["done"] = min(i + BATCH, len(domains))
            logger.info(f"Lapsed enrichment: {_lapsed_progress['done']}/{len(domains)}")

            if i + BATCH < len(domains):
                await asyncio.sleep(1.0)  # be polite to Wayback + RDAP

        hot = db.query(Domain).filter(Domain.lapsed_label == "HOT").count()
        warm = db.query(Domain).filter(Domain.lapsed_label == "WARM").count()
        logger.info(f"Lapsed enrichment complete — {hot} HOT, {warm} WARM")

    except Exception:
        logger.exception("Lapsed enrichment error")
    finally:
        _lapsed_enriching = False
        db.close()


@router.post("/lapsed")
async def enrich_lapsed(background_tasks: BackgroundTasks):
    """
    Run Wayback Machine + WHOIS lapsed-by-mistake scoring for every domain.
    Saves lapsed_score, lapsed_label, prev_owner info to DB so the HOT filter works.
    """
    if _lapsed_enriching:
        return {"status": "already_running", "progress": _lapsed_progress}
    background_tasks.add_task(_run_lapsed_enrichment)
    return {"status": "started", "message": "Lapsed enrichment started — HOT filter will populate as it runs"}


@router.get("/status")
async def enrich_status(db: Session = Depends(get_db)):
    total = db.query(Domain).count()
    with_da = db.query(Domain).filter(Domain.domain_authority.isnot(None)).count()
    with_bl = db.query(Domain).filter(Domain.backlink_count.isnot(None)).count()
    no_data = total - with_da

    hot = db.query(Domain).filter(Domain.lapsed_label == "HOT").count()
    warm = db.query(Domain).filter(Domain.lapsed_label == "WARM").count()
    lapsed_done = db.query(Domain).filter(Domain.lapsed_label.isnot(None)).count()

    return {
        "total_domains": total,
        "with_pagerank": with_da,
        "with_backlinks": with_bl,
        "missing_data": no_data,
        "enrichment_running": _enriching,
        "lapsed_enriching": _lapsed_enriching,
        "lapsed_progress": _lapsed_progress,
        "lapsed_done": lapsed_done,
        "hot_count": hot,
        "warm_count": warm,
        "coverage_pct": round(with_da / total * 100, 1) if total else 0,
    }


# ── Trends enrichment ─────────────────────────────────────────────────────────

_trends_enriching = False
_trends_progress: dict = {"done": 0, "total": 0}


async def _run_trends_enrichment():
    global _trends_enriching, _trends_progress
    if _trends_enriching:
        return
    _trends_enriching = True
    db = SessionLocal()
    try:
        from valuation.trends import get_trend_score
        domains = db.query(Domain).filter(Domain.trend_score.is_(None)).all()
        _trends_progress = {"done": 0, "total": len(domains)}
        logger.info(f"Trends enrichment: {len(domains)} domains to process")

        for d in domains:
            result = await get_trend_score(d.sld)
            d.trend_score = result["trend_score"]
            d.trend_rising = result["trend_rising"]
            db.commit()
            _trends_progress["done"] += 1
            if _trends_progress["done"] % 10 == 0:
                logger.info(f"Trends: {_trends_progress['done']}/{_trends_progress['total']}")
            await asyncio.sleep(2.5)   # rate limit Google

        logger.info("Trends enrichment complete")
    except Exception:
        logger.exception("Trends enrichment error")
    finally:
        _trends_enriching = False
        db.close()


@router.post("/trends")
async def enrich_trends(background_tasks: BackgroundTasks):
    """Score all domains by Google Trends interest for their keyword."""
    if _trends_enriching:
        return {"status": "already_running", "progress": _trends_progress}
    background_tasks.add_task(_run_trends_enrichment)
    return {"status": "started", "message": "Trends enrichment started — scores will populate gradually (rate-limited)"}


@router.get("/trends/status")
async def trends_status(db: Session = Depends(get_db)):
    done = db.query(Domain).filter(Domain.trend_score.isnot(None)).count()
    rising = db.query(Domain).filter(Domain.trend_rising == True).count()  # noqa: E712
    return {"enriching": _trends_enriching, "progress": _trends_progress, "done": done, "rising": rising}
