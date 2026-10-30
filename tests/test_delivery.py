from datetime import timedelta

from app.extensions import db
from app.models import Order, utcnow
from tests.conftest import go_online, login, make_user, place_order


def _order(app, data, dest=(-1.2921, 36.7872)):
    customer = login(app, "amina@example.com")
    place_order(customer, data, dest=dest)
    return Order.query.one()


def test_offline_rider_sees_nothing_and_cannot_accept(app, data):
    order = _order(app, data)
    rider = login(app, "brian@example.com")
    assert rider.get("/api/rider/available").get_json() == {"orders": [], "reason": "offline"}
    assert rider.post(f"/api/rider/orders/{order.id}/accept").status_code == 409


def test_only_nearby_riders_see_the_order(app, data):
    order = _order(app, data)
    near = login(app, "brian@example.com")
    far = login(app, "cecilia@example.com")
    go_online(near, -1.30, 36.81)       # about 1 km from the shop in Upper Hill
    go_online(far, -1.10, 37.00)        # roughly 28 km away
    listing = near.get("/api/rider/available").get_json()
    assert [o["id"] for o in listing["orders"]] == [order.id]
    assert "customer" not in str(listing).lower() and "+254" not in str(listing)  # no personal details before accepting
    assert far.get("/api/rider/available").get_json()["orders"] == []
    assert far.post(f"/api/rider/orders/{order.id}/accept").status_code == 403


def test_nearest_rider_is_listed_first(app, data):
    customer = login(app, "amina@example.com")
    place_order(customer, data, dest=(-1.2921, 36.7872))
    place_order(customer, data, dest=(-1.2900, 36.7900))
    near_second = Order.query.order_by(Order.id).all()
    rider = login(app, "brian@example.com")
    go_online(rider, -1.30, 36.81)
    ids = [o["id"] for o in rider.get("/api/rider/available").get_json()["orders"]]
    assert sorted(ids) == sorted(o.id for o in near_second)


def test_stale_location_counts_as_offline(app, data):
    order = _order(app, data)
    rider = login(app, "brian@example.com")
    go_online(rider)
    data["rider1"].last_seen_at = utcnow() - timedelta(minutes=10)
    db.session.commit()
    assert rider.get("/api/rider/available").get_json()["reason"] == "offline"
    assert rider.post(f"/api/rider/orders/{order.id}/accept").status_code == 409


def test_only_one_rider_can_win_an_order(app, data):
    order = _order(app, data)
    first, second = login(app, "brian@example.com"), login(app, "cecilia@example.com")
    go_online(first)
    go_online(second)
    r1 = first.post(f"/api/rider/orders/{order.id}/accept")
    r2 = second.post(f"/api/rider/orders/{order.id}/accept")
    assert r1.status_code == 200 and r2.status_code == 409
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.rider_id == data["rider1"].id and order.status == "accepted"
    assert second.get("/api/rider/available").get_json()["orders"] == []


def test_rider_with_active_delivery_cannot_take_another(app, data):
    _order(app, data)
    customer = login(app, "amina@example.com")
    place_order(customer, data)
    rider = login(app, "brian@example.com")
    go_online(rider)
    first_id = rider.get("/api/rider/available").get_json()["orders"][0]["id"]
    assert rider.post(f"/api/rider/orders/{first_id}/accept").status_code == 200
    assert rider.get("/api/rider/available").get_json()["reason"] == "busy"
    other_id = Order.query.filter(Order.id != first_id).one().id
    assert rider.post(f"/api/rider/orders/{other_id}/accept").status_code == 409


