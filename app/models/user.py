from datetime import datetime
from bson import ObjectId
from flask_login import UserMixin
import bcrypt
import app as _app


class User(UserMixin):
    def __init__(self, doc):
        self.id            = str(doc["_id"])
        self.username      = doc["username"]
        self._password_hash = doc["password_hash"]
        self.role          = doc.get("role", "admin")

    def check_password(self, plaintext):
        pw = self._password_hash
        if isinstance(pw, str):
            pw = pw.encode("utf-8")
        return bcrypt.checkpw(plaintext.encode("utf-8"), pw)

    @staticmethod
    def find_by_username(username):
        doc = _app.db.users.find_one({"username": username})
        return User(doc) if doc else None

    @staticmethod
    def create(username, password, role="admin"):
        pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        _app.db.users.insert_one({
            "username":      username,
            "password_hash": pw_hash,
            "role":          role,
            "created_at":    datetime.utcnow(),
        })


def load_user_by_id(user_id):
    try:
        doc = _app.db.users.find_one({"_id": ObjectId(user_id)})
        return User(doc) if doc else None
    except Exception:
        return None
