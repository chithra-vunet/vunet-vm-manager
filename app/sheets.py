import logging
import os
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_lock = threading.Lock()

HEADERS = [
    "VM Name", "Cloud Provider", "IP Address", "Requested By", "Requester Email",
    "Team", "Subscription Plan", "Purpose",
    "Start Date", "Planned End Date", "Status", "Deleted Date",
    "Daily Cost (INR)",
]


def _creds():
    """Build gspread credentials from env vars."""
    import gspread
    from google.oauth2.service_account import Credentials

    private_key = os.environ.get("GS_PRIVATE_KEY", "").replace("\\n", "\n")
    info = {
        "type":                        "service_account",
        "project_id":                  os.environ.get("GS_PROJECT_ID", ""),
        "private_key_id":              os.environ.get("GS_PRIVATE_KEY_ID", ""),
        "private_key":                 private_key,
        "client_email":                os.environ.get("GS_SA_EMAIL", ""),
        "client_id":                   os.environ.get("GS_CLIENT_ID", ""),
        "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                   "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url":        (
            f"https://www.googleapis.com/robot/v1/metadata/x509/"
            f"{os.environ.get('GS_SA_EMAIL', '').replace('@', '%40')}"
        ),
    }
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def _sheet():
    gc       = _creds()
    sheet_id = os.environ.get("GS_SHEET_ID", "")
    return gc.open_by_key(sheet_id).sheet1


def _fmt(val):
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return str(val)


def _vm_row(vm):
    return [
        _fmt(vm.get("vm_name")),
        _fmt(vm.get("cloud_provider")),
        _fmt(vm.get("ip_address")),
        _fmt(vm.get("requested_by")),
        _fmt(vm.get("requester_email")),
        _fmt(vm.get("team_name")),
        _fmt(vm.get("subscription_plan")),
        _fmt(vm.get("purpose")),
        _fmt(vm.get("start_date")),
        _fmt(vm.get("planned_end_date")),
        _fmt(vm.get("status")),
        _fmt(vm.get("deleted_date")),
        str(float(vm.get("daily_cost") or 0)),
    ]


def sync_all():
    """Rewrite the sheet from the current MongoDB state. Called in a background thread."""
    if not os.environ.get("GS_SHEET_ID"):
        return
    try:
        import app as _app
        if _app.db is None:
            print("[sheets] db not ready — skipping sync", flush=True)
            return
        vms = list(_app.db.vms.find({}, {
            "vm_name": 1, "cloud_provider": 1, "ip_address": 1,
            "requested_by": 1, "requester_email": 1, "team_name": 1,
            "subscription_plan": 1, "purpose": 1,
            "start_date": 1, "planned_end_date": 1, "status": 1,
            "deleted_date": 1, "daily_cost": 1,
        }).sort("vm_name", 1))

        rows = [HEADERS] + [_vm_row(v) for v in vms]

        with _lock:
            ws = _sheet()
            ws.clear()
            ws.update(rows, value_input_option="USER_ENTERED")

        print(f"[sheets] Google Sheet synced — {len(vms)} VM(s).", flush=True)
        log.info("Google Sheet synced — %d VM(s).", len(vms))
    except Exception as exc:
        import traceback
        print(f"[sheets] sync failed: {exc}", flush=True)
        traceback.print_exc()
        log.error("Google Sheet sync failed: %s", exc)


def sync_async():
    """Sync the sheet. Runs directly — Sheets API is fast enough (~1-2s) for write ops."""
    sync_all()
