import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from database import get_db
from models import Domain, OutreachLog
from outreach.whois_lookup import lookup_whois
from outreach.mailer import send_outreach_email

router = APIRouter(prefix="/api/outreach", tags=["outreach"])
logger = logging.getLogger(__name__)


@router.get("/{domain_id}/whois")
async def get_whois(domain_id: int, db: Session = Depends(get_db)):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")

    result = await lookup_whois(d.name)

    # Cache owner info in DB
    if result.get("registrant_email"):
        d.owner_email = result["registrant_email"]
        d.owner_name = result.get("registrant_name")
        d.registrar = result.get("registrar")
        db.commit()

    return result


@router.post("/{domain_id}/send")
async def send_outreach(
    domain_id: int,
    asking_price: float = Body(..., embed=True),
    template: str = Body("initial_offer", embed=True),
    to_email: str = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")

    email = to_email or d.owner_email
    if not email:
        # Try WHOIS lookup
        whois_data = await lookup_whois(d.name)
        email = whois_data.get("registrant_email")
        if email:
            d.owner_email = email
            d.owner_name = whois_data.get("registrant_name")
            db.commit()

    if not email:
        raise HTTPException(
            status_code=400,
            detail="No owner email found. Try the WHOIS lookup first or provide to_email manually."
        )

    result = await send_outreach_email(
        to_email=email,
        to_name=d.owner_name or "Domain Owner",
        domain_name=d.name,
        asking_price=asking_price,
        template_name=template,
    )

    log = OutreachLog(
        domain_id=d.id,
        owner_email=email,
        template_used=template,
        status="sent" if result["sent"] else "preview",
        asking_price=asking_price,
        body=result.get("preview", ""),
    )
    db.add(log)
    db.commit()

    return {
        "domain": d.name,
        "to_email": email,
        "sent": result["sent"],
        "preview": result.get("preview"),
        "error": result.get("error"),
    }


@router.get("/{domain_id}/history")
async def outreach_history(domain_id: int, db: Session = Depends(get_db)):
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")
    logs = db.query(OutreachLog).filter(OutreachLog.domain_id == domain_id).all()
    return [
        {
            "id": l.id,
            "owner_email": l.owner_email,
            "template_used": l.template_used,
            "sent_at": l.sent_at.isoformat() if l.sent_at else None,
            "status": l.status,
            "asking_price": l.asking_price,
        }
        for l in logs
    ]
