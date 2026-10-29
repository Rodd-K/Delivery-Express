from app.extensions import db
from app.models import Order
from app.utils import delivery_fee, haversine_km, normalize_phone, parse_coord, KENYA_BOUNDS
from tests.conftest import login, place_order


def test_helpers():
    assert normalize_phone("0712 345 678") == "+254712345678"
    assert normalize_phone("12345") is None
    assert parse_coord("nan", "36.8") is None
    assert parse_coord("48.85", "2.35", KENYA_BOUNDS) is None  # Paris is outside Kenya
    assert 0.9 < haversine_km(-1.2864, 36.8172, -1.2864, 36.8262) < 1.1
    assert delivery_fee(0, 100, 30) == 100
    assert delivery_fee(2.3, 100, 30) == 190  # 3 started km: 100 + 90
    assert delivery_fee(1, 105, 33) == 140    # 138 rounded up to the next 10


def test_cart_add_update_and_one_shop_rule(app, data):
    c = app.test_client()
    c.post("/cart/add", data={"product_id": data["chapati"].id, "qty": 2})
    c.post("/cart/add", data={"product_id": data["chapati"].id, "qty": 1})
    page = c.get("/cart").get_data(as_text=True)
    assert "Chapati" in page and "KES 150" in page  # 3 x 50

    # A product from another shop asks before replacing the cart
    r = c.post("/cart/add", data={"product_id": data["milk"].id})
    assert r.status_code == 200 and b"Start a new cart" in r.data
    assert "Chapati" in c.get("/cart").get_data(as_text=True)
    c.post("/cart/add", data={"product_id": data["milk"].id, "replace": "1"})
    cart = c.get("/cart").get_data(as_text=True)
    assert "Milk" in cart and "Chapati" not in cart

    c.post("/cart/update", data={f"qty_{data['milk'].id}": "0"})
    assert b"Your cart is empty" in c.get("/cart").data


def test_unavailable_product_cannot_be_added(app, data):
    c = app.test_client()
    c.post("/cart/add", data={"product_id": data["hidden"].id})
    assert b"Your cart is empty" in c.get("/cart").data


def test_checkout_requires_customer_and_cart(app, data):
    anon = app.test_client()
    anon.post("/cart/add", data={"product_id": data["chapati"].id})
    assert anon.get("/checkout").status_code == 302            # must sign in first
    customer = login(app, "amina@example.com")
    assert customer.get("/checkout").status_code == 302        # empty cart goes back to the cart page


def test_checkout_creates_order_with_server_side_totals(app, data):
    c = login(app, "amina@example.com")
    r = place_order(c, data, items=(("chapati", 2), ("beans", 1)))
    assert r.status_code == 302 and "/track/" in r.headers["Location"]

    order = Order.query.one()
    assert order.customer_id == data["customer"].id
    assert order.subtotal == 2 * 50 + 130
    assert order.delivery_fee == delivery_fee(
        haversine_km(order.pickup_lat, order.pickup_lng, order.dest_lat, order.dest_lng), 100, 30)
    assert order.total == order.subtotal + order.delivery_fee
    assert order.status == "placed" and order.rider_id is None
    assert order.payment_method == "cash_on_delivery" and order.payment_status == "unpaid"
    assert {(i.name, i.unit_price, i.quantity) for i in order.items} == {("Chapati", 50, 2), ("Beans", 130, 1)}
    assert b"Your cart is empty" in c.get("/cart").data       # cart cleared after ordering


def test_order_keeps_price_snapshot(app, data):
    c = login(app, "amina@example.com")
    place_order(c, data)
    data["chapati"].price = 500
    db.session.commit()
    order = Order.query.one()
    assert order.items[0].unit_price == 50 and order.subtotal == 100


def test_checkout_rejects_bad_input(app, data):
    c = login(app, "amina@example.com")
    c.post("/cart/add", data={"product_id": data["chapati"].id})
    bad = {"customer_name": "A", "customer_phone": "abc", "dest_address": "", "dest_lat": "", "dest_lng": "",
           "payment_method": "bitcoin"}
    assert c.post("/checkout", data=bad).status_code == 400
    outside = {"customer_name": "Amina", "customer_phone": "0712345678", "dest_address": "Paris",
               "dest_lat": "48.85", "dest_lng": "2.35", "payment_method": "cash_on_delivery"}
    assert c.post("/checkout", data=outside).status_code == 400
    assert Order.query.count() == 0


def test_cart_prices_cannot_be_tampered_with(app, data):
    c = login(app, "amina@example.com")
    c.post("/cart/add", data={"product_id": data["chapati"].id, "price": "1", "qty": "1"})
    place_order(c, data, items=())
    assert Order.query.one().subtotal == 50


def test_customer_sees_only_own_orders(app, data):
    from tests.conftest import make_user
    make_user("other@example.com", "customer")
    mine = login(app, "amina@example.com")
    place_order(mine, data)
    other = login(app, "other@example.com")
    assert b"not placed any orders" in other.get("/account/orders").data
    assert b"Order #1" in mine.get("/account/orders").data


def test_tracking_link_hides_phone_and_needs_token(app, data):
    c = login(app, "amina@example.com")
    place_order(c, data)
    order = Order.query.one()
    anon = app.test_client()
    assert anon.get(f"/track/{order.public_token}").status_code == 200
    payload = anon.get(f"/api/track/{order.public_token}").get_json()
    assert payload["status"] == "placed" and payload["rider"] is None
    assert "+254" not in str(payload)
    assert anon.get("/track/not-a-real-token").status_code == 404
    assert anon.get("/api/track/1").status_code == 404  # numeric ids are not accepted
