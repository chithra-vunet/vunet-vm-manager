import os
from flask import Flask
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
from pymongo import MongoClient
from config import Config

login_manager = LoginManager()
oauth         = OAuth()
mongo_client  = None
db            = None


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.url_map.strict_slashes = False

    # MongoDB
    global mongo_client, db
    mongo_client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=5000)
    db = mongo_client[app.config["DB_NAME"]]

    try:
        db.vms.create_index("vm_name")
        db.vms.create_index([("status", 1), ("planned_end_date", 1)])
        db.vms.create_index("cloud_provider")
        db.vms.create_index("team_name")
        db.users.create_index("username", unique=True)
        db.users.create_index("email",    unique=True, sparse=True)
    except Exception as exc:
        import warnings
        warnings.warn(f"Could not create DB indexes: {exc}")

    # Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import load_user_by_id
        return load_user_by_id(user_id)

    # Google OAuth
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    # APScheduler — start once only.
    # In dev: only in the reloader's main process (not the watcher child).
    # In prod (gunicorn --workers 1): always starts, which is correct.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from app.notifications import init_scheduler
        init_scheduler(app)

    # Blueprints
    from app.routes.auth      import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.reports   import reports_bp
    from app.routes.settings  import settings_bp
    from app.routes.users     import users_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(users_bp)

    return app
