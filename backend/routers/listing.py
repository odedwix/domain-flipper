"""
Auto-listing router: one endpoint that does everything after a purchase.
POST /api/list/{domain_id}  →  Afternic nameservers + Sedo listing + parked page
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from database import get_db
from models import Domain
from purchase.afternic import list_on_afternic
from purchase.godaddy import create_aftermarket_listing
from purchase.sedo import list_on_sedo
from purchase.parked_page import generate_parked_page
from config import get_settings

router = APIRouter(prefix="/api/list", tags=["listing"])
logger = logging.getLogger(__name__)


@router.post("/{domain_id}")
async def auto_list(
    domain_id: int,
    asking_price: float = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    After buying a domain, call this to:
    1. Point nameservers to Afternic (biggest buyer network)
    2. List on Sedo
    3. Generate a parked 'For Sale' landing page
    """
    d = db.query(Domain).filter(Domain.id == domain_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")

    settings = get_settings()
    results = {}

    # 1 — Afternic via nameserver update
    afternic = await list_on_afternic(d.name, asking_price)
    results["afternic"] = afternic

    # 1b — GoDaddy aftermarket API to set the price (works alongside nameservers)
    godaddy = await create_aftermarket_listing(d.name, asking_price)
    results["godaddy"] = godaddy

    # 2 — Sedo (if configured)
    sedo = await list_on_sedo(d.name, asking_price)
    results["sedo"] = sedo

    # 3 — Parked page HTML
    formspree_id = getattr(settings, "formspree_id", "YOUR_FORM_ID")
    parked_html = generate_parked_page(d.name, asking_price, formspree_id)
    results["parked_page"] = {
        "html_length": len(parked_html),
        "preview_snippet": parked_html[:200],
    }

    # Update domain with asking price
    d.sold_price = None  # not sold yet
    db.commit()

    listed_on = [k for k, v in results.items() if v.get("success")]
    not_listed = [k for k, v in results.items() if not v.get("success") and k != "parked_page"]

    return {
        "domain": d.name,
        "asking_price": asking_price,
        "listed_on": listed_on,
        "not_listed": not_listed,
        "details": results,
        "parked_html": parked_html,
        "next_steps": _next_steps(results, d.name),
    }


def _next_steps(results: dict, domain: str) -> list[str]:
    steps = []
    if results.get("afternic", {}).get("success"):
        steps.append(
            f"Afternic: log into afternic.com, find {domain}, set your price. "
            "It will appear on GoDaddy + 100 partner registrars within 24h."
        )
    else:
        steps.append(
            "Afternic: nameserver update failed — manually add domain at afternic.com "
            "or check your Namecheap API config."
        )
    if not results.get("sedo", {}).get("success"):
        steps.append("Sedo: add SEDO_PARTNER_ID + SEDO_SIGN_KEY to .env to enable auto-listing.")
    steps.append(
        "Parked page: download the HTML and host it (GitHub Pages, Netlify, or Cloudflare Pages — all free). "
        "Get a contact form at formspree.io (free) and add your form ID to .env as FORMSPREE_ID."
    )
    return steps
