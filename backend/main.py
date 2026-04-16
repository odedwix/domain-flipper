import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Ensure we can import sibling modules
sys.path.insert(0, str(Path(__file__).parent))

from database import Base, engine
from config import get_settings
from routers import domains, scan, purchase, outreach, listing, analysis, enrich

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

settings = get_settings()

# ── Scheduler ──────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()


async def scheduled_scan():
    """Periodic background scan job."""
    from routers.scan import _run_scan
    logger.info("Scheduled scan triggered")
    await _run_scan(use_demo=not settings.expireddomains_session_cookie)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all DB tables
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")

    # Download NLTK word corpus (needed for dictionary scoring)
    try:
        import nltk
        nltk.download("words", quiet=True)
        logger.info("NLTK words corpus ready")
    except Exception as e:
        logger.warning(f"Could not download NLTK words: {e}")

    # Start background scheduler
    scheduler.add_job(
        scheduled_scan,
        "interval",
        hours=settings.scan_interval_hours,
        id="domain_scan",
    )
    # Follow-up email drip — runs daily at 9am
    from outreach.followup_scheduler import run_followup_job
    scheduler.add_job(run_followup_job, "cron", hour=9, minute=0, id="followup_drip")
    scheduler.start()
    logger.info(f"Scheduler started — scanning every {settings.scan_interval_hours}h, follow-ups daily at 9am")

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped")


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Domain Flipper",
    description="Scan, score, buy, and sell expired domains from Israel",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Settings endpoint ─────────────────────────────────────────────────────────
from fastapi import APIRouter as _AR
_settings_router = _AR(prefix="/api/settings", tags=["settings"])

@_settings_router.get("")
def get_public_settings():
    return {"namecheap_sandbox": settings.namecheap_sandbox}

# ── API Routers ────────────────────────────────────────────────────────────────
app.include_router(_settings_router)
app.include_router(domains.router)
app.include_router(scan.router)
app.include_router(purchase.router)
app.include_router(outreach.router)
app.include_router(listing.router)
app.include_router(analysis.router)
app.include_router(enrich.router)

# ── Frontend static files ──────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{path:path}")
    async def catch_all(path: str):
        file_path = FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
