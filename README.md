# Domain Flipper

A full-stack platform for discovering, scoring, buying, and selling expired domains — built for Israel-based domain investors.

## What it does

- **Scans 7 sources** in parallel for expired/expiring domains: ExpiredDomains.net deleted list, grace-period expiring list, GoDaddy auctions with bids, Namecheap auctions, Dynadot closeout, Sedo expiring, and WhoisFreaks
- **Scores every domain** 0–100 across TLD, length, brandability, keywords, backlinks, age, and domain authority
- **Enriches with signals**: Open PageRank, Wayback Machine history, WHOIS company lookup
- **Lapsed-by-mistake scoring**: HOT / WARM / LUKEWARM / COLD — detects domains that expired accidentally (active Wayback history, previously held by a company, recent lapse)
- **Bulk availability verification**: checks all domains against Namecheap's live API and removes taken ones automatically after every scan
- **Buys domains** via Namecheap API (live mode, real purchases)
- **Lists for sale** via Afternic nameservers + GoDaddy aftermarket API + Sedo
- **Outreach** to previous owners via email (SendGrid)
- **AI recommendations** per domain

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | Vanilla JS SPA (no framework) |
| Scheduler | APScheduler (scans every 2h, follow-up emails daily 9am) |
| Domain registration | Namecheap XML API |
| Listing | Afternic nameservers + GoDaddy aftermarket API |
| Enrichment | Open PageRank, Wayback Machine CDX, RDAP/WHOIS |
| Scraping | httpx + BeautifulSoup (expireddomains.net) |

## Setup

### 1. Install dependencies

```bash
cd backend
pip install -r ../requirements.txt
```

### 2. Configure `.env`

Copy the template and fill in your keys:

```bash
cp .env.example .env   # or edit .env directly
```

| Variable | Required | Description |
|----------|----------|-------------|
| `NAMECHEAP_API_USER` | Yes | Your Namecheap username |
| `NAMECHEAP_API_KEY` | Yes | Namecheap API key (enable in account settings) |
| `NAMECHEAP_CLIENT_IP` | Yes | Your public IP (must be whitelisted in Namecheap) |
| `NAMECHEAP_SANDBOX` | Yes | `false` for real purchases, `true` for testing |
| `NAMECHEAP_REG_*` | Yes | Registrant contact details |
| `EXPIREDDOMAINS_SESSION_COOKIE` | Yes | `ef_session` cookie from expireddomains.net |
| `GODADDY_API_KEY` | Recommended | From developer.godaddy.com — enables aftermarket listing |
| `GODADDY_API_SECRET` | Recommended | Pair with above |
| `GODADDY_ENVIRONMENT` | Recommended | `production` |
| `OPENPAGERANK_API_KEY` | Optional | Free at domcop.com/openpagerank — 10k req/hr |
| `WHOISFREAKS_API_KEY` | Optional | Free at whoisfreaks.com — 10k/month |
| `SENDGRID_API_KEY` | Optional | For outreach emails |
| `SEDO_*` | Optional | Sedo marketplace listing |

### 3. Run

```bash
# Using the macOS dock app (recommended)
open "/Applications/Domain Flipper.app"

# Or manually
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000**

## Domain scoring

Each domain is scored 0–100 from these signals:

| Signal | Max points | Notes |
|--------|-----------|-------|
| TLD | 100 | .com = 100, .io = 65, .net = 60 … |
| Length | 100 | 6–9 chars optimal |
| Keywords | 100 | NLTK English word match + commercial keyword list |
| Brandability | 100 | Pronounceable, no hyphens, dictionary word |
| Backlinks | 100 | Majestic BL count from expireddomains.net |
| Age | 100 | Years since registration |
| Domain authority | bonus | Open PageRank score |

Only domains scoring ≥ 50 are saved. Quality gate rejects gibberish, hyphens, SLD > 15 chars, and >40% digits.

## Lapsed-by-mistake scoring

Runs separately via **🔥 Lapse Scan**. Scores each domain 0–100:

| Signal | Max | What it means |
|--------|-----|---------------|
| Wayback snapshots | 30 | Domain had real website content |
| Recency of last snapshot | 30 | Was active recently before lapsing |
| Company registrant | 20 | Held by a business, not an individual |
| Years held | 15 | Owned for many years = not speculative |
| Email hint | 5 | Registrant email suggests corporate use |

**HOT** (≥75): owner very likely wants it back — contact them  
**WARM** (≥50): worth reaching out  
**LUKEWARM** (≥30): possible  
**COLD** (<30): probably intentional lapse

## Purchase flow

1. Click **Buy** on a domain (only shown for directly-registrable domains)
2. Confirm in the modal — shows LIVE MODE warning
3. App checks availability via Namecheap, then registers
4. Domain status → `purchased`, nameservers set to Afternic automatically

## Listing flow

1. Click **🚀 List for Sale** on a purchased domain
2. Enter asking price
3. App sets nameservers to `ns1.afternic.com` / `ns2.afternic.com`
4. GoDaddy aftermarket API called to set price (works for GoDaddy-registered domains)
5. Afternic claim page opens automatically in browser for price verification
6. Parked "For Sale" HTML page generated for download

## Source actions by type

| Source | What to do | How |
|--------|-----------|-----|
| `godaddy_auction` | Bid on GoDaddy | Opens auction page |
| `namecheap_auction` | Bid on Namecheap | Opens marketplace |
| `sedo_expiring` | Bid on Sedo | Opens Sedo search |
| `dynadot_closeout` | Buy on Dynadot | Opens closeout page |
| `expiring` | Backorder via Namecheap | Opens Namecheap backorder |
| `expireddomains` | Register directly | Namecheap API |

## Project structure

```
domain_flipping/
├── backend/
│   ├── main.py              # FastAPI app + scheduler
│   ├── config.py            # Settings from .env
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # DB session
│   ├── routers/
│   │   ├── domains.py       # CRUD, filters, status
│   │   ├── scan.py          # Scan trigger + status
│   │   ├── purchase.py      # Buy + bulk availability check
│   │   ├── listing.py       # List for sale (Afternic/Sedo)
│   │   ├── enrich.py        # PageRank + lapsed enrichment
│   │   ├── outreach.py      # Email outreach
│   │   └── analysis.py      # AI recommendations
│   ├── scrapers/
│   │   ├── expireddomains.py # 6 sources from expireddomains.net
│   │   └── whoisfreaks.py   # WhoisFreaks expiring domains
│   ├── valuation/
│   │   ├── scorer.py        # Domain scoring algorithm
│   │   ├── signals.py       # Wayback Machine enrichment
│   │   ├── whois_lookup.py  # RDAP/WHOIS + lapsed scoring
│   │   ├── pagerank.py      # Open PageRank batch lookup
│   │   ├── comparables.py   # Comparable sales (Namebio)
│   │   └── recommendation.py # AI recommendation engine
│   └── purchase/
│       ├── namecheap.py     # Namecheap XML API
│       ├── afternic.py      # Nameserver-based Afternic listing
│       ├── godaddy.py       # GoDaddy aftermarket API
│       ├── sedo.py          # Sedo API
│       └── parked_page.py   # For Sale landing page generator
├── frontend/
│   └── index.html           # Single-file SPA
├── icon_build/              # App icon assets
├── icon.svg                 # Source icon
├── run.sh                   # Manual start script
└── .env                     # API keys (never commit)
```

## macOS dock app

`/Applications/Domain Flipper.app` — Automator app that:
- Kills any existing process on port 8000
- Starts a fresh uvicorn server using Homebrew's Python
- Waits up to 15 seconds for startup
- Opens http://localhost:8000 in your browser
