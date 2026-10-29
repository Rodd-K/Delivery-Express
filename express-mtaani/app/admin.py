from datetime import timedelta

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user
from sqlalchemy import func

from .access import home_for
from .extensions import db
from .models import (CATEGORIES, CATEGORY_LABELS, LIVE_STATUSES, STATUS_LABELS, TRANSITIONS,
                     Order, Product, Shop, User, utcnow)
from .utils import KENYA_BOUNDS, haversine_km, kes, parse_coord, parse_int

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def admin_only():
    """Every route in this blueprint requires a signed-in admin."""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.path))
    if current_user.role != "admin":
        abort(403)


def _today_start_utc():
    """Midnight in Nairobi (UTC+3), expressed in UTC."""
    local_now = utcnow() + timedelta(hours=3)
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3)


def _field(name, low, high):
    return (request.form.get(name) or "").strip()[:high] if high else (request.form.get(name) or "").strip()


# ---- Dashboard ----

@bp.get("/")
def dashboard():
    start = _today_start_utc()
    fresh_cutoff = utcnow() - timedelta(seconds=current_app.config["RIDER_FRESH_SECONDS"])
    stats = {
        "orders_today": Order.query.filter(Order.created_at >= start).count(),
        "active": Order.query.filter(Order.status.in_(["placed", "accepted", "on_the_way"])).count(),
        "waiting": Order.query.filter_by(status="placed").count(),
        "sales_today": db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(
            Order.status == "delivered", Order.delivered_at >= start).scalar(),
        "riders_online": User.query.filter(User.role == "rider", User.approved.is_(True), User.active.is_(True),
                                           User.online.is_(True), User.last_seen_at >= fresh_cutoff).count(),
        "pending_riders": User.query.filter_by(role="rider", approved=False).count(),
        "cash_to_chase": Order.query.filter_by(status="delivered", payment_status="unpaid").count(),
    }
    counts = dict(db.session.query(Order.status, func.count(Order.id)).group_by(Order.status).all())
    status_counts = [(key, label, counts.get(key, 0)) for key, label in STATUS_LABELS.items()]
    recent = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    shops = Shop.query.filter_by(is_active=True).all()
    page_data = {
        "riders_url": url_for("api.admin_riders"),
        "shops": [{"name": s.name, "lat": s.lat, "lng": s.lng} for s in shops],
        "center": {"lat": -1.286389, "lng": 36.817223},
    }
    return render_template("admin/dashboard.html", stats=stats, status_counts=status_counts,
                           max_count=max([c for _, _, c in status_counts] + [1]),
                           recent=recent, page_data=page_data, kes=kes)


# ---- Orders ----

@bp.get("/orders")
def orders():
    status = request.args.get("status") or ""
    query = Order.query
    if status in STATUS_LABELS:
        query = query.filter_by(status=status)
    else:
        status = ""
    rows = query.order_by(Order.created_at.desc()).limit(100).all()
    return render_template("admin/orders.html", orders=rows, status=status, statuses=STATUS_LABELS)


@bp.get("/orders/<int:order_id>")
def order_detail(order_id):
    order = db.get_or_404(Order, order_id)
    riders = User.query.filter_by(role="rider", approved=True, active=True).order_by(User.name).all()
    options = []
    for r in riders:
        km = None
        if r.is_fresh():
            km = round(haversine_km(r.last_lat, r.last_lng, order.pickup_lat, order.pickup_lng), 1)
        options.append({"rider": r, "km": km})
    options.sort(key=lambda o: (o["km"] is None, o["km"] or 0, o["rider"].name))
    return render_template("admin/order_detail.html", order=order, options=options,
                           can_assign=order.status in ("placed", "accepted"),
                           can_cancel="cancelled" in TRANSITIONS.get(order.status, set()))


