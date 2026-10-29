from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user

from .access import roles_required
from .extensions import db
from .models import CATEGORIES, CATEGORY_LABELS, Order, OrderItem, Product, Shop
from .utils import (KENYA_BOUNDS, delivery_fee, haversine_km, normalize_phone,
                    parse_coord, parse_int, safe_next)

bp = Blueprint("shop", __name__)

MAX_QTY = 20


def _like(text):
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---- Cart (kept in the signed session cookie; prices are always re-read from the database) ----

def _cart():
    cart = session.get("cart")
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), dict) or "shop_id" not in cart:
        return {"shop_id": None, "items": {}}
    return cart


def _save(cart):
    session["cart"] = cart
    session.modified = True


def cart_lines():
    """Return (shop, lines, subtotal) for the current cart, dropping anything no longer for sale."""
    cart = _cart()
    if not cart["items"]:
        return None, [], 0
    shop = db.session.get(Shop, cart["shop_id"]) if cart["shop_id"] else None
    if not shop or not shop.is_active:
        return None, [], 0
    ids = [int(k) for k in cart["items"] if str(k).isdigit()]
    products = (Product.query.filter(Product.id.in_(ids), Product.shop_id == shop.id,
                                     Product.is_available.is_(True))
                .order_by(Product.name).all())
    lines, subtotal = [], 0
    for p in products:
        qty = parse_int(cart["items"].get(str(p.id)), 1, MAX_QTY)
        if not qty:
            continue
        lines.append({"product": p, "qty": qty, "total": p.price * qty})
        subtotal += p.price * qty
    return shop, lines, subtotal


@bp.app_context_processor
def inject_cart_count():
    items = _cart()["items"]
    return {"cart_count": sum(v for v in items.values() if isinstance(v, int))}


# ---- Home ----

@bp.get("/")
def home():
    q = (request.args.get("q") or "").strip()[:60]
    category = request.args.get("category") or ""
    shop_id = parse_int(request.args.get("shop"), 1, 10**9)

    query = (Product.query.join(Shop)
             .filter(Product.is_available.is_(True), Shop.is_active.is_(True)))
    if q:
        query = query.filter(Product.name.ilike(_like(q), escape="\\") |
                             Product.description.ilike(_like(q), escape="\\"))
    if category in CATEGORY_LABELS:
        query = query.filter(Product.category == category)
    else:
        category = ""
    if shop_id:
        query = query.filter(Product.shop_id == shop_id)
    products = query.order_by(Shop.name, Product.name).limit(120).all()
    shops = Shop.query.filter_by(is_active=True).order_by(Shop.name).all()
    return render_template("index.html", products=products, shops=shops, categories=CATEGORIES,
                           q=q, category=category, shop_id=shop_id)


# ---- Cart pages ----

@bp.post("/cart/add")
def cart_add():
    product_id = parse_int(request.form.get("product_id"), 1, 10**9)
    qty = parse_int(request.form.get("qty") or "1", 1, MAX_QTY) or 1
    back = safe_next(request.form.get("next"), url_for("shop.home"))
    product = db.session.get(Product, product_id) if product_id else None
    if not product or not product.is_available or not product.shop.is_active:
        flash("Sorry, that item is not available right now.", "error")
        return redirect(back)

    cart = _cart()
    different_shop = bool(cart["items"]) and cart["shop_id"] != product.shop_id
    if different_shop and request.form.get("replace") != "1":
        return render_template("cart_conflict.html", product=product, qty=qty, back=back,
                               current_shop=db.session.get(Shop, cart["shop_id"]))
    if different_shop or not cart["items"]:
        cart = {"shop_id": product.shop_id, "items": {}}
    key = str(product.id)
    cart["items"][key] = min(MAX_QTY, (parse_int(cart["items"].get(key), 1, MAX_QTY) or 0) + qty)
    _save(cart)
    flash(f"Added {product.name} to your cart.", "success")
    return redirect(back)


@bp.get("/cart")
def cart():
    shop, lines, subtotal = cart_lines()
    return render_template("cart.html", shop=shop, lines=lines, subtotal=subtotal, max_qty=MAX_QTY)


