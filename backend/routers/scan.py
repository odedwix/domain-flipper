import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import Domain, DomainScore, ScanLog
from scrapers.expireddomains import fetch_expired_domains, fetch_demo_domains
from valuation.scorer import score_domain
from config import get_settings

router = APIRouter(prefix="/api/scan", tags=["scan"])
logger = logging.getLogger(__name__)

_scan_running = False
_last_scan: dict = {}


async def _run_scan(use_demo: bool = False):
    global _scan_running, _last_scan
    if _scan_running:
        return {"status": "already_running"}

    _scan_running = True
    settings = get_settings()
    db = SessionLocal()

    scan_log = ScanLog(started_at=datetime.utcnow(), status="running")
    db.add(scan_log)
    db.commit()

    try:
        logger.info("Scan started")

        if use_demo or not settings.expireddomains_session_cookie:
            raw_domains = await fetch_demo_domains()
            scan_log.source = "demo"
        else:
            pages = max(1, settings.max_domains_per_scan // 25)
            raw_domains = await fetch_expired_domains(max_pages=pages)
            scan_log.source = "expireddomains"

        scan_log.domains_found = len(raw_domains)
        db.commit()

        saved = 0
        scored = 0

        for rd in raw_domains:
            name = rd.get("name", "").lower().strip()
            if not name or "." not in name:
                continue

            # Skip if already in DB
            existing = db.query(Domain).filter(Domain.id == Domain.id, Domain.name == name).first()
            if existing:
                continue

            age = rd.get("domain_age_years")
            bl = rd.get("backlink_count")

            result = score_domain(name, age_years=age, backlink_count=bl)

            if result["total_score"] < settings.min_score_threshold:
                continue

            domain = Domain(
                name=name,
                sld=result["sld"],
                tld=result["tld"],
                source=rd.get("source", "expireddomains"),
                domain_age_years=age,
                backlink_count=bl,
                score=result["total_score"],
                estimated_value=result["estimated_value"],
                score_breakdown=json.dumps({
                    k: v for k, v in result.items()
                    if k.endswith("_score")
                }),
            )
            db.add(domain)
            db.flush()  # get the domain.id

            score_row = DomainScore(
                domain_id=domain.id,
                tld_score=result["tld_score"],
                length_score=result["length_score"],
                word_score=result["word_score"],
                brand_score=result["brand_score"],
                backlink_score=result["backlink_score"],
                age_score=result["age_score"],
                keyword_score=result["keyword_score"],
                total_score=result["total_score"],
            )
            db.add(score_row)
            scored += 1
            saved += 1

        db.commit()

        scan_log.finished_at = datetime.utcnow()
        scan_log.domains_scored = scored
        scan_log.domains_saved = saved
        scan_log.status = "done"
        db.commit()

        _last_scan = {
            "finished_at": scan_log.finished_at.isoformat(),
            "domains_found": scan_log.domains_found,
            "domains_saved": saved,
            "source": scan_log.source,
        }
        logger.info(f"Scan done: found={scan_log.domains_found}, saved={saved}")

    except Exception as e:
        logger.exception("Scan error")
        scan_log.status = "error"
        scan_log.error_msg = str(e)
        scan_log.finished_at = datetime.utcnow()
        db.commit()
    finally:
        _scan_running = False
        db.close()


@router.post("/trigger")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    demo: bool = False,
):
    if _scan_running:
        return {"status": "already_running", "message": "A scan is already in progress"}
    background_tasks.add_task(_run_scan, use_demo=demo)
    return {"status": "started", "message": "Scan started in background"}


@router.get("/status")
async def scan_status(db: Session = Depends(get_db)):
    total = db.query(Domain).count()
    by_status = {}
    for s in ["available", "watchlist", "purchased", "sold", "passed"]:
        by_status[s] = db.query(Domain).filter(Domain.status == s).count()

    last_scan_row = db.query(ScanLog).order_by(ScanLog.id.desc()).first()
    last_scan_info = None
    if last_scan_row:
        last_scan_info = {
            "started_at": last_scan_row.started_at.isoformat() if last_scan_row.started_at else None,
            "finished_at": last_scan_row.finished_at.isoformat() if last_scan_row.finished_at else None,
            "status": last_scan_row.status,
            "domains_found": last_scan_row.domains_found,
            "domains_saved": last_scan_row.domains_saved,
            "source": last_scan_row.source,
        }

    return {
        "scanning": _scan_running,
        "total_domains": total,
        "by_status": by_status,
        "last_scan": last_scan_info,
    }
