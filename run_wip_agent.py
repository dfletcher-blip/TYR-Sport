#!/usr/bin/env python3
# ============================================================
# run_wip_agent.py — WIP Receive Report Agent — Entry Point
# ============================================================
#
# USAGE:
#
#   Check for changes now (one-shot):
#     python run_wip_agent.py
#
#   Check now and show email preview (no send):
#     python run_wip_agent.py --dry-run
#
#   Force a notification even if nothing changed:
#     python run_wip_agent.py --force
#
#   Run on a schedule (keeps process running):
#     python run_wip_agent.py --schedule            # daily at 8 AM (default)
#     python run_wip_agent.py --schedule --every 4h # every 4 hours
#     python run_wip_agent.py --schedule --every 30m # every 30 minutes
#
#   Show a demo notification with sample change data:
#     python run_wip_agent.py --demo
#
# REQUIRED .env VARIABLES:
#   ANTHROPIC_API_KEY   — Claude API key
#   ACS_MOCK_DATA=true  — Use mock data until ACS credentials are set up
#
# OPTIONAL .env VARIABLES (for live operation):
#   ACS_BASE_URL        — ACS API base URL
#   ACS_API_KEY         — ACS API key
#   WIP_NOTIFY_EMAILS   — Comma-separated recipient addresses
#   WIP_FROM_EMAIL      — Sender address
#   SMTP_HOST           — SMTP server (e.g. smtp.office365.com)
#   SMTP_PORT           — SMTP port (default: 587)
#   SMTP_USERNAME       — SMTP login
#   SMTP_PASSWORD       — SMTP password or app password
#
# See SETUP_GUIDE.md for step-by-step setup instructions.
# ============================================================

import argparse
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


BANNER = """
╔══════════════════════════════════════════════════════════╗
║        TYR Sport — WIP Receive Report Agent              ║
║                  Powered by Claude                       ║
╚══════════════════════════════════════════════════════════╝"""


def check_setup() -> bool:
    """Verify minimum required configuration is present."""
    missing = []
    if not os.getenv("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")

    acs_url = os.getenv("ACS_BASE_URL", "")
    acs_mock = os.getenv("ACS_MOCK_DATA", "").lower() in ("true", "1", "yes")
    if not acs_url and not acs_mock:
        missing.append("ACS_BASE_URL (or set ACS_MOCK_DATA=true to use mock data)")

    if missing:
        print("\n  SETUP REQUIRED")
        print("  " + "-" * 48)
        for item in missing:
            print(f"  Missing: {item}")
        print("\n  Add the above to your .env file.")
        print("  For testing without ACS access: add ACS_MOCK_DATA=true\n")
        return False
    return True


def _parse_interval(value: str) -> int:
    """Parse a schedule interval like '4h', '30m', '1d' into seconds."""
    value = value.strip().lower()
    if value.endswith("h"):
        return int(value[:-1]) * 3600
    if value.endswith("m"):
        return int(value[:-1]) * 60
    if value.endswith("d"):
        return int(value[:-1]) * 86400
    if value.endswith("s"):
        return int(value[:-1])
    raise ValueError(f"Cannot parse interval '{value}'. Use formats like: 4h, 30m, 1d, 90s")


def run_once(dry_run: bool = False, force: bool = False) -> None:
    """Execute one WIP monitoring cycle."""
    from wip_agent import run_wip_agent
    print(f"\n  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running WIP check...")
    result = run_wip_agent(dry_run=dry_run, force_notify=force)
    print(f"\n{'═' * 60}")
    print(result)
    print(f"{'═' * 60}\n")