def test_full_delivery_with_cash(app, data):
    order = _order(app, data)
    token = order.public_token
    rider = login(app, "brian@example.com")
    customer_view = app.test_client()
    go_online(rider)
    assert rider.post(f"/api/rider/orders/{order.id}/accept").status_code == 200

    loc, status = f"/api/rider/orders/{order.id}/location", f"/api/rider/orders/{order.id}/status"
    assert rider.get(f"/rider/orders/{order.id}").status_code == 200
    assert rider.post(status, json={"status": "delivered"}).status_code == 409   # cannot skip pickup
    assert rider.post(status, json={"status": "cancelled"}).status_code == 409   # riders cannot cancel
    assert rider.post(loc, json={"lat": "x", "lng": 36.8}).status_code == 400

    assert rider.post(loc, json={"lat": -1.30, "lng": 36.81, "eta_seconds": 600}).status_code == 200
    seen = customer_view.get(f"/api/track/{token}").get_json()
    assert seen["status"] == "accepted" and seen["rider_name"] == "Brian"
    assert seen["rider"]["lat"] == -1.30 and seen["rider"]["eta_seconds"] is None

    assert rider.post(status, json={"status": "on_the_way"}).status_code == 200
    rider.post(loc, json={"lat": -1.29, "lng": 36.79, "eta_seconds": 240, "distance_m": 900})
    seen = customer_view.get(f"/api/track/{token}").get_json()
    assert seen["rider"]["eta_seconds"] == 240 and seen["rider"]["distance_m"] == 900

    done = rider.post(status, json={"status": "delivered", "cash_collected": True})
    assert done.status_code == 200 and done.get_json()["payment_status"] == "paid"
    seen = customer_view.get(f"/api/track/{token}").get_json()
    assert seen["status"] == "delivered" and seen["rider"] is None   # position wiped
    assert rider.post(loc, json={"lat": -1.3, "lng": 36.8}).status_code == 409


def test_delivered_without_cash_stays_unpaid(app, data):
    order = _order(app, data)
    rider = login(app, "brian@example.com")
    go_online(rider)
    rider.post(f"/api/rider/orders/{order.id}/accept")
    status = f"/api/rider/orders/{order.id}/status"
    rider.post(status, json={"status": "on_the_way"})
    assert rider.post(status, json={"status": "delivered"}).get_json()["payment_status"] == "unpaid"


def test_riders_cannot_touch_each_others_orders(app, data):
    order = _order(app, data)
    mine, other = login(app, "brian@example.com"), login(app, "cecilia@example.com")
    go_online(mine)
    mine.post(f"/api/rider/orders/{order.id}/accept")
    for path, body in ((f"/api/rider/orders/{order.id}/location", {"lat": -1.3, "lng": 36.8}),
                       (f"/api/rider/orders/{order.id}/status", {"status": "on_the_way"}),
                       (f"/api/rider/orders/{order.id}/release", {})):
        assert other.post(path, json=body).status_code == 403
    assert other.get(f"/rider/orders/{order.id}").status_code == 404


def test_release_returns_order_to_the_pool(app, data):
    order = _order(app, data)
    rider = login(app, "brian@example.com")
    go_online(rider)
    rider.post(f"/api/rider/orders/{order.id}/accept")
    assert rider.post(f"/api/rider/orders/{order.id}/release").status_code == 200
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.status == "placed" and order.rider_id is None
    assert [o["id"] for o in rider.get("/api/rider/available").get_json()["orders"]] == [order.id]


def test_admin_cannot_be_impersonated_on_rider_api(app, data):
    customer = login(app, "amina@example.com")
    assert customer.post("/api/rider/presence", json={"online": True, "lat": -1.3, "lng": 36.8}).status_code == 403
    assert app.test_client().get("/api/admin/riders").status_code == 401
    assert customer.get("/api/admin/riders").status_code == 403


# ---- Admin ----

def test_admin_dashboard_and_pages(app, data):
    _order(app, data)
    admin = login(app, "boss@example.com")
    for path in ("/admin/", "/admin/orders", "/admin/orders?status=placed", "/admin/orders/1", "/admin/products",
                 "/admin/products/new", "/admin/products/1/edit", "/admin/shops", "/admin/shops/new",
                 "/admin/shops/1/edit", "/admin/riders"):
        assert admin.get(path).status_code == 200, path


