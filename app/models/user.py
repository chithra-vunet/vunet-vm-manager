from datetime import datetime
from bson import ObjectId
from flask_login import UserMixin
import bcrypt
import app as _app


class User(UserMixin):
    def __init__(self, doc):
        self.id           = str(doc["_id"])
        self.username     = doc.get("username", "")
        self.email        = doc.get("email", "")
        self.display_name = doc.get("name") or doc.get("username") or doc.get("email", "")
        self._password_hash = doc.get("password_hash")
        self.role         = doc.get("role", "viewer")
        self.status       = doc.get("status", "active")

    @property
    def is_admin(self):
        return self.role == "admin"

    def check_password(self, plaintext):
        if not self._password_hash:
            return False
        pw = self._password_hash
        if isinstance(pw, str):
            pw = pw.encode("utf-8")
        return bcrypt.checkpw(plaintext.encode("utf-8"), pw)

    # ── Lookups ────────────────────────────────────────────────────────────────

    @staticmethod
    def find_by_username(username):
        doc = _app.db.users.find_one({"username": username})
        return User(doc) if doc else None

    @staticmethod
    def find_by_email(email):
        doc = _app.db.users.find_one({"email": email.strip().lower()})
        return User(doc) if doc else None

    @staticmethod
    def all_users():
        docs = list(_app.db.users.find().sort("created_at", 1))
        return [User(d) for d in docs]

    # ── Writes ─────────────────────────────────────────────────────────────────

    @staticmethod
    def create_admin(username, password, role="admin"):
        pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        _app.db.users.insert_one({
            "username":      username,
            "password_hash": pw_hash,
            "role":          role,
            "status":        "active",
            "created_at":    datetime.utcnow(),
        })

    @staticmethod
    def invite(email, role, invited_by):
        """Insert an invited-user record (no Google ID yet — set on first sign-in)."""
        email = email.strip().lower()
        now   = datetime.utcnow()
        _app.db.users.update_one(
            {"email": email},
            {"$setOnInsert": {
                "email":      email,
                "role":       role,
                "status":     "invited",
                "invited_by": invited_by,
                "invited_at": now,
                "created_at": now,
            }},
            upsert=True,
        )

    @staticmethod
    def activate_google(email, google_id, name):
        """Called on first Google sign-in — attach the Google identity to the record."""
        now = datetime.utcnow()
        _app.db.users.update_one(
            {"email": email.strip().lower()},
            {"$set": {
                "google_id":  google_id,
                "name":       name,
                "status":     "active",
                "last_login": now,
                "updated_at": now,
            }},
        )

    @staticmethod
    def touch_login(email):
        _app.db.users.update_one(
            {"email": email.strip().lower()},
            {"$set": {"last_login": datetime.utcnow()}},
        )

    @staticmethod
    def update_role(user_id, role):
        _app.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"role": role, "updated_at": datetime.utcnow()}},
        )

    @staticmethod
    def delete(user_id):
        _app.db.users.delete_one({"_id": ObjectId(user_id)})


def load_user_by_id(user_id):
    try:
        doc = _app.db.users.find_one({"_id": ObjectId(user_id)})
        return User(doc) if doc else None
    except Exception:
        return None