def run_scheduled(interval_seconds: int, dry_run: bool = False) -> None:
    """Run WIP checks on a recurring interval until interrupted."""
    hours = interval_seconds // 3600
    minutes = (interval_seconds % 3600) // 60
    if hours > 0 and minutes > 0:
        interval_label = f"{hours}h {minutes}m"
    elif hours > 0:
        interval_label = f"{hours}h"
    else:
        interval_label = f"{minutes}m"

    print(f"\n  Scheduled mode — checking every {interval_label}")
    print("  Press Ctrl+C to stop\n")

    # Run immediately on start
    run_once(dry_run=dry_run)
    next_run = time.time() + interval_seconds

    while True:
        try:
            remaining = next_run - time.time()
            if remaining <= 0:
                run_once(dry_run=dry_run)
                next_run = time.time() + interval_seconds
            else:
                # Show countdown every 60 seconds
                mins_left = int(remaining // 60)
                next_str = datetime.fromtimestamp(next_run).strftime("%H:%M:%S")
                print(f"  Next check at {next_str} ({mins_left}m remaining)", end="\r")
                time.sleep(min(60, remaining))
        except KeyboardInterrupt:
            print("\n\n  Stopped. Goodbye!")
            break


def run_demo() -> None:
    """
    Show a demo notification using synthetic before/after data so you can see
    what the email alert looks like without waiting for real ACS changes.
    """
    from datetime import timedelta
    from tools.wip_report import detect_wip_changes, format_change_summary
    from tools.wip_notifications import send_wip_notification

    today = datetime.now()

    # Simulate a previous snapshot
    previous = [
        {
            "po_number": "PO-2025-0042", "line_number": 1, "sku": "SWIM-M-BLU-MD",
            "description": "Men's Swim Jammer - Blue - Medium",
            "quantity_ordered": 200, "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=15)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None, "status": "Open",
            "vendor": "Pacific Sportswear", "buyer": "Sarah Johnson", "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0055", "line_number": 1, "sku": "SUIT-W-RED-SM",
            "description": "Women's Competition Suit - Red - Small",
            "quantity_ordered": 100, "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None, "status": "Open",
            "vendor": "Elite Aquatics Mfg", "buyer": "Mark Torres", "category": "Swimwear",
        },
        {
            "po_number": "PO-2025-0061", "line_number": 1, "sku": "GOGGLE-ELITE-CLR",
            "description": "Elite Racing Goggles - Clear Lens",
            "quantity_ordered": 500, "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None, "status": "Open",
            "vendor": "TechVision Eyewear", "buyer": "Sarah Johnson", "category": "Accessories",
        },
        {
            "po_number": "PO-2025-0063", "line_number": 1, "sku": "CAP-SILICONE-BLK",
            "description": "Silicone Swim Cap - Black",
            "quantity_ordered": 1000, "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=20)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None, "status": "Open",
            "vendor": "Aqua Gear Co.", "buyer": "Mark Torres", "category": "Accessories",
        },
    ]

    # Simulate the current report with various changes
    current = [
        # EDD pushed later by 7 days
        {**previous[0], "expected_delivery_date": (today + timedelta(days=22)).strftime("%Y-%m-%d")},
        # Partially received
        {**previous[1], "quantity_received": 45, "status": "Partially Received"},
        # Fully arrived
        {
            **previous[2],
            "quantity_received": 500,
            "actual_receipt_date": today.strftime("%Y-%m-%d"),
            "status": "Received",
        },
        # Cancelled
        {**previous[3], "status": "Cancelled"},
        # New PO line
        {
            "po_number": "PO-2025-0075", "line_number": 1, "sku": "BRIEF-W-BLK-LG",
            "description": "Women's Brief - Black - Large",
            "quantity_ordered": 180, "quantity_received": 0,
            "expected_delivery_date": (today + timedelta(days=25)).strftime("%Y-%m-%d"),
            "actual_receipt_date": None, "status": "Open",
            "vendor": "Pacific Sportswear", "buyer": "Sarah Johnson", "category": "Swimwear",
        },
    ]

    prev_snapshot = {
        f"{i['po_number']}::{i['line_number']}::{i['sku']}": i for i in previous
    }
    changes = detect_wip_changes(current, prev_snapshot)

    print("\n" + "=" * 60)
    print("DEMO — Simulated WIP Report Changes")
    print("=" * 60)
    print(format_change_summary(changes))
    print("=" * 60)
    print("\nPreviewing notification email (dry run)...\n")

    demo_summary = (
        "TechVision goggles (PO-2025-0061) arrived in full — 500 units received. "
        "The Pacific Sportswear jammer delivery slipped 7 days to a later date; follow up "
        "if this affects any planned promotional inventory. "
        "PO-2025-0063 (swim caps) was cancelled — confirm whether a replacement order is needed."
    )

    send_wip_notification(changes, ai_summary=demo_summary, dry_run=True)


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(
        description="TYR Sport WIP Receive Report Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect changes and preview the email without sending it",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send a notification even if no changes are detected",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on a recurring schedule (keeps the process alive)",
    )
    parser.add_argument(
        "--every",
        default="24h",
        metavar="INTERVAL",
        help="Schedule interval: e.g. 4h, 30m, 1d (default: 24h). Only used with --schedule.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Show a demo notification with synthetic change data (no ACS connection needed)",
    )
    args = parser.parse_args()

    # Demo mode needs no setup
    if args.demo:
        run_demo()
        return

    if not check_setup():
        sys.exit(1)

    if args.schedule:
        try:
            interval = _parse_interval(args.every)
        except ValueError as e:
            print(f"\n  Error: {e}")
            sys.exit(1)
        run_scheduled(interval_seconds=interval, dry_run=args.dry_run)
    else:
        run_once(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
