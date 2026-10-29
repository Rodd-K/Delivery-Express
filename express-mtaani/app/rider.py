from flask import Blueprint, abort, render_template, url_for
from flask_login import current_user
from sqlalchemy import func

from .access import roles_required
from .extensions import db
from .models import LIVE_STATUSES, Order
from .utils import kes

bp = Blueprint("rider", __name__, url_prefix="/rider")


def active_order_for(rider):
    return (Order.query.filter(Order.rider_id == rider.id, Order.status.in_(LIVE_STATUSES))
            .order_by(Order.accepted_at.desc()).first())


@bp.get("/")
@roles_required("rider")
def dashboard():
    active = active_order_for(current_user)
    delivered = db.session.query(func.count(Order.id), func.coalesce(func.sum(Order.delivery_fee), 0)).filter(
        Order.rider_id == current_user.id, Order.status == "delivered").one()
    page_data = {
        "online": bool(current_user.online),
        "has_active": bool(active),
        "presence_url": url_for("api.rider_presence"),
        "available_url": url_for("api.rider_available"),
        "accept_url": url_for("api.rider_accept", order_id=0),  # JS swaps the 0 for the order id
    }
    return render_template("rider_dashboard.html", active=active, delivered_count=delivered[0],
                           fees=kes(delivered[1]), page_data=page_data)


@bp.get("/orders/<int:order_id>")
@roles_required("rider")
def order(order_id):
    order = db.get_or_404(Order, order_id)
    if order.rider_id != current_user.id:
        abort(404)  # do not reveal other riders' orders
    page_data = {
        "order_id": order.id,
        "status": order.status,
        "total": order.total,
        "cash": order.payment_method == "cash_on_delivery",
        "pickup": {"name": order.pickup_name, "lat": order.pickup_lat, "lng": order.pickup_lng},
        "dest": {"address": order.dest_address, "lat": order.dest_lat, "lng": order.dest_lng},
        "location_url": url_for("api.rider_location", order_id=order.id),
        "status_url": url_for("api.rider_status", order_id=order.id),
        "release_url": url_for("api.rider_release", order_id=order.id),
        "dashboard_url": url_for("rider.dashboard"),
    }
    return render_template("rider_order.html", order=order, page_data=page_data)
