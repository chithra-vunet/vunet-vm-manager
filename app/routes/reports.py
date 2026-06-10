import csv
import io
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required
from app.models.vm import get_distinct_teams, CLOUD_PROVIDERS
import app as _app

reports_bp = Blueprint("reports", __name__, url_prefix="/vm-manager/reports")


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

@reports_bp.route("/expiring/")
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
                "vm_id":            str(d["_id"]),
                "vm_name":          d["vm_name"],
                "ip_address":       d.get("ip_address", "NA"),
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
            "vm_id":            str(d["_id"]),
            "vm_name":          d["vm_name"],
            "ip_address":       d.get("ip_address", "NA"),
            "cloud_provider":   d["cloud_provider"],
            "team_name":        d["team_name"],
            "requested_by":     d.get("requested_by", ""),
            "planned_end_date": d["planned_end_date"].strftime("%Y-%m-%d"),
            "days_left":        days_left,
            "days_overdue":     0,
            "daily_cost":       float(d.get("daily_cost", 0)),
        })
    return jsonify(result)


@reports_bp.route("/cost-by-provider/")
@login_required
def cost_by_provider():
    from collections import defaultdict
    today     = _today()
    start_s   = request.args.get("start")
    end_s     = request.args.get("end")
    start     = datetime.strptime(start_s, "%Y-%m-%d") if start_s else today.replace(day=1)
    end       = datetime.strptime(end_s,   "%Y-%m-%d") if end_s   else today
    range_end = min(end + timedelta(days=1), today)  # past end dates are inclusive; today is exclusive

    range_match = {
        "start_date": {"$lt": range_end},
        "$or": [{"deleted_date": None}, {"deleted_date": {"$gte": start}}],
    }
    vms = list(_db().vms.find(range_match,
                              {"cloud_provider": 1, "daily_cost": 1,
                               "start_date": 1, "deleted_date": 1}))

    provider_data = defaultdict(lambda: {"total_cost": 0.0, "daily_sum": 0.0, "vm_count": 0})
    for vm in vms:
        overlap_start = max(vm["start_date"], start)
        overlap_end   = min(vm.get("deleted_date") or range_end, range_end)
        overlap_days  = max(0, (overlap_end - overlap_start).days)
        provider = vm.get("cloud_provider") or "Unknown"
        daily    = float(vm.get("daily_cost", 0))
        provider_data[provider]["total_cost"] += daily * overlap_days
        provider_data[provider]["daily_sum"]  += daily
        provider_data[provider]["vm_count"]   += 1

    grand_total = sum(d["total_cost"] for d in provider_data.values())
    data = []
    for provider, d in sorted(provider_data.items(), key=lambda x: -x[1]["total_cost"]):
        tc = round(d["total_cost"], 2)
        data.append({
            "provider":   provider,
            "vm_count":   d["vm_count"],
            "total_cost": tc,
            "daily_cost": round(d["daily_sum"], 2),
            "pct":        round(tc / grand_total * 100, 1) if grand_total else 0,
        })
    return jsonify(data)


@reports_bp.route("/cost-compare/")
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
        from collections import defaultdict
        ms         = datetime(y, m, 1)
        me_full    = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
        me         = min(me_full, today)  # cap at today — no future days
        if me <= ms:
            return {}
        q   = {
            "start_date": {"$lt": me},
            "$or": [{"deleted_date": None}, {"deleted_date": {"$gte": ms}}],
        }
        vms    = list(_db().vms.find(q, {"cloud_provider": 1, "daily_cost": 1,
                                         "start_date": 1, "deleted_date": 1}))
        result = defaultdict(float)
        for vm in vms:
            overlap_start = max(vm["start_date"], ms)
            overlap_end   = min(vm.get("deleted_date") or me, me)
            overlap_days  = max(0, (overlap_end - overlap_start).days)
            result[vm.get("cloud_provider") or "Unknown"] += float(vm.get("daily_cost", 0)) * overlap_days
        return {p: round(c, 2) for p, c in result.items()}

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


def _team_match(request):
    """Build the shared $match dict for usage-by-team queries."""
    providers      = request.args.getlist("provider")
    exclude_provs  = request.args.getlist("exclude_provider")
    teams          = request.args.getlist("team") or ([request.args.get("team")] if request.args.get("team") else [])
    status_filter  = request.args.get("status", "Active")
    start_s        = request.args.get("start")
    end_s          = request.args.get("end")

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
        effective = [p for p in providers if p not in exclude_provs]
        match["cloud_provider"] = {"$in": effective}
    elif exclude_provs:
        match["cloud_provider"] = {"$nin": exclude_provs}
    if teams:
        match["team_name"] = {"$in": teams}
    return match


