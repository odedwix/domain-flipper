import logging
import asyncio
import xml.etree.ElementTree as ET
import httpx
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import Domain
from purchase.namecheap import check_availability, register_domain, _get_url, _base_params

router = APIRouter(prefix="/api/purchase", tags=["purchase"])
logger = logging.getLogger(__name__)

NC_NS = "http://api.namecheap.com/xml.response"
_checking = False
_check_progress = {"done": 0, "total": 0, "removed": 0}


async def _batch_check_availability(names: list[str]) -> dict[str, bool]:
    """Check up to 50 domains in one Namecheap API call."""
    if not names:
        return {}
    params = _base_params()
    params["Command"] = "namecheap.domains.check"
    params["DomainList"] = ",".join(names[:50])
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(_get_url(), params=params)
        root = ET.fromstring(r.text)
        results = {}
        for el in root.findall(f".//{{{NC_NS}}}DomainCheckResult"):
            results[el.get("Domain")] = el.get("Available", "false").lower() == "true"
        return results
    except Exception as e:
        logger.error(f"Batch availability check failed: {e}")
        return {}


async def _run_availability_check():
    global _checking, _check_progress
    if _checking:
        return
    _checking = True
    db = SessionLocal()
    try:
        domains = db.query(Domain).filter(Domain.status == "available").all()
        names = [d.name for d in domains]
        _check_progress = {"done": 0, "total": len(names), "removed": 0}
        logger.info(f"Checking availability for {len(names)} domains")

        BATCH = 50
        for i in range(0, len(names), BATCH):
            batch = names[i:i + BATCH]
            results = await _batch_check_availability(batch)

            for domain in domains[i:i + BATCH]:
                avail = results.get(domain.name)
                if avail is False:  # explicitly not available → remove
                    db.delete(domain)
                    _check_progress["removed"] += 1

            db.commit()
            _check_progress["done"] = min(i + BATCH, len(names))
            logger.info(f"Availability check: {_check_progress['done']}/{len(names)}, removed {_check_progress['removed']}")
            await asyncio.sleep(0.5)

        logger.info(f"Availability check done — removed {_check_progress['removed']} taken domains")
    except Exception:
        logger.exception("Availability check error")
    finally:
        _checking = False
        db.close()


@router.post("/check-all")
async def check_all_availability(background_tasks: BackgroundTasks):
    """Batch-check all available domains against Namecheap and remove taken ones."""
    if _checking:
        return {"status": "already_running", "progress": _check_progress}
    background_tasks.add_task(_run_availability_check)
    return {"status": "started", "message": "Availability check started — taken domains will be removed"}


@router.get("/check-all/status")
async def check_all_status():
    return {"checking": _checking, "progress": _check_progress}


@router.get("/{domain_id}/check")
async def check_domain_availability(domain_id: int, db: Session = Depends(get_db)):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")
    result = await check_availability(d.name)
    return {"domain": d.name, **result}


@router.post("/{domain_id}/buy")
async def buy_domain(domain_id: int, years: int = 1, db: Session = Depends(get_db)):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")

    if d.status == "purchased":
        return {"success": False, "error": "Domain already purchased", "domain": d.name}

    # First check availability
    avail = await check_availability(d.name)
    if avail.get("error"):
        return {"success": False, "error": avail["error"], "domain": d.name}
    if not avail.get("available"):
        return {"success": False, "error": "Domain is no longer available", "domain": d.name, "available": False}

    # Register it
    result = await register_domain(d.name, years=years)

    if result["success"]:
        d.status = "purchased"
        d.purchased_at = datetime.utcnow()
        d.purchase_price = 10.98 * years  # Standard .com price
        db.commit()

    return {
        "domain": d.name,
        "success": result["success"],
        "order_id": result.get("order_id"),
        "error": result.get("error"),
        "purchase_price": d.purchase_price,
    }
