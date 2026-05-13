import csv
import io
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required
from app.models.vm import get_distinct_teams, CLOUD_PROVIDERS
import app as _app

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


def _db():
    return _app.db


def _today():
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


# ── Pages ──────────────────────────────────────────────────────────────────────

@reports_bp.route("/")
@login_required
def index():
    return render_template("reports.html",
                           cloud_providers=CLOUD_PROVIDERS,
                           all_teams=get_distinct_teams())


# ── JSON data endpoints ────────────────────────────────────────────────────────

@reports_bp.route("/expiring")
@login_required
def expiring():
    today     = _today()
    providers = request.args.getlist("provider")
    team      = request.args.get("team", "")

    def base_match(extra):
        m = dict(extra)
        if providers:
            m["cloud_provider"] = {"$in": providers}
        if team:
            m["team_name"] = team
        return m

    if request.args.get("overdue") == "1":
        docs = list(_db().vms.find(base_match({
            "status":           "Active",
            "planned_end_date": {"$lt": today},
        })).sort("planned_end_date", 1))
        result = []
        for d in docs:
            days_overdue = (today - d["planned_end_date"]).days
            result.append({
                "vm_name":          d["vm_name"],
                "cloud_provider":   d["cloud_provider"],
                "team_name":        d["team_name"],
                "requested_by":     d.get("requested_by", ""),
                "planned_end_date": d["planned_end_date"].strftime("%Y-%m-%d"),
                "days_left":        -days_overdue,
                "days_overdue":     days_overdue,
                "daily_cost":       float(d.get("daily_cost", 0)),
            })
        return jsonify(result)

    days   = max(1, int(request.args.get("days", 30)))
    cutoff = today + timedelta(days=days)
    docs   = list(_db().vms.find(base_match({
        "status":           "Active",
        "planned_end_date": {"$gte": today, "$lte": cutoff},
    })).sort("planned_end_date", 1))
    result = []
    for d in docs:
        days_left = (d["planned_end_date"] - today).days
        result.append({
            "vm_name":          d["vm_name"],
            "cloud_provider":   d["cloud_provider"],
            "team_name":        d["team_name"],
            "requested_by":     d.get("requested_by", ""),
            "planned_end_date": d["planned_end_date"].strftime("%Y-%m-%d"),
            "days_left":        days_left,
            "days_overdue":     0,
            "daily_cost":       float(d.get("daily_cost", 0)),
        })
    return jsonify(result)


@reports_bp.route("/cost-by-provider")
@login_required
def cost_by_provider():
    today    = _today()
    start_s  = request.args.get("start")
    end_s    = request.args.get("end")
    start    = datetime.strptime(start_s, "%Y-%m-%d") if start_s else today.replace(day=1)
    end      = datetime.strptime(end_s,   "%Y-%m-%d") if end_s   else today
    days_rng = max(1, (end - start).days + 1)

    pipeline = [
        {"$match": {"status": "Active"}},
        {"$group": {
            "_id":       "$cloud_provider",
            "daily_sum": {"$sum": "$daily_cost"},
            "vm_count":  {"$sum": 1},
        }},
        {"$sort": {"daily_sum": -1}},
    ]
    raw         = list(_db().vms.aggregate(pipeline))
    grand_total = sum(float(r["daily_sum"]) * days_rng for r in raw)
    data = []
    for r in raw:
        tc = round(float(r["daily_sum"]) * days_rng, 2)
        data.append({
            "provider":   r["_id"],
            "vm_count":   r["vm_count"],
            "total_cost": tc,
            "daily_cost": round(float(r["daily_sum"]), 2),
            "pct":        round(tc / grand_total * 100, 1) if grand_total else 0,
        })
    return jsonify(data)


