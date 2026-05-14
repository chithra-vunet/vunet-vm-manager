import csv
import io
import re
from datetime import datetime, date
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify, Response)
from flask_login import login_required
from app.decorators import role_required
from app.models.vm import (
    get_all_vms, get_vm, create_vm, update_vm, deactivate_vm, delete_vm,
    get_distinct_teams, get_stats, CLOUD_PROVIDERS,
)

dashboard_bp = Blueprint("dashboard", __name__)

PER_PAGE = 25


# ── Smart CSV import helpers ───────────────────────────────────────────────────

_DATE_FORMATS = [
    "%d-%m-%Y", "%d-%m-%y",      # 24-07-2025 or 14-11-26
    "%d/%m/%Y", "%d/%m/%y",
    "%Y-%m-%d",
    "%d-%b-%Y", "%d-%b-%y",      # 9-Apr-25 or 9-Apr-2025
    "%d-%B-%Y", "%d-%B-%y",
    "%d %b %Y", "%d %b %y",
    "%d %B %Y", "%d %B %y",
    "%m/%d/%Y", "%m-%d-%Y",
]

def _parse_flex_date(value):
    """Parse date strings in many formats → 'YYYY-MM-DD' or ''."""
    if not value:
        return ""
    value = str(value).strip().split(" ")[0].split("T")[0]  # strip time part
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.year < 2000:          # 2-digit year like 24 → 2024
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _extract_planned_end(vm_name):
    """Guess planned_end_date from VM name patterns like 'foo-to-30-05-2026'."""
    if not vm_name:
        return ""
    lname = vm_name.lower()
    if any(x in lname for x in ("long-term", "longterm", "long term", "to-long", "to_long")):
        return ""

    m = re.search(r"\bto[-_](\d{1,2}[-_][a-zA-Z]{3,9}[-_](?:20)?\d{2})\b", vm_name, re.I)
    if m:
        d = _parse_flex_date(m.group(1).replace("_", "-"))
        if d:
            return d

    m = re.search(r"\bto[-_](\d{1,2}[-_]\d{1,2}[-_](?:20)?\d{2})\b", vm_name, re.I)
    if m:
        d = _parse_flex_date(m.group(1).replace("_", "-"))
        if d:
            return d
    return ""


def _status_map(raw):
    """Map various status strings to Active / Inactive."""
    return "Active" if str(raw).strip().lower() == "active" else "Inactive"


def _float(value):
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


# Ordered keyword groups for flexible column detection.
# For each field, groups are tried in order; all keywords in a group must appear in the column name.
_FIELD_KEYWORDS = {
    "vm_name":           [["vm name"], ["vm_name"]],
    "ip_address":        [["public_ip_address"], ["public ip"], ["ip address"], ["ip_address"]],
    "start_date":        [["creat"], ["start date"], ["start_date"]],
    "deleted_date":      [["deletion date"], ["deletion_date"], ["deleted date"]],
    "status":            [["current status"], ["status"]],
    "daily_cost":        [["per day cost"], ["per_day_cost"], ["daily cost"], ["day cost"]],
    "requested_by":      [["requested by"], ["requested_by"], ["owner"]],
    "team_name":         [["owned by team"], ["team name"], ["team_name"], ["team"]],
    "cloud_provider":    [["cloud provider"], ["cloud_provider"]],
    "subscription_plan": [["subscription plan"], ["subscription_plan"], ["plan"]],
    "purpose":           [["purpose"]],
    "planned_end_date":  [["planned end"], ["planned_end"]],
}


def _norm_key(k):
    """Normalize a column name: lowercase and collapse all whitespace (including newlines)."""
    return " ".join((k or "").lower().split())


def _find_col(row, keyword_groups):
    """Return the value of the first column whose normalized name matches any keyword group."""
    for keywords in keyword_groups:
        for k, v in row.items():
            nk = _norm_key(k)
            if all(kw.lower() in nk for kw in keywords):
                return (v or "").strip()
    return ""


