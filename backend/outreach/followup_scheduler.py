"""
Auto follow-up email drip for purchased domains.

Job runs daily. For any domain where:
  - status = purchased
  - an initial_offer email was sent 7+ days ago
  - no follow_up has been sent yet
  - no reply received

It automatically sends the follow_up template at a 20% lower price.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Domain, OutreachLog
from outreach.mailer import send_outreach_email

logger = logging.getLogger(__name__)

FOLLOW_UP_DAYS = 7
FOLLOW_UP_DISCOUNT = 0.80  # 20% lower than initial ask


async def run_followup_job():
    db: Session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=FOLLOW_UP_DAYS)

        # Find initial offers sent before the cutoff
        initial_logs = (
            db.query(OutreachLog)
            .filter(
                OutreachLog.template_used == "initial_offer",
                OutreachLog.sent_at <= cutoff,
                OutreachLog.status == "sent",
            )
            .all()
        )

        for log in initial_logs:
            domain = db.query(Domain).filter(Domain.id == log.domain_id).first()
            if not domain or domain.status != "purchased":
                continue

            # Skip if already followed up
            already = (
                db.query(OutreachLog)
                .filter(
                    OutreachLog.domain_id == log.domain_id,
                    OutreachLog.template_used == "follow_up",
                )
                .first()
            )
            if already:
                continue

            # Skip if replied
            if log.status == "replied":
                continue

            asking_price = round((log.asking_price or 200) * FOLLOW_UP_DISCOUNT, -1)

            logger.info(f"Sending follow-up for {domain.name} to {log.owner_email} at ${asking_price}")

            result = await send_outreach_email(
                to_email=log.owner_email,
                to_name=domain.owner_name or "Domain Owner",
                domain_name=domain.name,
                asking_price=asking_price,
                template_name="follow_up",
            )

            follow_up_log = OutreachLog(
                domain_id=domain.id,
                owner_email=log.owner_email,
                template_used="follow_up",
                status="sent" if result["sent"] else "preview",
                asking_price=asking_price,
                body=result.get("preview", ""),
            )
            db.add(follow_up_log)
            db.commit()

            if result["sent"]:
                logger.info(f"Follow-up sent for {domain.name}")
            else:
                logger.warning(f"Follow-up preview only for {domain.name}: {result.get('error')}")

    except Exception as e:
        logger.exception("Follow-up job error")
    finally:
        db.close()