@bp.post("/cart/update")
def cart_update():
    cart = _cart()
    for key, value in request.form.items():
        if not key.startswith("qty_"):
            continue
        pid = key[4:]
        if pid not in cart["items"]:
            continue
        qty = parse_int(value, 0, MAX_QTY)
        if qty is None:
            continue
        if qty == 0:
            cart["items"].pop(pid, None)
        else:
            cart["items"][pid] = qty
    if not cart["items"]:
        cart = {"shop_id": None, "items": {}}
    _save(cart)
    return redirect(url_for("shop.cart"))


@bp.post("/cart/clear")
def cart_clear():
    session.pop("cart", None)
    return redirect(url_for("shop.cart"))


# ---- Checkout ----

def _checkout_data(shop):
    cfg = current_app.config
    return {
        "center": {"lat": shop.lat, "lng": shop.lng},
        "shop": {"name": shop.name, "lat": shop.lat, "lng": shop.lng},
        "fee_base": cfg["DELIVERY_BASE_FEE"],
        "fee_per_km": cfg["DELIVERY_PER_KM"],
    }


@bp.route("/checkout", methods=["GET", "POST"])
@roles_required("customer")
def checkout():
    shop, lines, subtotal = cart_lines()
    if not lines:
        flash("Your cart is empty.", "info")
        return redirect(url_for("shop.cart"))

    values = {"customer_name": current_user.name, "customer_phone": current_user.phone,
              "dest_address": "", "dest_lat": "", "dest_lng": ""}
    errors = []

    if request.method == "POST":
        for k in values:
            values[k] = (request.form.get(k) or "").strip()
        if not 2 <= len(values["customer_name"]) <= 80:
            errors.append("Enter the name the rider should ask for.")
        phone = normalize_phone(values["customer_phone"])
        if not phone:
            errors.append("Enter a valid Kenyan phone number, like 0712 345 678.")
        if not 3 <= len(values["dest_address"]) <= 255:
            errors.append("Add an address or landmark so the rider can find you.")
        coords = parse_coord(values["dest_lat"], values["dest_lng"], KENYA_BOUNDS)
        if not coords:
            errors.append("Search for your address or drop the pin on the map.")
        if request.form.get("payment_method") != "cash_on_delivery":
            errors.append("Choose a payment method.")

        if not errors:
            cfg = current_app.config
            km = haversine_km(shop.lat, shop.lng, coords[0], coords[1])
            fee = delivery_fee(km, cfg["DELIVERY_BASE_FEE"], cfg["DELIVERY_PER_KM"])
            order = Order(
                customer_id=current_user.id, shop_id=shop.id,
                customer_name=values["customer_name"], customer_phone=phone,
                pickup_name=shop.name, pickup_lat=shop.lat, pickup_lng=shop.lng,
                dest_address=values["dest_address"], dest_lat=coords[0], dest_lng=coords[1],
                subtotal=subtotal, delivery_fee=fee, total=subtotal + fee,
                payment_method="cash_on_delivery", payment_status="unpaid",
            )
            for line in lines:
                order.items.append(OrderItem(product_id=line["product"].id, name=line["product"].name,
                                             unit_price=line["product"].price, quantity=line["qty"]))
            db.session.add(order)
            db.session.commit()
            session.pop("cart", None)
            flash("Order placed! A rider near the shop will accept it shortly.", "success")
            return redirect(url_for("shop.track", token=order.public_token))

    status = 400 if errors else 200
    return render_template("checkout.html", shop=shop, lines=lines, subtotal=subtotal,
                           values=values, errors=errors, page_data=_checkout_data(shop)), status


# ---- Customer account + tracking ----

@bp.get("/account/orders")
@roles_required("customer")
def my_orders():
    orders = (Order.query.filter_by(customer_id=current_user.id)
              .order_by(Order.created_at.desc()).limit(50).all())
    return render_template("my_orders.html", orders=orders)


@bp.get("/track/<token>")
def track(token):
    order = Order.query.filter_by(public_token=token).first_or_404()
    page_data = {"api_url": url_for("api.track_data", token=token), "initial": order.public_dict()}
    return render_template("track.html", order=order, page_data=page_data)
