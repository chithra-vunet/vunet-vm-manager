import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def _html_table(vms, today):
    rows = ""
    for vm in vms:
        end  = vm["planned_end_date"]
        days = max(0, (end - today).days)
        color = "#dc3545" if days <= 1 else "#fd7e14"
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px'>{vm['vm_name']}</td>"
            f"<td style='padding:6px 12px'>{vm.get('cloud_provider','—')}</td>"
            f"<td style='padding:6px 12px'>{vm.get('team_name','—')}</td>"
            f"<td style='padding:6px 12px'>{vm.get('requested_by','—')}</td>"
            f"<td style='padding:6px 12px'>{end.strftime('%d %b %Y')}</td>"
            f"<td style='padding:6px 12px;font-weight:bold;color:{color}'>{days} day(s)</td>"
            f"</tr>"
        )
    return f"""
<html><body style="font-family:Arial,sans-serif;color:#222;font-size:14px;margin:24px">
<p>Hello,</p>
<p>The following VM(s) are expiring soon. Please take action to extend or deactivate them.</p>
<table border="1" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;width:100%;font-size:13px">
  <thead style="background:#1a3a5c;color:#fff">
    <tr>
      <th style="padding:8px 12px;text-align:left">VM Name</th>
      <th style="padding:8px 12px;text-align:left">Provider</th>
      <th style="padding:8px 12px;text-align:left">Team</th>
      <th style="padding:8px 12px;text-align:left">Requested By</th>
      <th style="padding:8px 12px;text-align:left">Planned End</th>
      <th style="padding:8px 12px;text-align:left">Days Left</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<p style="margin-top:16px">Log in to <strong>VUNet VM Manager</strong> to manage these VMs.</p>
<p style="color:#888;font-size:11px;margin-top:24px">— VUNet VM Manager automated alert</p>
</body></html>"""


def _send_email(username, password, recipients, subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = username
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.login(username, password)
        server.sendmail(username, recipients, msg.as_string())


def send_expiry_alerts(app):
    """Find Active VMs expiring soon and send email alerts based on DB settings."""
    with app.app_context():
        from app.models.settings import get_settings
        import app as _app_module

        s = get_settings()

        if not s.get("alerts_enabled"):
            log.info("Expiry alerts are disabled in settings.")
            return
        if not s.get("mail_username") or not s.get("mail_password"):
            log.warning("Email not configured — skipping expiry alerts.")
            return

        today      = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        alert_days = int(s.get("alert_days", 2))
        deadline   = today + timedelta(days=alert_days)
        admin      = (s.get("admin_email") or "").strip()

        vms = list(_app_module.db.vms.find({
            "status": "Active",
            "planned_end_date": {"$gt": today, "$lte": deadline},
        }))

        if not vms:
            log.info("Expiry check: no VMs expiring within %d day(s).", alert_days)
            return

        log.info("Expiry check: %d VM(s) expiring within %d day(s).", len(vms), alert_days)

        # Send per-requester alert
        by_requester: dict[str, list] = {}
        for vm in vms:
            email = (vm.get("requester_email") or "").strip().lower()
            if email:
                by_requester.setdefault(email, []).append(vm)

        for email, vm_list in by_requester.items():
            try:
                _send_email(
                    s["mail_username"], s["mail_password"],
                    [email],
                    f"[VM Alert] {len(vm_list)} VM(s) expiring soon — action required",
                    _html_table(vm_list, today),
                )
                log.info("Sent alert to %s for %d VM(s).", email, len(vm_list))
            except Exception as exc:
                log.error("Failed to send alert to %s: %s", email, exc)

        # Send admin digest (all expiring VMs)
        if admin:
            try:
                _send_email(
                    s["mail_username"], s["mail_password"],
                    [admin],
                    f"[VM Alert] {len(vms)} VM(s) expiring within {alert_days} day(s)",
                    _html_table(vms, today),
                )
                log.info("Sent admin digest to %s.", admin)
            except Exception as exc:
                log.error("Failed to send admin digest: %s", exc)


def send_welcome_email(invited_email, role, signin_url):
    """Send a welcome / access-granted email to a newly invited user."""
    from app.models.settings import get_settings
    s = get_settings()
    if not s.get("mail_username") or not s.get("mail_password"):
        log.warning("Email not configured — skipping welcome email to %s.", invited_email)
        return

    role_label = {"admin": "Admin", "editor": "Editor", "viewer": "Viewer"}.get(role, role.title())
    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#222;font-size:14px;margin:24px">
<p>Hello,</p>
<p>You have been granted access to <strong>VUNet VM Manager</strong> with the role of
<strong>{role_label}</strong>.</p>
<p style="margin:24px 0">
  <a href="{signin_url}"
     style="background:#1a3a5c;color:#fff;padding:12px 28px;border-radius:6px;
            text-decoration:none;font-weight:bold;font-size:15px">
    Sign in with Google
  </a>
</p>
<p style="color:#555;font-size:13px">
  Click the button above to sign in using your Google account (<strong>{invited_email}</strong>).
  No password is needed — Google handles your identity.
</p>
<p style="color:#888;font-size:11px;margin-top:24px">— VUNet VM Manager</p>
</body></html>"""

    try:
        _send_email(
            s["mail_username"], s["mail_password"],
            [invited_email],
            "You've been given access to VUNet VM Manager",
            html,
        )
        log.info("Sent welcome email to %s.", invited_email)
    except Exception as exc:
        log.error("Failed to send welcome email to %s: %s", invited_email, exc)


def init_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=send_expiry_alerts,
        args=[app],
        trigger="cron",
        hour=9,
        minute=0,
        id="vm_expiry_alerts",
        replace_existing=True,
    )
    scheduler.start()
    log.info("VM expiry alert scheduler started — runs daily at 09:00 UTC.")
    return scheduler
