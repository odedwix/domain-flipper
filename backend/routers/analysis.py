"""
Analysis endpoints — recommendation, comparables, portfolio health.
"""

from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from database import get_db
from models import Domain
from valuation.recommendation import analyze, portfolio_health
from valuation.comparables import get_comparable_sales
from valuation.signals import enrich_domain, signals_to_score_adjustments
from datetime import datetime

router = APIRouter(prefix="/api/analyze", tags=["analysis"])


@router.get("/{domain_id}")
async def analyze_domain(
    domain_id: int,
    weekly_budget: float = 50.0,
    db: Session = Depends(get_db),
):
    """Full buy/skip analysis for a domain already in the DB."""
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Domain not found")

    domains_owned = db.query(Domain).filter(Domain.status == "purchased").count()

    # Run comparables + enrichment signals in parallel
    comps, enrichment = await __import__('asyncio').gather(
        get_comparable_sales(d.name),
        enrich_domain(d.name, expiry_date=d.whois_raw and __import__('json').loads(d.whois_raw or '{}').get('expiration_date')),
    )
    adjustments = signals_to_score_adjustments(enrichment)

    result = analyze(
        domain=d.name,
        age_years=d.domain_age_years,
        backlink_count=d.backlink_count,
        domain_authority=d.domain_authority,
        comparable_avg=comps.get("avg_sale_price"),
        weekly_budget_remaining=weekly_budget,
        domains_owned=domains_owned,
    )

    # Apply signal adjustments to score and decision
    result["score"] = round(min(100, max(0, result["score"] + adjustments["net_adjustment"])), 1)
    if adjustments["hard_stop"]:
        result["decision"] = "SKIP"
        result["confidence"] = 99
        result["reason"] = adjustments["flags"][0]

    result["comparables"] = comps
    result["enrichment"]  = enrichment
    result["adjustments"] = adjustments
    return result


@router.post("/quick")
async def quick_analyze(
    domain: str = Body(..., embed=True),
    weekly_budget: float = Body(50.0, embed=True),
    db: Session = Depends(get_db),
):
    """Analyze any domain name — doesn't need to be in the DB yet."""
    import asyncio
    domains_owned = db.query(Domain).filter(Domain.status == "purchased").count()

    comps, enrichment = await asyncio.gather(
        get_comparable_sales(domain),
        enrich_domain(domain),
    )
    adjustments = signals_to_score_adjustments(enrichment)

    result = analyze(
        domain=domain,
        comparable_avg=comps.get("avg_sale_price"),
        weekly_budget_remaining=weekly_budget,
        domains_owned=domains_owned,
    )

    result["score"] = round(min(100, max(0, result["score"] + adjustments["net_adjustment"])), 1)
    if adjustments["hard_stop"]:
        result["decision"] = "SKIP"
        result["confidence"] = 99
        result["reason"] = adjustments["flags"][0]

    result["comparables"]  = comps
    result["enrichment"]   = enrichment
    result["adjustments"]  = adjustments
    return result


@router.get("/portfolio/health")
async def portfolio_health_check(db: Session = Depends(get_db)):
    """Check portfolio concentration risk, burn rate, and stale inventory."""
    purchased = db.query(Domain).filter(Domain.status == "purchased").all()

    domain_list = []
    for d in purchased:
        days_held = (datetime.utcnow() - d.purchased_at).days if d.purchased_at else 0
        domain_list.append({
            "name": d.name,
            "purchase_price": d.purchase_price or 10.98,
            "days_held": days_held,
            "status": d.status,
        })

    return portfolio_health(domain_list)