@reports_bp.route("/usage-by-team/")
@login_required
def usage_by_team():
    from collections import defaultdict
    start_s   = request.args.get("start")
    end_s     = request.args.get("end")
    has_range = bool(start_s and end_s)
    if has_range:
        today_    = _today()
        start     = datetime.strptime(start_s, "%Y-%m-%d")
        end       = datetime.strptime(end_s,   "%Y-%m-%d")
        range_end = min(end + timedelta(days=1), today_)  # past end dates are inclusive; today is exclusive

    match = _team_match(request)
    vms   = list(_db().vms.find(match, {
        "team_name": 1, "daily_cost": 1, "start_date": 1, "deleted_date": 1
    }))

    team_data = defaultdict(lambda: {"total_cost": 0.0, "total_daily_cost": 0.0, "vm_count": 0})
    for vm in vms:
        team  = vm.get("team_name") or "Unknown"
        daily = float(vm.get("daily_cost", 0))
        team_data[team]["total_daily_cost"] += daily
        team_data[team]["vm_count"]         += 1
        if has_range:
            overlap_start = max(vm["start_date"], start)
            overlap_end   = min(vm.get("deleted_date") or range_end, range_end)
            overlap_days  = max(0, (overlap_end - overlap_start).days)
            team_data[team]["total_cost"] += daily * overlap_days

    grand_daily = sum(d["total_daily_cost"] for d in team_data.values())
    data = []
    for team, d in sorted(team_data.items(), key=lambda x: -x[1]["total_daily_cost"]):
        total_d = round(d["total_daily_cost"], 2)
        data.append({
            "team":             team,
            "vm_count":         d["vm_count"],
            "total_daily_cost": total_d,
            "total_cost":       round(d["total_cost"], 2) if has_range else None,
            "pct":              round(total_d / grand_daily * 100, 1) if grand_daily else 0,
        })
    return jsonify(data)


@reports_bp.route("/top-expensive/")
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
        })
    return jsonify(result)


@reports_bp.route("/trends/compare/")
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
    cap        = min(cur_end, today)
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
    vms   = list(_db().vms.find(q, {"daily_cost": 1, "start_date": 1, "deleted_date": 1}))
    count = len(vms)
    total = 0.0
    for vm in vms:
        overlap_start = max(vm["start_date"], period_start)
        overlap_end   = min(vm.get("deleted_date") or period_end, period_end)
        overlap_days  = max(0, (overlap_end - overlap_start).days)
        total += float(vm.get("daily_cost", 0)) * overlap_days
    return count, round(total, 2)


@reports_bp.route("/trends/")
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
            y_end = datetime(y + 1, 1, 1)
            c, cost = _active_count_and_cost(datetime(y, 1, 1), min(y_end, today))
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
            c, cost = _active_count_and_cost(m_start, min(m_end, today))
            labels.append(m_start.strftime("%b %Y"))
            vm_counts.append(c)
            cost_totals.append(cost)
        cost_label = "Estimated Monthly Cost (INR)"

    return jsonify({"labels": labels, "vm_counts": vm_counts, "cost_totals": cost_totals,
                    "cost_label": cost_label})


# ── CSV exports ────────────────────────────────────────────────────────────────