def _detect_and_parse(text):
    """
    Skip leading metadata/title rows and return parsed CSV row dicts.
    The header row is the first row containing recognizable column keywords.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    header_idx = 0
    for i, line in enumerate(lines[:8]):
        try:
            cells = [c.strip().strip('"') for c in next(csv.reader(io.StringIO(line)))]
        except Exception:
            continue
        joined = " ".join(cells).lower()
        if any(kw in joined for kw in ("name", "ip", "status", "owner", "creat", "cost", "team", "cloud")):
            header_idx = i
            break
    return list(csv.DictReader(io.StringIO("\n".join(lines[header_idx:]))))


def _map_row(row, default_provider=""):
    """
    Universal flexible row mapper — works with any CSV layout.
    Uses keyword matching on column names to detect each field.
    Returns None for rows with no recognisable VM name.
    """
    # VM name: prefer explicit "vm name"/"vm_name", then fall back to a plain "name" column
    name = _find_col(row, _FIELD_KEYWORDS["vm_name"])
    if not name:
        for k, v in row.items():
            nk = _norm_key(k)
            if nk == "name" or (nk.endswith(" name") and not any(
                    x in nk for x in ("team", "owner", "file", "user"))):
                name = (v or "").strip()
                if name:
                    break

    # Skip blank rows, placeholder values, and pure-number cells (serial-number columns)
    if not name or name in ("-", "—", "N/A", "NA", "na") or name.isdigit():
        return None

    # Cloud provider: explicit column wins over user-supplied default
    provider = _find_col(row, _FIELD_KEYWORDS["cloud_provider"]) or default_provider

    # IP address (normalize common placeholder values to empty string)
    ip = _find_col(row, _FIELD_KEYWORDS["ip_address"])
    if not ip:
        for k, v in row.items():
            nk = _norm_key(k)
            if "ip" in nk and not any(x in nk for x in ("type", "cidr", "range", "pool", "email")):
                ip = (v or "").strip()
                if ip:
                    break
    if ip in ("-", "—", "NA", "N/A", "na"):
        ip = ""

    status_raw = _find_col(row, _FIELD_KEYWORDS["status"])
    status     = _status_map(status_raw) if status_raw else "Active"

    del_raw   = _find_col(row, _FIELD_KEYWORDS["deleted_date"])
    start_raw = _find_col(row, _FIELD_KEYWORDS["start_date"])
    cost_raw  = _find_col(row, _FIELD_KEYWORDS["daily_cost"])
    owner     = _find_col(row, _FIELD_KEYWORDS["requested_by"])
    team      = _find_col(row, _FIELD_KEYWORDS["team_name"])
    plan      = _find_col(row, _FIELD_KEYWORDS["subscription_plan"])
    purpose   = _find_col(row, _FIELD_KEYWORDS["purpose"])

    # Planned end: explicit column first, then extract from VM name
    planned = _find_col(row, _FIELD_KEYWORDS["planned_end_date"]) or _extract_planned_end(name)

    return {
        "cloud_provider":    provider,
        "vm_name":           name,
        "ip_address":        ip,
        "requested_by":      owner,
        "team_name":         team,
        "start_date":        _parse_flex_date(start_raw),
        "planned_end_date":  planned,
        "status":            status,
        "deleted_date":      _parse_flex_date(del_raw) if del_raw and status == "Inactive" else "",
        "daily_cost":        _float(cost_raw),
        "subscription_plan": plan,
        "purpose":           purpose,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/")
@login_required
def index():
    search    = request.args.get("search", "").strip()
    providers = request.args.getlist("provider")
    teams     = request.args.getlist("team")
    status    = request.args.get("status", "All")
    page      = max(1, int(request.args.get("page", 1)))
    sort_by   = request.args.get("sort_by", "")
    sort_dir  = request.args.get("sort_dir", "asc")

    vms, total = get_all_vms(
        search    = search    or None,
        providers = providers or None,
        teams     = teams     or None,
        status    = status,
        page      = page,
        per_page  = PER_PAGE,
        sort_by   = sort_by   or None,
        sort_dir  = sort_dir,
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    return render_template(
        "dashboard.html",
        vms                = vms,
        stats              = get_stats(),
        all_teams          = get_distinct_teams(),
        cloud_providers    = CLOUD_PROVIDERS,
        search             = search,
        selected_providers = providers,
        selected_teams     = teams,
        selected_status    = status,
        page               = page,
        total_pages        = total_pages,
        total              = total,
        sort_by            = sort_by,
        sort_dir           = sort_dir,
    )


@dashboard_bp.route("/vms/add", methods=["POST"])
@login_required
@role_required("admin", "editor")
def add_vm():
    data = request.form.to_dict()
    try:
        create_vm(data)
        flash("VM added successfully.", "success")
    except Exception as exc:
        flash(f"Could not add VM: {exc}", "danger")
    return redirect(_back())


@dashboard_bp.route("/vms/<vm_id>/edit", methods=["POST"])
@login_required
@role_required("admin", "editor")
def edit_vm(vm_id):
    data = request.form.to_dict()
    try:
        update_vm(vm_id, data)
        flash("VM updated successfully.", "success")
    except Exception as exc:
        flash(f"Could not update VM: {exc}", "danger")
    return redirect(_back())


@dashboard_bp.route("/vms/<vm_id>/deactivate", methods=["POST"])
@login_required
@role_required("admin", "editor")
def deactivate(vm_id):
    deleted_on = request.form.get("deleted_date", "").strip()
    deactivate_vm(vm_id, deleted_on or None)
    flash("VM marked as Inactive.", "warning")
    return redirect(_back())


@dashboard_bp.route("/vms/<vm_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete(vm_id):
    delete_vm(vm_id)
    flash("VM permanently deleted.", "danger")
    return redirect(_back())


@dashboard_bp.route("/vms/<vm_id>/json")
@login_required
def vm_json(vm_id):
    vm = get_vm(vm_id)
    if vm:
        return jsonify(vm)
    return jsonify({"error": "Not found"}), 404


def _vm_fingerprint(data):
    """
    Unique key for a VM: (name, cloud_provider, ip_address) — all lowercased.
    Used to detect duplicates during import without relying on a DB unique index.
    """
    return (
        (data.get("vm_name")        or "").strip().lower(),
        (data.get("cloud_provider") or "").strip().lower(),
        (data.get("ip_address")     or "").strip().lower(),
    )


@dashboard_bp.route("/vms/import", methods=["POST"])
@login_required
@role_required("admin")
def import_vms():
    file = request.files.get("csv_file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please upload a valid CSV file.", "danger")
        return redirect(_back())

    default_provider = request.form.get("cloud_provider", "").strip()
    update_existing  = request.form.get("update_existing") == "1"

    try:
        text = file.read().decode("utf-8-sig")
        rows = _detect_and_parse(text)

        # Build a fingerprint → _id map of every VM already in the DB (one query)
        import app as _app
        existing = {}
        for doc in _app.db.vms.find({}, {"vm_name": 1, "cloud_provider": 1, "ip_address": 1}):
            fp = _vm_fingerprint(doc)
            existing[fp] = str(doc["_id"])

        added      = 0
        updated    = 0
        duplicates = 0
        skipped    = 0
        no_prov    = 0
        errors     = []

        for i, row in enumerate(rows, 1):
            try:
                data = _map_row(row, default_provider)
                if data is None:
                    skipped += 1
                    continue
                if not data.get("cloud_provider"):
                    no_prov += 1
                    continue

                fp = _vm_fingerprint(data)
                if fp in existing:
                    if update_existing:
                        update_vm(existing[fp], data)
                        updated += 1
                    else:
                        duplicates += 1
                else:
                    new_id = create_vm(data)
                    existing[fp] = new_id   # prevent intra-batch duplicates too
                    added += 1

            except Exception as exc:
                name_val = next((v for k, v in row.items()
                                 if "name" in _norm_key(k) and v), "?")
                errors.append(f"Row {i} ({name_val}): {exc}")

        parts = []
        if added:
            parts.append(f"{added} new VM(s) added")
        if updated:
            parts.append(f"{updated} existing VM(s) updated")
        if duplicates:
            parts.append(f"{duplicates} duplicate(s) skipped")
        if skipped:
            parts.append(f"{skipped} blank row(s) ignored")

        if parts:
            flash(" · ".join(parts) + ".", "success" if added or updated else "info")
        if no_prov:
            flash(f"{no_prov} row(s) skipped — no Cloud Provider column found in CSV.", "warning")
        if errors:
            flash(f"{len(errors)} row(s) had errors: " + "; ".join(errors[:5]), "warning")
        if not added and not updated and not errors and not no_prov and not duplicates:
            flash("No VMs imported. Make sure the file has columns for Name / IP / Status / "
                  "Cost / Owner / Team.", "warning")

    except Exception as exc:
        flash(f"Failed to read CSV: {exc}", "danger")

    return redirect(_back())


_CSV_HEADERS = [
    "Cloud Provider", "VM Name", "IP Address", "Requested By", "Team",
    "Subscription Plan", "Purpose",
    "Start Date", "Planned End Date", "Status", "Deleted Date",
    "Daily Cost (INR)", "Total Cost (INR)",
]


def _vm_csv_row(v):
    return [
        v["cloud_provider"], v["vm_name"], v["ip_address"],
        v.get("requested_by", ""), v["team_name"],
        v.get("subscription_plan", ""), v.get("purpose", ""),
        v.get("start_date", ""), v.get("planned_end_date", ""),
        v["status"], v.get("deleted_date") or "",
        v["daily_cost"], v.get("total_cost", 0),
    ]


def _write_csv(vms):
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(_CSV_HEADERS)
    for v in vms:
        w.writerow(_vm_csv_row(v))
    buf.seek(0)
    return buf


@dashboard_bp.route("/export/vms")
@login_required
def export_vms():
    search    = request.args.get("search", "").strip() or None
    providers = request.args.getlist("provider") or None
    teams     = request.args.getlist("team") or None
    status    = request.args.get("status", "All")
    vms, _    = get_all_vms(search=search, providers=providers,
                            teams=teams, status=status, page=1, per_page=10_000)
    filename  = f"vms_{date.today().isoformat()}.csv"
    return Response(_write_csv(vms).getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@dashboard_bp.route("/export/all")
@login_required
def export_all():
    vms, _   = get_all_vms(page=1, per_page=100_000)
    filename = f"all_vms_{date.today().isoformat()}.csv"
    return Response(_write_csv(vms).getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def _back():
    ref = request.referrer
    return ref if ref else url_for("dashboard.index")
