import pytest
from flask import g

from app import create_app
from app.extensions import db
from app.models import Product, Shop, User


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test",
        "GEOAPIFY_API_KEY": "test-key",
        "NEARBY_RADIUS_KM": 6,
    })
    # The fixture keeps one app context open, so Flask-Login's cached user would leak between
    # test clients. Real requests each get their own context; this makes the tests behave the same.
    @app.before_request
    def _fresh_login_state():
        g.pop("_login_user", None)

    from app import auth
    auth._failed.clear()  # the sign-in limiter keeps state in memory between tests

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(email, role, approved=True, name=None, password="password123"):
    user = User(name=name or email.split("@")[0].title(), email=email, phone="+254712345678",
                role=role, approved=approved)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def data(app):
    """A shop (Upper Hill), two products, one customer, one admin and two approved riders."""
    shop = Shop(name="Test Kitchen", description="", address="Upper Hill", lat=-1.2976, lng=36.8157)
    other = Shop(name="Other Shop", description="", address="CBD", lat=-1.2864, lng=36.8172)
    db.session.add_all([shop, other])
    db.session.flush()
    chapati = Product(shop_id=shop.id, category="food", name="Chapati", price=50)
    beans = Product(shop_id=shop.id, category="food", name="Beans", price=130)
    milk = Product(shop_id=other.id, category="groceries", name="Milk", price=65)
    hidden = Product(shop_id=shop.id, category="food", name="Hidden dish", price=999, is_available=False)
    db.session.add_all([chapati, beans, milk, hidden])
    db.session.commit()
    return {
        "shop": shop, "other": other, "chapati": chapati, "beans": beans, "milk": milk, "hidden": hidden,
        "customer": make_user("amina@example.com", "customer", name="Amina Wanjiru"),
        "admin": make_user("boss@example.com", "admin", name="Boss"),
        "rider1": make_user("brian@example.com", "rider", name="Brian Otieno"),
        "rider2": make_user("cecilia@example.com", "rider", name="Cecilia Njoki"),
    }


def login(app, email, password="password123"):
    client = app.test_client()
    resp = client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 302, resp.get_data(as_text=True)
    return client


def place_order(client, data, dest=(-1.2921, 36.7872), items=(("chapati", 2),)):
    """Add items to the cart and check out as the given (signed-in) customer."""
    for product, qty in items:
        r = client.post("/cart/add", data={"product_id": data[product].id,
                                           "qty": qty})
        assert r.status_code == 302
    return client.post("/checkout", data={
        "customer_name": "Amina Wanjiru", "customer_phone": "0712 345 678",
        "dest_address": "Gate B, Kilimani", "dest_lat": dest[0], "dest_lng": dest[1],
        "payment_method": "cash_on_delivery",
    })


def go_online(client, lat=-1.30, lng=36.81):
    r = client.post("/api/rider/presence", json={"online": True, "lat": lat, "lng": lng})
    assert r.status_code == 200