@reports_bp.route("/export/expiring/")
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
        w.writerow(["VM Name", "IP Address", "Cloud Provider", "Team", "Requested By",
                    "Planned End Date", "Days Overdue", "Daily Cost (INR)"])
        for d in docs:
            w.writerow([d["vm_name"], d.get("ip_address", "NA"), d["cloud_provider"], d["team_name"],
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
        w.writerow(["VM Name", "IP Address", "Cloud Provider", "Team", "Requested By",
                    "Planned End Date", "Days Left", "Daily Cost (INR)"])
        for d in docs:
            w.writerow([d["vm_name"], d.get("ip_address", "NA"), d["cloud_provider"], d["team_name"],
                        d.get("requested_by", ""),
                        d["planned_end_date"].strftime("%Y-%m-%d"),
                        (d["planned_end_date"] - today).days,
                        float(d.get("daily_cost", 0))])
        fname = f"expiring_vms_{date.today().isoformat()}.csv"

    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@reports_bp.route("/export/cost-by-provider/")
@login_required
def export_cost_by_provider():
    from collections import defaultdict
    today     = _today()
    start_s   = request.args.get("start")
    end_s     = request.args.get("end")
    start     = datetime.strptime(start_s, "%Y-%m-%d") if start_s else today.replace(day=1)
    end       = datetime.strptime(end_s,   "%Y-%m-%d") if end_s   else today
    range_end = min(end + timedelta(days=1), today)  # past end dates are inclusive; today is exclusive

    range_match = {
        "start_date": {"$lt": range_end},
        "$or": [{"deleted_date": None}, {"deleted_date": {"$gte": start}}],
    }
    vms = list(_db().vms.find(range_match,
                              {"cloud_provider": 1, "daily_cost": 1,
                               "start_date": 1, "deleted_date": 1}))

    provider_data = defaultdict(lambda: {"total_cost": 0.0, "daily_sum": 0.0, "vm_count": 0})
    for vm in vms:
        overlap_start = max(vm["start_date"], start)
        overlap_end   = min(vm.get("deleted_date") or range_end, range_end)
        overlap_days  = max(0, (overlap_end - overlap_start).days)
        provider = vm.get("cloud_provider") or "Unknown"
        daily    = float(vm.get("daily_cost", 0))
        provider_data[provider]["total_cost"] += daily * overlap_days
        provider_data[provider]["daily_sum"]  += daily
        provider_data[provider]["vm_count"]   += 1

    grand_total = sum(d["total_cost"] for d in provider_data.values())
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Cloud Provider", "VM Count", "Daily Cost (INR)", "Total Cost (INR)", "% Contribution"])
    for provider, d in sorted(provider_data.items(), key=lambda x: -x[1]["total_cost"]):
        tc  = round(d["total_cost"], 2)
        pct = f"{round(tc / grand_total * 100, 1)}%" if grand_total else "0%"
        w.writerow([provider, d["vm_count"], round(d["daily_sum"], 2), tc, pct])
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=cost_by_provider_{date.today().isoformat()}.csv"})


@reports_bp.route("/export/usage-by-team/")
@login_required
def export_usage_by_team():
    from collections import defaultdict
    start_s   = request.args.get("start")
    end_s     = request.args.get("end")
    has_range = bool(start_s and end_s)
    if has_range:
        today_    = _today()
        start     = datetime.strptime(start_s, "%Y-%m-%d")
        end       = datetime.strptime(end_s,   "%Y-%m-%d")
        range_end = min(end + timedelta(days=1), today_)  # past end dates are inclusive; today is exclusive

    match = _team_match(request)
    vms   = list(_db().vms.find(match, {
        "team_name": 1, "daily_cost": 1, "start_date": 1, "deleted_date": 1
    }))

    team_data = defaultdict(lambda: {"total_cost": 0.0, "total_daily_cost": 0.0, "vm_count": 0})
    for vm in vms:
        team  = vm.get("team_name") or "Unknown"
        daily = float(vm.get("daily_cost", 0))
        team_data[team]["total_daily_cost"] += daily
        team_data[team]["vm_count"]         += 1
        if has_range:
            overlap_start = max(vm["start_date"], start)
            overlap_end   = min(vm.get("deleted_date") or range_end, range_end)
            overlap_days  = max(0, (overlap_end - overlap_start).days)
            team_data[team]["total_cost"] += daily * overlap_days

    grand_daily   = sum(d["total_daily_cost"] for d in team_data.values())
    provider_note = ", ".join(request.args.getlist("provider")) or "All"

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow([f"# Cloud Provider filter: {provider_note}"])
    if has_range:
        w.writerow(["Team", "VM Count", "Total Daily Cost (INR)", "Total Cost in Period (INR)", "% Contribution"])
    else:
        w.writerow(["Team", "VM Count", "Total Daily Cost (INR)", "% Contribution"])
    for team, d in sorted(team_data.items(), key=lambda x: -x[1]["total_daily_cost"]):
        total_d = round(d["total_daily_cost"], 2)
        pct     = f"{round(total_d / grand_daily * 100, 1)}%" if grand_daily else "0%"
        if has_range:
            w.writerow([team, d["vm_count"], total_d, round(d["total_cost"], 2), pct])
        else:
            w.writerow([team, d["vm_count"], total_d, pct])
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=usage_by_team_{date.today().isoformat()}.csv"})


@reports_bp.route("/export/cloud-team-consolidated/")
@login_required
def export_cloud_team_consolidated():
    """
    Export Cloud Provider × Team cost breakdown in one flat CSV.
    Matches the 'Cloud + Project Team + Cost' layout used in monthly tracker sheets.
    """
    match    = _team_match(request)
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id":              {"cloud": "$cloud_provider", "team": "$team_name"},
            "vm_count":         {"$sum": 1},
            "total_daily_cost": {"$sum": "$daily_cost"},
        }},
        {"$sort": {"_id.cloud": 1, "total_daily_cost": -1}},
    ]
    raw         = list(_db().vms.aggregate(pipeline))
    grand_total = sum(float(r["total_daily_cost"]) for r in raw)

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Cloud", "Team", "VM Count", "Cost (INR)", "% of Total"])
    for r in raw:
        total = float(r["total_daily_cost"])
        pct   = f"{round(total / grand_total * 100, 1)}%" if grand_total else "0%"
        w.writerow([r["_id"]["cloud"], r["_id"]["team"], r["vm_count"], round(total, 2), pct])

    # Summary rows at the bottom
    w.writerow([])
    w.writerow(["--- Summary by Cloud ---"])
    w.writerow(["Cloud", "Total Cost (INR)", "% of Total"])
    cloud_totals = {}
    for r in raw:
        c = r["_id"]["cloud"]
        cloud_totals[c] = cloud_totals.get(c, 0) + float(r["total_daily_cost"])
    for cloud, total in sorted(cloud_totals.items(), key=lambda x: -x[1]):
        pct = f"{round(total / grand_total * 100, 1)}%" if grand_total else "0%"
        w.writerow([cloud, round(total, 2), pct])
    w.writerow(["Grand Total", round(grand_total, 2), "100%"])

    buf.seek(0)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=cloud_team_costs_{date.today().isoformat()}.csv"})