@reports_bp.route("/cost-compare")
@login_required
def cost_compare():
    """Cost by provider for two months — powers the grouped comparison bar chart."""
    today  = _today()
    prev_m = today.month - 1 if today.month > 1 else 12
    prev_y = today.year if today.month > 1 else today.year - 1
    year1  = int(request.args.get("year1",  prev_y))
    month1 = int(request.args.get("month1", prev_m))
    year2  = int(request.args.get("year2",  today.year))
    month2 = int(request.args.get("month2", today.month))

    def cost_for_month(y, m):
        ms   = datetime(y, m, 1)
        me   = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
        days = (me - ms).days
        q    = {
            "start_date": {"$lt": me},
            "$or": [{"deleted_date": None}, {"deleted_date": {"$gte": ms}}],
        }
        pipeline = [
            {"$match": q},
            {"$group": {"_id": "$cloud_provider", "daily_sum": {"$sum": "$daily_cost"}}},
        ]
        return {r["_id"]: round(float(r["daily_sum"]) * days, 2)
                for r in _db().vms.aggregate(pipeline)}

    prev_data = cost_for_month(year1, month1)
    cur_data  = cost_for_month(year2, month2)
    providers = sorted(set(list(prev_data.keys()) + list(cur_data.keys())))

    m1_label = datetime(year1, month1, 1).strftime("%b %Y")
    m2_label = datetime(year2, month2, 1).strftime("%b %Y")

    rows = []
    for p in providers:
        prev_cost  = prev_data.get(p, 0)
        cur_cost   = cur_data.get(p, 0)
        pct_change = round((cur_cost - prev_cost) / prev_cost * 100, 1) if prev_cost else None
        rows.append({"provider": p, "prev": prev_cost, "cur": cur_cost, "pct_change": pct_change})

    return jsonify({"m1_label": m1_label, "m2_label": m2_label, "rows": rows})


@reports_bp.route("/usage-by-team")
@login_required
def usage_by_team():
    providers     = request.args.getlist("provider")
    status_filter = request.args.get("status", "Active")
    start_s       = request.args.get("start")
    end_s         = request.args.get("end")

    match = {}
    if start_s or end_s:
        start = datetime.strptime(start_s, "%Y-%m-%d") if start_s else datetime(2000, 1, 1)
        end   = (datetime.strptime(end_s, "%Y-%m-%d") + timedelta(days=1)) if end_s else _today() + timedelta(days=1)
        match["start_date"] = {"$lt": end}
        match["$or"] = [{"deleted_date": None}, {"deleted_date": {"$gte": start}}]
    else:
        if status_filter != "All":
            match["status"] = status_filter
    if providers:
        match["cloud_provider"] = {"$in": providers}

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id":              "$team_name",
            "vm_count":         {"$sum": 1},
            "total_daily_cost": {"$sum": "$daily_cost"},
        }},
        {"$sort": {"total_daily_cost": -1}},
    ]
    raw         = list(_db().vms.aggregate(pipeline))
    grand_total = sum(float(r["total_daily_cost"]) for r in raw)
    data = []
    for r in raw:
        cnt   = r["vm_count"]
        total = float(r["total_daily_cost"])
        data.append({
            "team":             r["_id"],
            "vm_count":         cnt,
            "total_daily_cost": round(total, 2),
            "avg_daily_cost":   round(total / cnt, 2) if cnt else 0,
            "pct":              round(total / grand_total * 100, 1) if grand_total else 0,
        })
    return jsonify(data)


@reports_bp.route("/top-expensive")
@login_required
def top_expensive():
    n      = min(20, max(1, int(request.args.get("n", 5))))
    status = request.args.get("status", "Active")
    query  = {} if status == "All" else {"status": status}

    docs   = list(_db().vms.find(query).sort("daily_cost", -1).limit(n))
    result = []
    for d in docs:
        end_date = d.get("planned_end_date")
        result.append({
            "vm_name":          d["vm_name"],
            "cloud_provider":   d["cloud_provider"],
            "team_name":        d["team_name"],
            "daily_cost":       float(d.get("daily_cost", 0)),
            "monthly_est":      round(float(d.get("daily_cost", 0)) * 30, 2),
            "planned_end_date": end_date.strftime("%Y-%m-%d") if end_date else None,
            "tags":             d.get("tags", []),
        })
    return jsonify(result)


@reports_bp.route("/trends/compare")
@login_required
def trends_compare():
    today      = _today()
    year       = int(request.args.get("year",  today.year))
    month      = int(request.args.get("month", today.month))
    cur_start  = datetime(year, month, 1)
    cur_end    = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    prev_month = month - 1 if month > 1 else 12
    prev_year  = year if month > 1 else year - 1
    prev_start = datetime(prev_year, prev_month, 1)
    cap        = min(cur_end, today + timedelta(days=1))
    cur_count,  cur_cost  = _active_count_and_cost(cur_start, cap)
    prev_count, prev_cost = _active_count_and_cost(prev_start, cur_start)
    return jsonify({
        "cur":  {"label": cur_start.strftime("%b %Y"),  "count": cur_count,  "cost": cur_cost},
        "prev": {"label": prev_start.strftime("%b %Y"), "count": prev_count, "cost": prev_cost},
    })


