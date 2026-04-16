from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

# .env lives one level up from backend/
ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    # Namecheap
    namecheap_api_user: str = ""
    namecheap_api_key: str = ""
    namecheap_client_ip: str = ""
    namecheap_sandbox: bool = True

    # Registrant contact info
    namecheap_reg_first_name: str = "John"
    namecheap_reg_last_name: str = "Doe"
    namecheap_reg_address: str = "123 Main St"
    namecheap_reg_city: str = "Tel Aviv"
    namecheap_reg_state: str = "Tel Aviv"
    namecheap_reg_postal: str = "12345"
    namecheap_reg_country: str = "IL"
    namecheap_reg_phone: str = "+972.501234567"
    namecheap_reg_email: str = "you@example.com"

    # GoDaddy
    godaddy_api_key: str = ""
    godaddy_api_secret: str = ""
    godaddy_environment: str = "test"

    # Moz
    moz_access_id: str = ""
    moz_secret_key: str = ""

    # WhoisXML
    whoisxml_api_key: str = ""

    # SendGrid
    sendgrid_api_key: str = ""
    outreach_from_email: str = ""
    outreach_from_name: str = "Domain Investor"

    # ExpiredDomains
    expireddomains_session_cookie: str = ""

    # Namebio comparable sales API (~$0.25–0.50 per lookup)
    namebio_api_key: str = ""
    namebio_email: str = ""

    # Open PageRank (free — domcop.com/openpagerank)
    openpagerank_api_key: str = ""

    # WhoisFreaks expired domains API (free — whoisfreaks.com)
    whoisfreaks_api_key: str = ""

    # Google Safe Browsing (free — console.cloud.google.com → enable Safe Browsing API)
    google_api_key: str = ""

    # DataForSEO keyword volume + CPC (~$0.02 per 100 keywords — dataforseo.com)
    dataforseo_email: str = ""
    dataforseo_password: str = ""

    # Sedo marketplace
    sedo_partner_id: str = ""
    sedo_sign_key: str = ""
    sedo_username: str = ""
    sedo_password: str = ""

    # Parked page contact form (formspree.io — free)
    formspree_id: str = "YOUR_FORM_ID"

    # App
    database_url: str = "sqlite:///./data/domains.db"
    scan_interval_hours: int = 6
    max_domains_per_scan: int = 500
    min_score_threshold: int = 35

    class Config:
        env_file = str(ENV_FILE)
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
