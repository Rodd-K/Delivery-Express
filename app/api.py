from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user
from sqlalchemy import update

from .access import api_roles
from .extensions import db
from .models import LIVE_STATUSES, TRANSITIONS, Order, User, utcnow
from .utils import haversine_km, parse_coord, parse_int

bp = Blueprint("api", __name__, url_prefix="/api")


def _json(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _my_order(order_id):
    """The order, only if it is assigned to the signed-in rider."""
    order = db.session.get(Order, order_id)
    if not order or order.rider_id != current_user.id:
        return None
    return order


# ---- Customer tracking (anyone with the unguessable link) ----

@bp.get("/track/<token>")
def track_data(token):
    order = Order.query.filter_by(public_token=token).first_or_404()
    return _json(order.public_dict())


# ---- Rider: presence + nearby orders ----

@bp.post("/rider/presence")
@api_roles("rider")
def rider_presence():
    data = request.get_json(silent=True) or {}
    if data.get("online") is False:
        current_user.online = False
        db.session.commit()
        return _json({"ok": True, "online": False})
    coords = parse_coord(data.get("lat"), data.get("lng"))
    if not coords:
        return _json({"error": "Invalid location."}, 400)
    current_user.online = True
    current_user.set_position(*coords)
    db.session.commit()
    return _json({"ok": True, "online": True})


def _has_active_order(rider):
    return (Order.query.filter(Order.rider_id == rider.id, Order.status.in_(LIVE_STATUSES)).count()
            >= current_app.config["MAX_ACTIVE_ORDERS_PER_RIDER"])


@bp.get("/rider/available")
@api_roles("rider")
def rider_available():
    """New orders whose shop is within NEARBY_RADIUS_KM of the rider's last location, nearest first."""
    if not current_user.is_fresh():
        return _json({"orders": [], "reason": "offline"})
    if _has_active_order(current_user):
        return _json({"orders": [], "reason": "busy"})
    radius = current_app.config["NEARBY_RADIUS_KM"]
    candidates = (Order.query.filter(Order.status == "placed", Order.rider_id.is_(None))
                  .order_by(Order.created_at.asc()).limit(100).all())
    nearby = []
    for o in candidates:
        d = haversine_km(current_user.last_lat, current_user.last_lng, o.pickup_lat, o.pickup_lng)
        if d <= radius:
            nearby.append((d, o))
    nearby.sort(key=lambda pair: pair[0])
    return _json({"orders": [{
        "id": o.id,
        "shop": o.pickup_name,
        "deliver_to": o.dest_address,       # no customer name or phone until the rider accepts
        "to_shop_km": round(d, 1),
        "trip_km": round(haversine_km(o.pickup_lat, o.pickup_lng, o.dest_lat, o.dest_lng), 1),
        "items": sum(i.quantity for i in o.items),
        "fee": o.delivery_fee,
        "total": o.total,
        "cash": o.payment_method == "cash_on_delivery",
        "placed_at": o.created_at.isoformat() + "Z",
    } for d, o in nearby[:20]], "radius_km": radius})


@bp.post("/rider/orders/<int:order_id>/accept")
@api_roles("rider")
def rider_accept(order_id):
    if not current_user.is_fresh():
        return _json({"error": "Go online and share your location first."}, 409)
    if _has_active_order(current_user):
        return _json({"error": "Finish your current delivery first."}, 409)
    order = db.session.get(Order, order_id)
    if not order:
        return _json({"error": "Order not found."}, 404)
    distance = haversine_km(current_user.last_lat, current_user.last_lng, order.pickup_lat, order.pickup_lng)
    if distance > current_app.config["NEARBY_RADIUS_KM"]:
        return _json({"error": "This order is too far from you."}, 403)

    # Atomic claim: only one rider can win, even if two tap Accept at the same moment.
    result = db.session.execute(
        update(Order)
        .where(Order.id == order_id, Order.status == "placed", Order.rider_id.is_(None))
        .values(status="accepted", rider_id=current_user.id, accepted_at=utcnow())
    )
    if result.rowcount != 1:
        db.session.rollback()
        return _json({"error": "Another rider already took this order."}, 409)
    db.session.commit()
    return _json({"ok": True, "next": url_for("rider.order", order_id=order_id)})


# ---- Rider: the delivery itself (only for the rider the order is assigned to) ----

@bp.post("/rider/orders/<int:order_id>/location")
@api_roles("rider")
def rider_location(order_id):
    order = _my_order(order_id)
    if not order:
        return _json({"error": "This is not your order."}, 403)
    if order.status not in LIVE_STATUSES:
        return _json({"error": "This order is not being delivered right now."}, 409)

    data = request.get_json(silent=True) or {}
    coords = parse_coord(data.get("lat"), data.get("lng"))
    if not coords:
        return _json({"error": "Invalid location."}, 400)

    order.rider_lat, order.rider_lng = coords
    order.rider_updated_at = utcnow()
    current_user.online = True
    current_user.set_position(*coords)
    # ETA is display-only. Only share it with the customer once the rider is heading to them.
    if order.status == "on_the_way":
        order.eta_seconds = parse_int(data.get("eta_seconds"), 0, 86400)
        order.distance_m = parse_int(data.get("distance_m"), 0, 500000)
    else:
        order.eta_seconds = order.distance_m = None
    db.session.commit()
    return _json({"ok": True})


@bp.post("/rider/orders/<int:order_id>/status")
@api_roles("rider")
def rider_status(order_id):
    order = _my_order(order_id)
    if not order:
        return _json({"error": "This is not your order."}, 403)
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")

    # Riders move an order forward only. Cancelling or reassigning is for admins (or "release" below).
    if new_status not in ("on_the_way", "delivered") or new_status not in TRANSITIONS.get(order.status, set()):
        return _json({"error": f"Cannot change from {order.status} to {new_status}."}, 409)

    order.status = new_status
    if new_status == "delivered":
        order.delivered_at = utcnow()
        if order.payment_method == "cash_on_delivery" and data.get("cash_collected") is True:
            order.payment_status = "paid"
            order.cash_collected_at = utcnow()
        order.clear_rider_location()  # stop exposing the rider's position once done
    db.session.commit()
    return _json({"ok": True, "status": order.status, "payment_status": order.payment_status})


@bp.post("/rider/orders/<int:order_id>/release")
@api_roles("rider")
def rider_release(order_id):
    """Give an accepted (not yet picked up) order back so another nearby rider can take it."""
    order = _my_order(order_id)
    if not order:
        return _json({"error": "This is not your order."}, 403)
    if order.status != "accepted":
        return _json({"error": "You can only release an order before you pick it up."}, 409)
    order.status = "placed"
    order.rider_id = None
    order.accepted_at = None
    order.clear_rider_location()
    db.session.commit()
    return _json({"ok": True})


# ---- Admin: live rider positions for the dashboard map ----

@bp.get("/admin/riders")
@api_roles("admin")
def admin_riders():
    riders = User.query.filter_by(role="rider", approved=True, active=True, online=True).all()
    now = utcnow()
    out = []
    for r in riders:
        if not r.is_fresh():
            continue
        busy = Order.query.filter(Order.rider_id == r.id, Order.status.in_(LIVE_STATUSES)).first()
        out.append({"id": r.id, "name": r.name, "lat": r.last_lat, "lng": r.last_lng,
                    "age_seconds": int((now - r.last_seen_at).total_seconds()),
                    "order_id": busy.id if busy else None})
    return _json({"riders": out})