def _active_count_and_cost(period_start, period_end):
    q = {
        "start_date": {"$lt": period_end},
        "$or": [{"deleted_date": None}, {"deleted_date": {"$gte": period_start}}],
    }
    count = _db().vms.count_documents(q)
    res   = list(_db().vms.aggregate([
        {"$match": q},
        {"$group": {"_id": None, "s": {"$sum": "$daily_cost"}}},
    ]))
    days  = (period_end - period_start).days
    total = float(res[0]["s"]) * days if res else 0.0
    return count, round(total, 2)


@reports_bp.route("/trends")
@login_required
def trends():
    today = _today()
    mode  = request.args.get("mode", "monthly")
    labels, vm_counts, cost_totals = [], [], []

    if mode == "specific":
        year        = int(request.args.get("year",  today.year))
        month       = int(request.args.get("month", today.month))
        month_start = datetime(year, month, 1)
        month_end   = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        cap = min(month_end, today + timedelta(days=1))
        day = month_start
        while day < cap:
            next_day = day + timedelta(days=1)
            c, cost  = _active_count_and_cost(day, next_day)
            labels.append(day.strftime("%d %b"))
            vm_counts.append(c)
            cost_totals.append(cost)
            day = next_day
        cost_label = "Daily Cost (INR)"

    elif mode == "yearly":
        num_years = max(1, min(10, int(request.args.get("years", 3))))
        for y in range(today.year - num_years + 1, today.year + 1):
            c, cost = _active_count_and_cost(datetime(y, 1, 1), datetime(y + 1, 1, 1))
            labels.append(str(y))
            vm_counts.append(c)
            cost_totals.append(cost)
        cost_label = "Estimated Annual Cost (INR)"

    elif mode == "custom":
        start_s = request.args.get("start")
        end_s   = request.args.get("end")
        if not start_s or not end_s:
            return jsonify({"labels": [], "vm_counts": [], "cost_totals": [], "cost_label": "Cost (INR)"})
        c_start = datetime.strptime(start_s, "%Y-%m-%d")
        c_end   = datetime.strptime(end_s,   "%Y-%m-%d") + timedelta(days=1)
        cur     = datetime(c_start.year, c_start.month, 1)
        while cur < c_end:
            nxt     = datetime(cur.year + 1, 1, 1) if cur.month == 12 else datetime(cur.year, cur.month + 1, 1)
            seg_end = min(nxt, c_end)
            c, cost = _active_count_and_cost(max(cur, c_start), seg_end)
            labels.append(cur.strftime("%b %Y"))
            vm_counts.append(c)
            cost_totals.append(cost)
            cur = nxt
        cost_label = "Estimated Monthly Cost (INR)"

    else:  # rolling months
        num_months = max(1, min(36, int(request.args.get("months", 12))))
        for i in range(num_months - 1, -1, -1):
            month = today.month - i
            year  = today.year
            while month <= 0:
                month += 12
                year  -= 1
            m_start = datetime(year, month, 1)
            m_end   = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
            c, cost = _active_count_and_cost(m_start, m_end)
            labels.append(m_start.strftime("%b %Y"))
            vm_counts.append(c)
            cost_totals.append(cost)
        cost_label = "Estimated Monthly Cost (INR)"

    return jsonify({"labels": labels, "vm_counts": vm_counts, "cost_totals": cost_totals,
                    "cost_label": cost_label})


# ── CSV exports ────────────────────────────────────────────────────────────────