def test_admin_sees_online_riders(app, data):
    rider = login(app, "brian@example.com")
    go_online(rider)
    admin = login(app, "boss@example.com")
    riders = admin.get("/api/admin/riders").get_json()["riders"]
    assert [r["name"] for r in riders] == ["Brian Otieno"]


def test_admin_assigns_and_cancels(app, data):
    order = _order(app, data)
    admin = login(app, "boss@example.com")
    r = admin.post(f"/admin/orders/{order.id}/assign", data={"rider_id": data["rider2"].id})
    assert r.status_code == 302
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.rider_id == data["rider2"].id and order.status == "accepted"

    customer_id = data["customer"].id
    admin.post(f"/admin/orders/{order.id}/assign", data={"rider_id": customer_id})   # a customer is not a rider
    db.session.expire_all()
    assert db.session.get(Order, order.id).rider_id == data["rider2"].id

    admin.post(f"/admin/orders/{order.id}/cancel")
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == "cancelled"


def test_admin_marks_cash_received(app, data):
    order = _order(app, data)
    rider = login(app, "brian@example.com")
    go_online(rider)
    rider.post(f"/api/rider/orders/{order.id}/accept")
    rider.post(f"/api/rider/orders/{order.id}/status", json={"status": "on_the_way"})
    rider.post(f"/api/rider/orders/{order.id}/status", json={"status": "delivered"})
    admin = login(app, "boss@example.com")
    admin.post(f"/admin/orders/{order.id}/mark-paid")
    db.session.expire_all()
    assert db.session.get(Order, order.id).payment_status == "paid"


def test_admin_product_and_shop_management(app, data):
    from app.models import Product, Shop
    admin = login(app, "boss@example.com")
    good = {"shop_id": data["shop"].id, "name": "Samosa", "category": "food", "description": "Beef samosa",
            "price": "60", "image_url": "", "is_available": "on"}
    assert admin.post("/admin/products/new", data=good).status_code == 302
    assert Product.query.filter_by(name="Samosa").one().price == 60
    assert admin.post("/admin/products/new", data=dict(good, price="free")).status_code == 400
    assert admin.post("/admin/products/new", data=dict(good, image_url="http://insecure.example/x.png")).status_code == 400
    assert admin.post("/admin/products/new", data=dict(good, category="weapons")).status_code == 400

    pid = Product.query.filter_by(name="Samosa").one().id
    admin.post(f"/admin/products/{pid}/toggle")
    db.session.expire_all()
    assert db.session.get(Product, pid).is_available is False
    assert b"Samosa" not in app.test_client().get("/").data

    shop = {"name": "New Shop", "address": "Kilimani", "lat": "-1.29", "lng": "36.78", "is_active": "on"}
    assert admin.post("/admin/shops/new", data=shop).status_code == 302
    assert Shop.query.filter_by(name="New Shop").count() == 1
    assert admin.post("/admin/shops/new", data=dict(shop, lat="")).status_code == 400
    assert admin.post("/admin/shops/new", data=dict(shop, lat="48.8", lng="2.3")).status_code == 400


def test_admin_approves_rider(app, data):
    from app.models import User
    pending = make_user("new@rider.com", "rider", approved=False)
    admin = login(app, "boss@example.com")
    assert admin.post(f"/admin/riders/{pending.id}/approve").status_code == 302
    db.session.expire_all()
    assert db.session.get(User, pending.id).approved is True
    assert login(app, "new@rider.com").get("/rider/").status_code == 200
    # customers cannot be approved/deactivated through the rider routes
    assert admin.post(f"/admin/riders/{data['customer'].id}/deactivate").status_code == 404


def test_pages_that_need_login_for_each_role_render(app, data):
    rider = login(app, "brian@example.com")
    assert rider.get("/rider/").status_code == 200
    customer = login(app, "amina@example.com")
    place_order(customer, data)
    assert customer.get("/checkout").status_code == 302  # cart was emptied by the order
    customer.post("/cart/add", data={"product_id": data["chapati"].id})
    assert customer.get("/checkout").status_code == 200