@bp.post("/orders/<int:order_id>/assign")
def order_assign(order_id):
    order = db.get_or_404(Order, order_id)
    rider = db.session.get(User, parse_int(request.form.get("rider_id"), 1, 10**9) or 0)
    if order.status not in ("placed", "accepted"):
        flash("This order can no longer be assigned.", "error")
    elif not rider or rider.role != "rider" or not rider.approved or not rider.active:
        flash("Choose an approved rider.", "error")
    else:
        order.rider_id = rider.id
        order.status = "accepted"
        order.accepted_at = utcnow()
        order.clear_rider_location()
        db.session.commit()
        flash(f"Order #{order.id} assigned to {rider.name}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/cancel")
def order_cancel(order_id):
    order = db.get_or_404(Order, order_id)
    if "cancelled" not in TRANSITIONS.get(order.status, set()):
        flash("This order cannot be cancelled.", "error")
    else:
        order.status = "cancelled"
        order.clear_rider_location()
        db.session.commit()
        flash(f"Order #{order.id} cancelled.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/mark-paid")
def order_mark_paid(order_id):
    order = db.get_or_404(Order, order_id)
    if order.status == "delivered" and order.payment_status == "unpaid":
        order.payment_status = "paid"
        order.cash_collected_at = utcnow()
        db.session.commit()
        flash("Marked as paid.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


# ---- Products ----

def _product_from_form(product=None):
    f = request.form
    errors = []
    shop = db.session.get(Shop, parse_int(f.get("shop_id"), 1, 10**9) or 0)
    name = (f.get("name") or "").strip()
    description = (f.get("description") or "").strip()
    category = f.get("category") or ""
    price = parse_int(f.get("price"), 1, 1_000_000)
    image_url = (f.get("image_url") or "").strip()

    if not shop:
        errors.append("Choose a shop.")
    if not 2 <= len(name) <= 120:
        errors.append("Name must be 2 to 120 characters.")
    if len(description) > 255:
        errors.append("Description must be 255 characters or fewer.")
    if category not in CATEGORY_LABELS:
        errors.append("Choose a category.")
    if price is None:
        errors.append("Enter the price as whole shillings, for example 250.")
    if image_url and not (image_url.startswith("https://") and len(image_url) <= 500):
        errors.append("Image link must start with https:// (or leave it empty).")
    values = {"shop_id": f.get("shop_id", ""), "name": name, "description": description, "category": category,
              "price": f.get("price", ""), "image_url": image_url, "is_available": f.get("is_available") == "on"}
    if errors:
        return None, values, errors
    product = product or Product()
    product.shop_id, product.name, product.description = shop.id, name, description
    product.category, product.price = category, price
    product.image_url = image_url or None
    product.is_available = values["is_available"]
    return product, values, []


@bp.get("/products")
def products():
    shop_id = parse_int(request.args.get("shop"), 1, 10**9)
    query = Product.query
    if shop_id:
        query = query.filter_by(shop_id=shop_id)
    rows = query.order_by(Product.shop_id, Product.name).all()
    return render_template("admin/products.html", products=rows, shops=Shop.query.order_by(Shop.name).all(),
                           shop_id=shop_id, kes=kes)


@bp.route("/products/new", methods=["GET", "POST"])
def product_new():
    shops = Shop.query.order_by(Shop.name).all()
    values, errors = {"is_available": True, "category": "food"}, []
    if request.method == "POST":
        product, values, errors = _product_from_form()
        if product:
            db.session.add(product)
            db.session.commit()
            flash(f"Added {product.name}.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", values=values, errors=errors, shops=shops,
                           categories=CATEGORIES, editing=None), (400 if errors else 200)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def product_edit(product_id):
    product = db.get_or_404(Product, product_id)
    shops = Shop.query.order_by(Shop.name).all()
    values = {"shop_id": product.shop_id, "name": product.name, "description": product.description,
              "category": product.category, "price": product.price, "image_url": product.image_url or "",
              "is_available": product.is_available}
    errors = []
    if request.method == "POST":
        updated, values, errors = _product_from_form(product)
        if updated:
            db.session.commit()
            flash("Product updated.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", values=values, errors=errors, shops=shops,
                           categories=CATEGORIES, editing=product), (400 if errors else 200)


@bp.post("/products/<int:product_id>/toggle")
def product_toggle(product_id):
    product = db.get_or_404(Product, product_id)
    product.is_available = not product.is_available
    db.session.commit()
    return redirect(request.referrer or url_for("admin.products"))


# ---- Shops ----

def _shop_from_form(shop=None):
    f = request.form
    errors = []
    name = (f.get("name") or "").strip()
    description = (f.get("description") or "").strip()
    address = (f.get("address") or "").strip()
    coords = parse_coord(f.get("lat"), f.get("lng"), KENYA_BOUNDS)
    if not 2 <= len(name) <= 120:
        errors.append("Name must be 2 to 120 characters.")
    if len(description) > 255:
        errors.append("Description must be 255 characters or fewer.")
    if not 3 <= len(address) <= 255:
        errors.append("Enter the shop's address.")
    if not coords:
        errors.append("Click the map to set the shop's location (pickup point for riders).")
    values = {"name": name, "description": description, "address": address, "lat": f.get("lat", ""),
              "lng": f.get("lng", ""), "is_active": f.get("is_active") == "on"}
    if errors:
        return None, values, errors
    shop = shop or Shop()
    shop.name, shop.description, shop.address = name, description, address
    shop.lat, shop.lng = coords
    shop.is_active = values["is_active"]
    return shop, values, []


@bp.get("/shops")
def shops():
    return render_template("admin/shops.html", shops=Shop.query.order_by(Shop.name).all())


@bp.route("/shops/new", methods=["GET", "POST"])
def shop_new():
    values, errors = {"is_active": True, "lat": "", "lng": ""}, []
    if request.method == "POST":
        shop, values, errors = _shop_from_form()
        if shop:
            db.session.add(shop)
            db.session.commit()
            flash(f"Added {shop.name}.", "success")
            return redirect(url_for("admin.shops"))
    return render_template("admin/shop_form.html", values=values, errors=errors, editing=None,
                           page_data={"center": {"lat": -1.286389, "lng": 36.817223}}), (400 if errors else 200)


@bp.route("/shops/<int:shop_id>/edit", methods=["GET", "POST"])
def shop_edit(shop_id):
    shop = db.get_or_404(Shop, shop_id)
    values = {"name": shop.name, "description": shop.description, "address": shop.address,
              "lat": shop.lat, "lng": shop.lng, "is_active": shop.is_active}
    errors = []
    if request.method == "POST":
        updated, values, errors = _shop_from_form(shop)
        if updated:
            db.session.commit()
            flash("Shop updated.", "success")
            return redirect(url_for("admin.shops"))
    return render_template("admin/shop_form.html", values=values, errors=errors, editing=shop,
                           page_data={"center": {"lat": -1.286389, "lng": 36.817223}}), (400 if errors else 200)


# ---- Riders ----

@bp.get("/riders")
def riders():
    rows = User.query.filter_by(role="rider").order_by(User.approved.asc(), User.name).all()
    delivered = dict(db.session.query(Order.rider_id, func.count(Order.id))
                     .filter(Order.status == "delivered").group_by(Order.rider_id).all())
    return render_template("admin/riders.html", riders=rows, delivered=delivered)


def _rider_or_404(user_id):
    rider = db.get_or_404(User, user_id)
    if rider.role != "rider":
        abort(404)
    return rider


@bp.post("/riders/<int:user_id>/approve")
def rider_approve(user_id):
    rider = _rider_or_404(user_id)
    rider.approved = True
    db.session.commit()
    flash(f"{rider.name} can now sign in and take deliveries.", "success")
    return redirect(url_for("admin.riders"))


@bp.post("/riders/<int:user_id>/deactivate")
def rider_deactivate(user_id):
    rider = _rider_or_404(user_id)
    rider.active = False
    rider.online = False
    db.session.commit()
    flash(f"{rider.name} was deactivated.", "success")
    return redirect(url_for("admin.riders"))


@bp.post("/riders/<int:user_id>/activate")
def rider_activate(user_id):
    rider = _rider_or_404(user_id)
    rider.active = True
    db.session.commit()
    flash(f"{rider.name} was reactivated.", "success")
    return redirect(url_for("admin.riders"))
