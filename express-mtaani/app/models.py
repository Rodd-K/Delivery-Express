import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

ROLES = ("customer", "rider", "admin")

CATEGORIES = [
    ("food", "Food"),
    ("groceries", "Groceries"),
    ("shopping", "Shopping"),
    ("household", "Household"),
]
CATEGORY_LABELS = dict(CATEGORIES)

STATUS_LABELS = {
    "placed": "Order placed",
    "accepted": "Rider assigned",
    "on_the_way": "On the way",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}

# Explicit transitions only. Nobody can set an arbitrary status.
TRANSITIONS = {
    "placed": {"accepted", "cancelled"},
    "accepted": {"on_the_way", "cancelled", "placed"},  # "placed" = rider released the order
    "on_the_way": {"delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}

# Statuses where the rider's location is shared with the customer.
LIVE_STATUSES = {"accepted", "on_the_way"}


def utcnow():
    """Naive UTC timestamp (works the same on SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    approved = db.Column(db.Boolean, nullable=False, default=True)  # riders start unapproved
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    # Rider presence (last known position, used to match nearby orders)
    online = db.Column(db.Boolean, nullable=False, default=False)
    last_lat = db.Column(db.Float)
    last_lng = db.Column(db.Float)
    last_seen_at = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):  # Flask-Login
        return bool(self.active)

    @property
    def first_name(self):
        return (self.name or "").split(" ")[0]

    def is_fresh(self):
        """Rider is online and their location is recent."""
        if not (self.online and self.last_seen_at and self.last_lat is not None):
            return False
        limit = timedelta(seconds=current_app.config["RIDER_FRESH_SECONDS"])
        return utcnow() - self.last_seen_at <= limit

    def set_position(self, lat, lng):
        self.last_lat, self.last_lng, self.last_seen_at = lat, lng, utcnow()


@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    if user and user.active and (user.role != "rider" or user.approved):
        return user
    return None


class Shop(db.Model):
    __tablename__ = "shops"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")
    address = db.Column(db.String(255), nullable=False, default="")
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    products = db.relationship("Product", back_populates="shop", lazy="dynamic")


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shops.id"), nullable=False, index=True)
    category = db.Column(db.String(30), nullable=False, default="food", index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")
    price = db.Column(db.Integer, nullable=False)  # whole Kenyan shillings
    image_url = db.Column(db.String(500))
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    shop = db.relationship("Shop", back_populates="products")

    @property
    def category_label(self):
        return CATEGORY_LABELS.get(self.category, self.category.title())


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    # Unguessable token for the customer's tracking link (never use the numeric id publicly).
    public_token = db.Column(
        db.String(64), unique=True, nullable=False, index=True,
        default=lambda: secrets.token_urlsafe(16),
    )

    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    rider_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shops.id"), nullable=False)

    # Snapshots, so later edits to a profile or shop never change an existing order.
    customer_name = db.Column(db.String(80), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    pickup_name = db.Column(db.String(120), nullable=False)
    pickup_lat = db.Column(db.Float, nullable=False)
    pickup_lng = db.Column(db.Float, nullable=False)
    dest_address = db.Column(db.String(255), nullable=False)
    dest_lat = db.Column(db.Float, nullable=False)
    dest_lng = db.Column(db.Float, nullable=False)

    subtotal = db.Column(db.Integer, nullable=False)
    delivery_fee = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(30), nullable=False, default="cash_on_delivery")
    payment_status = db.Column(db.String(20), nullable=False, default="unpaid")  # unpaid | paid
    cash_collected_at = db.Column(db.DateTime)

    status = db.Column(db.String(20), nullable=False, default="placed", index=True)

    rider_lat = db.Column(db.Float)
    rider_lng = db.Column(db.Float)
    rider_updated_at = db.Column(db.DateTime)
    eta_seconds = db.Column(db.Integer)
    distance_m = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    accepted_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)

    customer = db.relationship("User", foreign_keys=[customer_id])
    rider = db.relationship("User", foreign_keys=[rider_id])
    shop = db.relationship("Shop")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def items_summary(self):
        return ", ".join(f"{i.quantity} x {i.name}" for i in self.items)

    def clear_rider_location(self):
        self.rider_lat = self.rider_lng = None
        self.rider_updated_at = None
        self.eta_seconds = self.distance_m = None

    def public_dict(self):
        """What the customer's tracking page is allowed to see (no phone number)."""
        rider = None
        if self.status in LIVE_STATUSES and self.rider_lat is not None:
            rider = {
                "lat": self.rider_lat,
                "lng": self.rider_lng,
                "updated_at": iso(self.rider_updated_at),
                "eta_seconds": self.eta_seconds,
                "distance_m": self.distance_m,
            }
        return {
            "status": self.status,
            "status_label": self.status_label,
            "rider_name": self.rider.first_name if self.rider and self.status in LIVE_STATUSES else None,
            "pickup": {"name": self.pickup_name, "lat": self.pickup_lat, "lng": self.pickup_lng},
            "dest": {"address": self.dest_address, "lat": self.dest_lat, "lng": self.dest_lng},
            "rider": rider,
            "server_time": iso(utcnow()),
        }


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    name = db.Column(db.String(120), nullable=False)       # product name at time of order
    unit_price = db.Column(db.Integer, nullable=False)     # price at time of order
    quantity = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", back_populates="items")

    @property
    def line_total(self):
        return self.unit_price * self.quantity
