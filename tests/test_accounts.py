from app.models import User
from tests.conftest import login, make_user




def test_pages_render(app, data):
    c = app.test_client()
    for path in ("/", "/login", "/register", "/rider/register", "/cart", "/?category=food", "/?q=chap"):
        assert c.get(path).status_code == 200, path
    assert b"Chapati" in c.get("/").data
    assert b"Hidden dish" not in c.get("/").data  # unavailable products are not listed


def test_search_is_escaped(app, data):
    c = app.test_client()
    assert c.get("/?q=%25").status_code == 200
    assert b"Chapati" not in c.get("/?q=%25").data  # a literal % matches nothing


def test_customer_signup_logs_in(app):
    c = app.test_client()
    r = c.post("/register", data={"name": "Wanjiku Kamau", "email": "W@Example.com", "phone": "0722111222",
                                  "password": "longenough1", "password2": "longenough1"})
    assert r.status_code == 302
    user = User.query.one()
    assert user.email == "w@example.com" and user.role == "customer" and user.phone == "+254722111222"
    assert user.password_hash != "longenough1"
    assert c.get("/account/orders").status_code == 200


def test_signup_validation(app, data):
    c = app.test_client()
    bad = {"name": "A", "email": "nope", "phone": "123", "password": "short", "password2": "short"}
    assert c.post("/register", data=bad).status_code == 400
    dup = {"name": "Amina Again", "email": "amina@example.com", "phone": "0712345678",
           "password": "longenough1", "password2": "longenough1"}
    assert c.post("/register", data=dup).status_code == 400
    mismatch = dict(dup, email="new@example.com", password2="different123")
    assert c.post("/register", data=mismatch).status_code == 400


def test_rider_signup_needs_approval(app):
    c = app.test_client()
    r = c.post("/rider/register", data={"name": "New Rider", "email": "new@rider.com", "phone": "0733000111",
                                        "password": "longenough1", "password2": "longenough1"})
    assert r.status_code == 302
    rider = User.query.filter_by(email="new@rider.com").one()
    assert rider.role == "rider" and rider.approved is False
    r = c.post("/login", data={"email": "new@rider.com", "password": "longenough1"})
    assert r.status_code == 200 and b"waiting for admin approval" in r.data


def test_wrong_password_and_lockout(app, data):
    c = app.test_client()
    for _ in range(5):
        r = c.post("/login", data={"email": "amina@example.com", "password": "wrong-password"})
        assert b"not correct" in r.data
    r = c.post("/login", data={"email": "amina@example.com", "password": "password123"})
    assert b"Too many attempts" in r.data


def test_login_redirects_by_role(app, data):
    assert login(app, "boss@example.com").get("/login").headers["Location"].endswith("/admin/")
    assert login(app, "brian@example.com").get("/login").headers["Location"].endswith("/rider/")
    assert login(app, "amina@example.com").get("/login").headers["Location"].endswith("/")


def test_next_redirect_is_same_site_only(app, data):
    c = app.test_client()
    r = c.post("/login", data={"email": "amina@example.com", "password": "password123", "next": "//evil.example"})
    assert "evil.example" not in r.headers["Location"]


def test_role_walls(app, data):
    anon = app.test_client()
    assert anon.get("/admin/").status_code == 302          # sent to sign in
    assert anon.get("/rider/").status_code == 302
    assert anon.get("/account/orders").status_code == 302
    customer = login(app, "amina@example.com")
    assert customer.get("/admin/").status_code == 403
    assert customer.get("/admin/products").status_code == 403
    assert customer.get("/rider/").status_code == 403
    rider = login(app, "brian@example.com")
    assert rider.get("/admin/orders").status_code == 403
    assert rider.get("/checkout").status_code == 403
    admin = login(app, "boss@example.com")
    assert admin.get("/admin/").status_code == 200
    assert admin.get("/rider/").status_code == 403


def test_deactivated_user_is_signed_out(app, data):
    c = login(app, "amina@example.com")
    assert c.get("/account/orders").status_code == 200
    data["customer"].active = False
    from app.extensions import db
    db.session.commit()
    assert c.get("/account/orders").status_code == 302


def test_logout(app, data):
    c = login(app, "amina@example.com")
    c.post("/logout")
    assert c.get("/account/orders").status_code == 302
