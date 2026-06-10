from datetime import datetime, timedelta
from bson import ObjectId
import app as _app

CLOUD_PROVIDERS = ["Azure-Billed", "Azure-FreeCredits", "AWS", "GCP", "E2E", "C4I", "Tower"]
STATUSES = ["Active", "Inactive"]

PROVIDER_COLORS = {
    "Azure-Billed":       "primary",
    "Azure-FreeCredits":  "info",
    "AWS":                "warning",
    "GCP":                "danger",
    "E2E":                "success",
    "C4I":                "secondary",
    "Tower":              "dark",
}


def _db():
    return _app.db


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _serialize(doc):
    if doc is None:
        return None
    doc   = dict(doc)
    doc["_id"] = str(doc["_id"])
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Total cost (before dates are stringified) ──────────────────────────
    start    = doc.get("start_date")
    del_date = doc.get("deleted_date")
    status   = doc.get("status", "Active")
    daily    = float(doc.get("daily_cost", 0))
    if start and isinstance(start, datetime):
        if status == "Active":
            end_for_cost = today
        elif del_date and isinstance(del_date, datetime):
            end_for_cost = del_date
        else:
            # Inactive but no deleted_date: use planned_end_date if it's in the past
            planned = doc.get("planned_end_date")
            if planned and isinstance(planned, datetime) and planned <= today:
                end_for_cost = planned
            else:
                end_for_cost = today
        days = max(0, (end_for_cost - start).days)
        doc["total_cost"] = round(days * daily, 2)
        doc["total_cost_days"] = days
        doc["cost_end_date"] = end_for_cost.strftime("%Y-%m-%d")
    else:
        doc["total_cost"] = 0.0
        doc["total_cost_days"] = 0
        doc["cost_end_date"] = ""

    # ── Serialize dates to strings ─────────────────────────────────────────
    for field in ("start_date", "planned_end_date", "deleted_date", "created_at", "updated_at"):
        if field in doc and isinstance(doc[field], datetime):
            doc[field] = doc[field].strftime("%Y-%m-%d")

    doc["provider_color"] = PROVIDER_COLORS.get(doc.get("cloud_provider", ""), "secondary")

    # ── Expiry flags ───────────────────────────────────────────────────────
    end = doc.get("planned_end_date")
    if end and status == "Active":
        try:
            end_dt = datetime.strptime(end, "%Y-%m-%d")
            doc["is_overdue"]  = end_dt < today
            doc["is_expiring"] = today <= end_dt <= today + timedelta(days=7)
        except ValueError:
            doc["is_overdue"] = doc["is_expiring"] = False
    else:
        doc["is_overdue"] = doc["is_expiring"] = False
    return doc


# ── Queries ────────────────────────────────────────────────────────────────────

_SORT_FIELDS = {
    "start_date":       "start_date",
    "planned_end_date": "planned_end_date",
    "daily_cost":       "daily_cost",
    "total_cost":       "daily_cost",   # total_cost is computed; daily_cost is a valid proxy
}


def get_all_vms(search=None, providers=None, teams=None, status=None,
                page=1, per_page=25, sort_by=None, sort_dir="asc"):
    query = {}
    if status and status != "All":
        query["status"] = status
    if providers:
        query["cloud_provider"] = {"$in": providers}
    if teams:
        query["team_name"] = {"$in": teams}
    if search:
        query["$or"] = [
            {"vm_name":      {"$regex": search, "$options": "i"}},
            {"ip_address":   {"$regex": search, "$options": "i"}},
            {"requested_by": {"$regex": search, "$options": "i"}},
        ]

    mongo_field = _SORT_FIELDS.get(sort_by, "created_at")
    direction   = 1 if sort_dir == "asc" else -1
    if sort_by not in _SORT_FIELDS:
        direction = -1   # default: newest first

    db    = _db()
    total = db.vms.count_documents(query)
    skip  = (page - 1) * per_page
    docs  = list(db.vms.find(query).sort(mongo_field, direction).skip(skip).limit(per_page))
    return [_serialize(d) for d in docs], total


def get_vm(vm_id):
    try:
        doc = _db().vms.find_one({"_id": ObjectId(vm_id)})
        return _serialize(doc)
    except Exception:
        return None


def get_distinct_teams():
    return sorted(t for t in _db().vms.distinct("team_name") if t)


# ── Writes ─────────────────────────────────────────────────────────────────────

def _vm_fields(data):
    status = data.get("status", "Active")
    return {
        "cloud_provider":    data["cloud_provider"],
        "vm_name":           data["vm_name"].strip(),
        "ip_address":        data.get("ip_address", "").strip() or "NA",
        "requested_by":      data["requested_by"].strip(),
        "requester_email":   data.get("requester_email", "").strip().lower(),
        "team_name":         data["team_name"].strip(),
        "subscription_plan": data.get("subscription_plan", "").strip(),
        "purpose":           data.get("purpose", "").strip(),
        "start_date":        _parse_date(data["start_date"]),
        "planned_end_date":  _parse_date(data["planned_end_date"]),
        "status":            status,
        "deleted_date":      _parse_date(data.get("deleted_date")) if status == "Inactive" else None,
        "daily_cost":        float(data.get("daily_cost") or 0),
    }


def create_vm(data):
    from app.sheets import sync_async
    now    = datetime.utcnow()
    doc    = {**_vm_fields(data), "created_at": now, "updated_at": now}
    result = _db().vms.insert_one(doc)
    sync_async()
    return str(result.inserted_id)


def update_vm(vm_id, data):
    from app.sheets import sync_async
    now = datetime.utcnow()
    _db().vms.update_one(
        {"_id": ObjectId(vm_id)},
        {"$set": {**_vm_fields(data), "updated_at": now}},
    )
    sync_async()


def deactivate_vm(vm_id, deleted_date=None):
    from app.sheets import sync_async
    now = datetime.utcnow()
    d   = _parse_date(deleted_date) if deleted_date else now
    _db().vms.update_one(
        {"_id": ObjectId(vm_id)},
        {"$set": {"status": "Inactive", "deleted_date": d or now, "updated_at": now}}
    )
    sync_async()


def delete_vm(vm_id):
    from app.sheets import sync_async
    _db().vms.delete_one({"_id": ObjectId(vm_id)})
    sync_async()


# ── Dashboard stats ────────────────────────────────────────────────────────────

def get_stats():
    db    = _db()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week  = today + timedelta(days=7)

    total_active = db.vms.count_documents({"status": "Active"})

    pipeline = [{"$match": {"status": "Active"}},
                {"$group": {"_id": None, "s": {"$sum": "$daily_cost"}}}]
    res = list(db.vms.aggregate(pipeline))
    total_daily_cost = round(float(res[0]["s"]), 2) if res else 0.0

    expiring_soon = db.vms.count_documents({
        "status": "Active",
        "planned_end_date": {"$gte": today, "$lte": week},
    })
    overdue = db.vms.count_documents({
        "status": "Active",
        "planned_end_date": {"$lt": today},
    })

    return {
        "total_active":     total_active,
        "total_daily_cost": total_daily_cost,
        "expiring_soon":    expiring_soon,
        "overdue":          overdue,
    }
