from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import Domain, DomainScore
import json

router = APIRouter(prefix="/api/domains", tags=["domains"])


def _domain_to_dict(d: Domain) -> dict:
    breakdown = {}
    if d.score_breakdown:
        try:
            breakdown = json.loads(d.score_breakdown)
        except Exception:
            pass
    return {
        "id": d.id,
        "name": d.name,
        "sld": d.sld,
        "tld": d.tld,
        "score": d.score,
        "estimated_value": d.estimated_value,
        "status": d.status,
        "source": d.source,
        "backlink_count": d.backlink_count,
        "domain_age_years": d.domain_age_years,
        "owner_email": d.owner_email,
        "owner_name": d.owner_name,
        "registrar": d.registrar,
        "discovered_at": d.discovered_at.isoformat() if d.discovered_at else None,
        "purchased_at": d.purchased_at.isoformat() if d.purchased_at else None,
        "purchase_price": d.purchase_price,
        "sold_at": d.sold_at.isoformat() if d.sold_at else None,
        "sold_price": d.sold_price,
        "score_breakdown": breakdown,
        "lapsed_score": d.lapsed_score,
        "lapsed_label": d.lapsed_label,
        "wayback_snapshots": d.wayback_snapshots,
        "wayback_first_seen": d.wayback_first_seen,
        "wayback_last_seen": d.wayback_last_seen,
        "prev_owner_name": d.prev_owner_name,
        "prev_owner_email": d.prev_owner_email,
        "prev_owner_country": d.prev_owner_country,
    }


@router.get("")
async def list_domains(
    status: str = Query(None),
    min_score: float = Query(0),
    tld: str = Query(None),
    lapsed: str = Query(None),   # HOT | WARM | LUKEWARM | COLD
    sort: str = Query("score"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Domain)
    if status:
        q = q.filter(Domain.status == status)
    if min_score > 0:
        q = q.filter(Domain.score >= min_score)
    if tld:
        q = q.filter(Domain.tld == tld.lower().lstrip("."))
    if lapsed:
        q = q.filter(Domain.lapsed_label == lapsed.upper())

    if sort == "score":
        q = q.order_by(desc(Domain.score))
    elif sort == "value":
        q = q.order_by(desc(Domain.estimated_value))
    elif sort == "age":
        q = q.order_by(desc(Domain.domain_age_years))
    elif sort == "discovered":
        q = q.order_by(desc(Domain.discovered_at))

    total = q.count()
    domains = q.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "domains": [_domain_to_dict(d) for d in domains],
    }


@router.get("/{domain_id}")
async def get_domain(domain_id: int, db: Session = Depends(get_db)):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Domain not found")
    return _domain_to_dict(d)


@router.patch("/{domain_id}/status")
async def update_status(
    domain_id: int,
    status: str = Query(...),
    db: Session = Depends(get_db),
):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Domain not found")
    allowed = {"available", "watchlist", "purchased", "sold", "passed"}
    if status not in allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Status must be one of {allowed}")
    d.status = status
    db.commit()
    return {"id": domain_id, "status": status}
