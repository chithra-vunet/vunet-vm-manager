import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    MONGO_URI   = os.environ.get("MONGO_URI", "mongodb://localhost:27017/vmmanager")
    DB_NAME     = os.environ.get("DB_NAME", "vmmanager")
    GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

