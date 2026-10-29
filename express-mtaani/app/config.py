import os

from dotenv import load_dotenv

load_dotenv()


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
