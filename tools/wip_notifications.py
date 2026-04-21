# ============================================================
# tools/wip_notifications.py — WIP Alert Email Sender
# ============================================================
# Sends email notifications when WIP receive report changes are
# detected (arrivals, date changes, cancellations).
#
# CONFIGURATION (.env variables):
#   WIP_NOTIFY_EMAILS  — Comma-separated list of recipient addresses
#                        e.g. "buyer@tyr.com,ops@tyr.com,mgr@tyr.com"
#   WIP_FROM_EMAIL     — Sender address (e.g. "wip-agent@tyr.com")
#   SMTP_HOST          — SMTP server hostname (e.g. smtp.office365.com)
#   SMTP_PORT          — SMTP port (default: 587 for STARTTLS, 465 for SSL)
#   SMTP_USERNAME      — SMTP login username (often same as WIP_FROM_EMAIL)
#   SMTP_PASSWORD      — SMTP login password or app password
#   SMTP_USE_SSL       — Set "true" to use SSL on connect (port 465); otherwise STARTTLS
# ============================================================

import os
import smtplib
import socket
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()


# ── Recipient config ───────────────────────────────────────────────────────────

def get_notify_recipients() -> list[str]:
    """Return the list of email addresses to notify, from WIP_NOTIFY_EMAILS env var."""
    raw = os.getenv("WIP_NOTIFY_EMAILS", "")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


# ── Email content builders ─────────────────────────────────────────────────────

def _build_subject(changes: dict) -> str:
    total = changes["total_changes"]
    parts = []
    if changes["arrivals"]:
        n = len(changes["arrivals"])
        parts.append(f"{n} arrival{'s' if n > 1 else ''}")
    if changes["partial_arrivals"]:
        n = len(changes["partial_arrivals"])
        parts.append(f"{n} partial arrival{'s' if n > 1 else ''}")
    if changes["date_changes"]:
        n = len(changes["date_changes"])
        parts.append(f"{n} date change{'s' if n > 1 else ''}")
    if changes["cancellations"]:
        n = len(changes["cancellations"])
        parts.append(f"{n} cancellation{'s' if n > 1 else ''}")
    detail = ", ".join(parts) if parts else f"{total} change(s)"
    date_str = datetime.now().strftime("%b %d, %Y")
    return f"WIP Receive Report Alert — {detail} [{date_str}]"


def _fmt_date(date_str: str | None) -> str:
    if not date_str:
        return "—"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return date_str


