import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Domain
from purchase.namecheap import check_availability, register_domain

router = APIRouter(prefix="/api/purchase", tags=["purchase"])
logger = logging.getLogger(__name__)


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
