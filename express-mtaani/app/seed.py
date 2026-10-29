from .extensions import db
from .models import Product, Shop

DEMO = [
    ("Mama Njeri Kitchen", "Home-style Kenyan meals, cooked fresh.", "Upper Hill, Nairobi", -1.2976, 36.8157, [
        ("food", "Chapati & beans", "Two soft chapatis with a bowl of stewed beans.", 180),
        ("food", "Pilau & kachumbari", "Spiced rice with fresh tomato and onion salad.", 300),
        ("food", "Ugali & sukuma wiki", "Ugali with sautéed collard greens.", 200),
        ("food", "Nyama choma (quarter kg)", "Grilled beef served with kachumbari.", 550),
        ("food", "Chicken & chips", "Fried chicken quarter with a portion of chips.", 450),
        ("food", "Mandazi (4 pieces)", "Fresh, lightly sweet fried dough.", 80),
    ]),
    ("Soko Fresh Groceries", "Fresh produce and kitchen staples.", "Nairobi CBD", -1.2864, 36.8172, [
        ("groceries", "Maize flour (2 kg)", "Sifted white maize flour.", 190),
        ("groceries", "Fresh milk (500 ml)", "Pasteurised whole milk.", 65),
        ("groceries", "Eggs (tray of 30)", "Farm eggs.", 480),
        ("groceries", "Tomatoes (1 kg)", "Ripe tomatoes.", 120),
        ("groceries", "Rice (1 kg)", "Long grain rice.", 200),
        ("groceries", "Cooking oil (1 litre)", "Vegetable cooking oil.", 330),
    ]),
    ("Westlands Mini Mart", "Everyday household items and small electronics.", "Westlands, Nairobi", -1.2673, 36.8110, [
        ("household", "Laundry detergent (1 kg)", "Washing powder.", 250),
        ("household", "Toilet paper (4 rolls)", "Soft two-ply tissue.", 220),
        ("household", "Drinking water (5 litres)", "Purified drinking water.", 150),
        ("shopping", "Phone charging cable", "Durable USB-C cable, 1 metre.", 350),
        ("shopping", "Earphones", "Wired earphones with microphone.", 400),
    ]),
]


def seed():
    if Shop.query.count():
        return "Shops already exist, nothing added."
    for name, desc, address, lat, lng, products in DEMO:
        shop = Shop(name=name, description=desc, address=address, lat=lat, lng=lng)
        db.session.add(shop)
        db.session.flush()
        for category, pname, pdesc, price in products:
            db.session.add(Product(shop_id=shop.id, category=category, name=pname, description=pdesc, price=price))
    db.session.commit()
    return "Added 3 demo shops with sample products."
