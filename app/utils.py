import math
import re

# Rough bounding box around Kenya: (lat_min, lat_max, lng_min, lng_max).
KENYA_BOUNDS = (-5.0, 5.6, 33.8, 42.0)

_PHONE_RE = re.compile(r"^(?:\+?254|0)?([71]\d{8})$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def parse_coord(lat, lng, bounds=None):
    """Return (lat, lng) as floats, or None if invalid or outside the bounds."""
    if isinstance(lat, bool) or isinstance(lng, bool):
        return None
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if bounds and not (bounds[0] <= lat <= bounds[1] and bounds[2] <= lng <= bounds[3]):
        return None
    return lat, lng


def normalize_phone(raw):
    """Accept 07xx, 01xx, 2547xx or +2547xx and return +254XXXXXXXXX, else None."""
    cleaned = re.sub(r"[\s\-()]", "", raw or "")
    match = _PHONE_RE.match(cleaned)
    return "+254" + match.group(1) if match else None


def valid_email(value):
    return bool(value and len(value) <= 120 and _EMAIL_RE.match(value))


def parse_int(value, low, high):
    """Return int within [low, high] or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def safe_next(target, fallback):
    """Only allow same-site relative redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return fallback


def haversine_km(lat1, lng1, lat2, lng2):
    """Straight-line distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def delivery_fee(km, base, per_km):
    """Whole KES: base + per-km for each started km, rounded up to the next 10."""
    raw = base + math.ceil(max(km, 0)) * per_km
    return int(math.ceil(raw / 10.0) * 10)


def kes(amount):
    return f"KES {int(amount):,}"
