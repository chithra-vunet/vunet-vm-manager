from flask import Flask
from flask_login import LoginManager
from pymongo import MongoClient
from config import Config

login_manager = LoginManager()
mongo_client  = None
db            = None


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # MongoDB — short timeout so startup failure is reported quickly
    global mongo_client, db
    mongo_client = MongoClient(
        app.config["MONGO_URI"],
        serverSelectionTimeoutMS=5000,
    )
    db = mongo_client[app.config["DB_NAME"]]

    # Create indexes (best-effort; logs a warning if DB is unreachable)
    try:
        db.vms.create_index("vm_name")
        db.vms.create_index([("status", 1), ("planned_end_date", 1)])
        db.vms.create_index("cloud_provider")
        db.vms.create_index("team_name")
        db.users.create_index("username", unique=True)
    except Exception as exc:
        import warnings
        warnings.warn(f"Could not create DB indexes (is MONGO_URI set?): {exc}")

    # Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import load_user_by_id
        return load_user_by_id(user_id)

    # Blueprints
    from app.routes.auth      import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.reports   import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(reports_bp)

    return app