def _build_html_body(changes: dict, ai_summary: str = "") -> str:
    sections = []

    def table_row(*cells, header=False):
        tag = "th" if header else "td"
        return "<tr>" + "".join(f"<{tag} style='padding:6px 12px;border:1px solid #ddd'>{c}</{tag}>" for c in cells) + "</tr>"

    def section(title: str, color: str, rows_html: str) -> str:
        return f"""
        <h3 style='color:{color};margin-top:24px'>{title}</h3>
        <table style='border-collapse:collapse;width:100%;font-size:13px'>
          {rows_html}
        </table>"""

    if changes["arrivals"]:
        rows = table_row("PO #", "Line", "SKU", "Description", "Vendor", "Qty Received", "Receipt Date", header=True)
        for item in changes["arrivals"]:
            rows += table_row(
                item["po_number"], item["line_number"], item["sku"],
                item["description"], item["vendor"],
                f"<b>{int(item['quantity_received'])}</b> / {int(item['quantity_ordered'])}",
                _fmt_date(item.get("actual_receipt_date")),
            )
        sections.append(section(f"✅ Arrivals ({len(changes['arrivals'])})", "#2e7d32", rows))

    if changes["partial_arrivals"]:
        rows = table_row("PO #", "Line", "SKU", "Description", "Vendor", "Qty Received", "% Complete", header=True)
        for item in changes["partial_arrivals"]:
            rows += table_row(
                item["po_number"], item["line_number"], item["sku"],
                item["description"], item["vendor"],
                f"{int(item['quantity_received'])} / {int(item['quantity_ordered'])} (+{int(item['qty_increase'])})",
                f"{item['pct_received']}%",
            )
        sections.append(section(f"📦 Partial Arrivals ({len(changes['partial_arrivals'])})", "#1565c0", rows))

    if changes["date_changes"]:
        rows = table_row("PO #", "Line", "SKU", "Description", "Vendor", "Previous EDD", "New EDD", "Shift", header=True)
        for item in changes["date_changes"]:
            shift = item["days_shifted"]
            shift_color = "#c62828" if shift > 0 else "#2e7d32"
            shift_label = f"<span style='color:{shift_color}'>{'+' if shift > 0 else ''}{shift}d ({item['direction']})</span>"
            rows += table_row(
                item["po_number"], item["line_number"], item["sku"],
                item["description"], item["vendor"],
                _fmt_date(item["previous_date"]),
                f"<b>{_fmt_date(item['expected_delivery_date'])}</b>",
                shift_label,
            )
        sections.append(section(f"📅 Delivery Date Changes ({len(changes['date_changes'])})", "#e65100", rows))

    if changes["cancellations"]:
        rows = table_row("PO #", "Line", "SKU", "Description", "Vendor", "Previous Status", "New Status", header=True)
        for item in changes["cancellations"]:
            rows += table_row(
                item["po_number"], item["line_number"], item["sku"],
                item["description"], item["vendor"],
                item["previous_status"],
                f"<b style='color:#c62828'>{item['status']}</b>",
            )
        sections.append(section(f"❌ Cancellations / Holds ({len(changes['cancellations'])})", "#b71c1c", rows))

    if changes["new_items"]:
        rows = table_row("PO #", "Line", "SKU", "Description", "Vendor", "Qty Ordered", "Expected EDD", header=True)
        for item in changes["new_items"]:
            rows += table_row(
                item["po_number"], item["line_number"], item["sku"],
                item["description"], item["vendor"],
                int(item["quantity_ordered"]),
                _fmt_date(item.get("expected_delivery_date")),
            )
        sections.append(section(f"🆕 New PO Lines ({len(changes['new_items'])})", "#4a148c", rows))

    ai_block = ""
    if ai_summary:
        ai_block = f"""
        <div style='background:#f0f4ff;border-left:4px solid #1565c0;padding:12px 16px;margin:24px 0;border-radius:4px'>
          <strong style='color:#1565c0'>AI Summary</strong>
          <p style='margin:8px 0 0;white-space:pre-wrap;font-size:13px'>{ai_summary}</p>
        </div>"""

    checked_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    return f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:960px;margin:auto;padding:24px'>
      <h2 style='color:#1a237e'>TYR Sport — WIP Receive Report Alert</h2>
      <p style='color:#666;font-size:12px'>Report checked: {checked_at}</p>
      {ai_block}
      {"".join(sections)}
      <hr style='margin-top:32px;border:none;border-top:1px solid #eee'/>
      <p style='color:#999;font-size:11px'>
        Sent by the TYR Sport WIP Monitoring Agent. Reply to this email to contact the operations team.
      </p>
    </body></html>"""


def _build_plain_body(changes: dict, ai_summary: str = "") -> str:
    lines = ["TYR Sport — WIP Receive Report Alert"]
    lines.append(f"Checked: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
    lines.append("=" * 60)

    if ai_summary:
        lines.append("\nAI SUMMARY")
        lines.append("-" * 40)
        lines.append(ai_summary)
        lines.append("")

    for item in changes["arrivals"]:
        lines.append(f"[ARRIVED] {item['po_number']} L{item['line_number']} — {item['sku']} — "
                     f"{int(item['quantity_received'])} units received from {item['vendor']}")

    for item in changes["partial_arrivals"]:
        lines.append(f"[PARTIAL] {item['po_number']} L{item['line_number']} — {item['sku']} — "
                     f"+{int(item['qty_increase'])} units ({item['pct_received']}% complete)")

    for item in changes["date_changes"]:
        lines.append(f"[EDD CHANGE] {item['po_number']} L{item['line_number']} — {item['sku']} — "
                     f"EDD: {item['previous_date']} → {item['expected_delivery_date']} "
                     f"({'+' if item['days_shifted'] > 0 else ''}{item['days_shifted']}d)")

    for item in changes["cancellations"]:
        lines.append(f"[CANCELLED] {item['po_number']} L{item['line_number']} — {item['sku']} — "
                     f"Status: {item['previous_status']} → {item['status']}")

    return "\n".join(lines)


# ── SMTP sender ────────────────────────────────────────────────────────────────

def send_wip_notification(changes: dict, ai_summary: str = "", dry_run: bool = False) -> dict:
    """
    Send a WIP alert email to all addresses in WIP_NOTIFY_EMAILS.

    changes    — the dict returned by detect_wip_changes()
    ai_summary — optional plain-text analysis from Claude to embed in the email
    dry_run    — if True, print the email content but do not send

    Returns a result dict with 'success', 'recipients', and 'message' keys.
    """
    recipients = get_notify_recipients()
    subject = _build_subject(changes)
    html_body = _build_html_body(changes, ai_summary)
    plain_body = _build_plain_body(changes, ai_summary)
    from_addr = os.getenv("WIP_FROM_EMAIL", os.getenv("SMTP_USERNAME", "wip-agent@tyr.com"))

    if not recipients and not dry_run:
        return {
            "success": False,
            "message": "WIP_NOTIFY_EMAILS is not configured. Add recipient addresses to your .env file.",
        }

    if dry_run:
        to_display = ", ".join(recipients) if recipients else "(WIP_NOTIFY_EMAILS not configured)"
        print(f"\n[DRY RUN] Would send email:")
        print(f"  From:    {from_addr}")
        print(f"  To:      {to_display}")
        print(f"  Subject: {subject}")
        print(f"\n--- Plain text preview ---")
        print(plain_body)
        return {"success": True, "dry_run": True, "recipients": recipients, "subject": subject}

    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    use_ssl = os.getenv("SMTP_USE_SSL", "").lower() in ("true", "1", "yes")

    if not smtp_host:
        return {
            "success": False,
            "message": "SMTP_HOST is not configured. Add SMTP settings to your .env file.",
        }

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()

        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)

        server.sendmail(from_addr, recipients, msg.as_string())
        server.quit()

        return {
            "success": True,
            "recipients": recipients,
            "recipient_count": len(recipients),
            "subject": subject,
            "message": f"Alert sent to {len(recipients)} recipient(s)",
        }

    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "message": "SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD in .env.",
        }
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP error: {e}"}
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return {"success": False, "message": f"Could not connect to SMTP server {smtp_host}:{smtp_port} — {e}"}
