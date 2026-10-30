import os
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

# The .env file must sit in the project's top folder (next to wsgi.py).
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_env():
    """Read .env into the environment.

    Handles the usual Windows problems: a UTF-8 BOM, a file saved as UTF-16 (for example by
    PowerShell's `>` redirect), and an empty variable already set in the system, which would
    otherwise hide the value in the file.
    """
    if not ENV_PATH.exists():
        return
    raw = ENV_PATH.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return
    for key, value in dotenv_values(stream=StringIO(text)).items():
        if value is not None:
            os.environ[key] = value.strip()


_load_env()


def _database_url():
    url = os.environ.get("DATABASE_URL") or "sqlite:///express_mtaani.db"
    # Use the psycopg 3 driver for PostgreSQL URLs.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url()
    GEOAPIFY_API_KEY = os.environ.get("GEOAPIFY_API_KEY", "")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("APP_ENV") == "production"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get("APP_ENV") == "production"

    # Rider matching: a rider sees new orders whose shop is within this many km of their last location.
    NEARBY_RADIUS_KM = float(os.environ.get("NEARBY_RADIUS_KM", "6"))
    # A rider counts as "online" only if their location was updated within this many seconds.
    RIDER_FRESH_SECONDS = int(os.environ.get("RIDER_FRESH_SECONDS", "120"))
    MAX_ACTIVE_ORDERS_PER_RIDER = 1

    # Delivery fee in whole KES: base + per-km (straight-line shop to customer), rounded up to 10.
    DELIVERY_BASE_FEE = int(os.environ.get("DELIVERY_BASE_FEE", "100"))
    DELIVERY_PER_KM = int(os.environ.get("DELIVERY_PER_KM", "30"))