@reports_bp.route("/export/expiring")
@login_required
def export_expiring():
    today = _today()
    buf   = io.StringIO()
    w     = csv.writer(buf)

    if request.args.get("overdue") == "1":
        docs = list(_db().vms.find({
            "status":           "Active",
            "planned_end_date": {"$lt": today},
        }).sort("planned_end_date", 1))
        w.writerow(["VM Name", "Cloud Provider", "Team", "Requested By",
                    "Planned End Date", "Days Overdue", "Daily Cost (INR)"])
        for d in docs:
            w.writerow([d["vm_name"], d["cloud_provider"], d["team_name"],
                        d.get("requested_by", ""),
                        d["planned_end_date"].strftime("%Y-%m-%d"),
                        (today - d["planned_end_date"]).days,
                        float(d.get("daily_cost", 0))])
        fname = f"overdue_vms_{date.today().isoformat()}.csv"
    else:
        days   = max(1, int(request.args.get("days", 30)))
        cutoff = today + timedelta(days=days)
        docs   = list(_db().vms.find({
            "status":           "Active",
            "planned_end_date": {"$gte": today, "$lte": cutoff},
        }).sort("planned_end_date", 1))
        w.writerow(["VM Name", "Cloud Provider", "Team", "Requested By",
                    "Planned End Date", "Days Left", "Daily Cost (INR)"])
        for d in docs:
            w.writerow([d["vm_name"], d["cloud_provider"], d["team_name"],
                        d.get("requested_by", ""),
                        d["planned_end_date"].strftime("%Y-%m-%d"),
                        (d["planned_end_date"] - today).days,
                        float(d.get("daily_cost", 0))])
        fname = f"expiring_vms_{date.today().isoformat()}.csv"

    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@reports_bp.route("/export/cost-by-provider")
@login_required
def export_cost_by_provider():
    today    = _today()
    start_s  = request.args.get("start")
    end_s    = request.args.get("end")
    start    = datetime.strptime(start_s, "%Y-%m-%d") if start_s else today.replace(day=1)
    end      = datetime.strptime(end_s,   "%Y-%m-%d") if end_s   else today
    days_rng = max(1, (end - start).days + 1)
    pipeline = [
        {"$match": {"status": "Active"}},
        {"$group": {"_id": "$cloud_provider", "daily_sum": {"$sum": "$daily_cost"}, "vm_count": {"$sum": 1}}},
        {"$sort": {"daily_sum": -1}},
    ]
    raw         = list(_db().vms.aggregate(pipeline))
    grand_total = sum(float(r["daily_sum"]) * days_rng for r in raw)
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Cloud Provider", "VM Count", "Daily Cost (INR)", "Total Cost (INR)", "% Contribution"])
    for r in raw:
        tc  = round(float(r["daily_sum"]) * days_rng, 2)
        pct = f"{round(tc / grand_total * 100, 1)}%" if grand_total else "0%"
        w.writerow([r["_id"], r["vm_count"], round(float(r["daily_sum"]), 2), tc, pct])
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=cost_by_provider_{date.today().isoformat()}.csv"})


@reports_bp.route("/export/usage-by-team")
@login_required
def export_usage_by_team():
    providers     = request.args.getlist("provider")
    status_filter = request.args.get("status", "Active")
    start_s       = request.args.get("start")
    end_s         = request.args.get("end")
    match = {}
    if start_s or end_s:
        start = datetime.strptime(start_s, "%Y-%m-%d") if start_s else datetime(2000, 1, 1)
        end   = (datetime.strptime(end_s, "%Y-%m-%d") + timedelta(days=1)) if end_s else _today() + timedelta(days=1)
        match["start_date"] = {"$lt": end}
        match["$or"] = [{"deleted_date": None}, {"deleted_date": {"$gte": start}}]
    else:
        if status_filter != "All":
            match["status"] = status_filter
    if providers:
        match["cloud_provider"] = {"$in": providers}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": "$team_name", "vm_count": {"$sum": 1}, "total_daily_cost": {"$sum": "$daily_cost"}}},
        {"$sort": {"total_daily_cost": -1}},
    ]
    raw         = list(_db().vms.aggregate(pipeline))
    grand_total = sum(float(r["total_daily_cost"]) for r in raw)
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Team", "VM Count", "Total Daily Cost (INR)", "Avg Daily Cost (INR)", "% Contribution"])
    for r in raw:
        cnt   = r["vm_count"]
        total = float(r["total_daily_cost"])
        pct   = f"{round(total / grand_total * 100, 1)}%" if grand_total else "0%"
        w.writerow([r["_id"], cnt, round(total, 2), round(total / cnt, 2) if cnt else 0, pct])
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=usage_by_team_{date.today().isoformat()}.csv"})
