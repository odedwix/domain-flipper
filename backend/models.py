from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)   # full domain e.g. "example.com"
    sld = Column(String, nullable=False)    # second-level e.g. "example"
    tld = Column(String, nullable=False)    # e.g. "com"
    source = Column(String, default="expireddomains")
    discovered_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    domain_age_years = Column(Float, nullable=True)
    backlink_count = Column(Integer, nullable=True)
    domain_authority = Column(Float, nullable=True)
    status = Column(String, default="available")  # available | watchlist | purchased | sold | passed
    purchased_at = Column(DateTime, nullable=True)
    purchase_price = Column(Float, nullable=True)
    sold_at = Column(DateTime, nullable=True)
    sold_price = Column(Float, nullable=True)
    owner_email = Column(String, nullable=True)
    owner_name = Column(String, nullable=True)
    registrar = Column(String, nullable=True)
    whois_raw = Column(Text, nullable=True)

    # Valuation
    score = Column(Float, default=0.0)
    estimated_value = Column(Float, default=0.0)
    score_breakdown = Column(Text, nullable=True)  # JSON string

    # Liquidity & market signals (computed at scan time)
    liquidity_score = Column(Integer, nullable=True)      # 0–100
    liquidity_label = Column(String, nullable=True)       # LIQUID | MODERATE | SLOW | ILLIQUID
    brand_conflict = Column(Boolean, nullable=True)       # conflicts with a major brand
    brand_conflict_term = Column(String, nullable=True)   # which brand
    hot_niches = Column(String, nullable=True)            # JSON list of matched niche keywords
    trend_score = Column(Integer, nullable=True)          # Google Trends 0–100
    trend_rising = Column(Boolean, nullable=True)         # rising in last 3 months

    # Lapsed-by-mistake enrichment
    lapsed_score = Column(Integer, nullable=True)        # 0–100
    lapsed_label = Column(String, nullable=True)         # HOT / WARM / LUKEWARM / COLD
    wayback_snapshots = Column(Integer, nullable=True)
    wayback_first_seen = Column(String, nullable=True)
    wayback_last_seen = Column(String, nullable=True)
    prev_owner_name = Column(String, nullable=True)
    prev_owner_email = Column(String, nullable=True)
    prev_owner_country = Column(String, nullable=True)

    scores = relationship("DomainScore", back_populates="domain", cascade="all, delete-orphan")
    outreach = relationship("OutreachLog", back_populates="domain", cascade="all, delete-orphan")


class DomainScore(Base):
    __tablename__ = "domain_scores"

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    scored_at = Column(DateTime, default=datetime.utcnow)

    tld_score = Column(Float, default=0.0)
    length_score = Column(Float, default=0.0)
    word_score = Column(Float, default=0.0)
    brand_score = Column(Float, default=0.0)
    backlink_score = Column(Float, default=0.0)
    age_score = Column(Float, default=0.0)
    keyword_score = Column(Float, default=0.0)
    total_score = Column(Float, default=0.0)

    domain = relationship("Domain", back_populates="scores")


class OutreachLog(Base):
    __tablename__ = "outreach_log"

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False)
    owner_email = Column(String, nullable=False)
    template_used = Column(String, default="initial_offer")
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="sent")  # sent | replied | bounced
    asking_price = Column(Float, nullable=True)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)

    domain = relationship("Domain", back_populates="outreach")


class ScanLog(Base):
    __tablename__ = "scan_log"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    domains_found = Column(Integer, default=0)
    domains_scored = Column(Integer, default=0)
    domains_saved = Column(Integer, default=0)
    source = Column(String, default="expireddomains")
    status = Column(String, default="running")  # running | done | error
    error_msg = Column(Text, nullable=True)
