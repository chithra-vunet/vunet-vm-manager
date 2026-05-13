import app as _app

_COLLECTION = "app_settings"
_DOC_ID     = "email_config"

_DEFAULTS = {
    "mail_username":   "",
    "mail_password":   "",
    "admin_email":     "",
    "alert_days":      2,
    "alerts_enabled":  True,
}


def get_settings():
    doc = _app.db[_COLLECTION].find_one({"_id": _DOC_ID}) or {}
    merged = {**_DEFAULTS}
    for k, v in doc.items():
        if k != "_id":
            merged[k] = v
    return merged


def save_settings(data):
    _app.db[_COLLECTION].update_one(
        {"_id": _DOC_ID},
        {"$set": data},
        upsert=True,
    )
