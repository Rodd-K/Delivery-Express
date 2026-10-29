import click
from flask import Flask, render_template

from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .utils import kes, valid_email


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    if app.config["APP_ENV"] == "production" and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("Set a strong SECRET_KEY before running in production.")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    from . import models  # noqa: F401  (register models with SQLAlchemy)
    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .rider import bp as rider_bp
    from .storefront import bp as shop_bp

    for blueprint in (shop_bp, auth_bp, rider_bp, admin_bp, api_bp):
        app.register_blueprint(blueprint)

    app.jinja_env.filters["kes"] = kes

    @app.context_processor
    def inject_maps():
        return {"geo_key": app.config["GEOAPIFY_API_KEY"]}

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="You do not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="We could not find that page."), 404

    # ---- Command line helpers ----

    @app.cli.command("init-db")
    def init_db():
        """Create all tables (quick start). Use `flask db migrate` once you manage schema changes."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True, default="Admin")
    @click.option("--phone", prompt=True, default="0700000000")
    @click.password_option()
    def create_admin(email, name, phone, password):
        """Create an administrator account."""
        from .models import User
        from .utils import normalize_phone

        email = email.strip().lower()
        if not valid_email(email):
            raise click.ClickException("That email address does not look valid.")
        if len(password) < 10:
            raise click.ClickException("Use a password of at least 10 characters for an admin.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("An account with that email already exists.")
        user = User(name=name.strip(), email=email, phone=normalize_phone(phone) or "+254700000000",
                    role="admin", approved=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin {email} created. Sign in at /login.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Add three demo shops with sample products (demo prices)."""
        from .seed import seed
        click.echo(seed())

    return app
