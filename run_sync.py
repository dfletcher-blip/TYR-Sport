#!/usr/bin/env python3
# ============================================================
# run_sync.py — Auto-Sync Last Activity Dates
# ============================================================
# Run this on a schedule to keep tyr_lastactivitydate current
# on all contacts, leads, and accounts.
#
# Schedule it with Windows Task Scheduler:
#   schtasks /create /tn "TYR Sync Activity Dates" \
#     /tr "python C:\path\to\TYR-Sport\run_sync.py" \
#     /sc hourly /mo 1
# ============================================================

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from tools.activity_date import sync_last_activity_dates
from tools.contacts import sync_contact_owners_from_accounts

LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "sync_activity_dates.log")


def log(msg: str):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    log("Starting Last Activity Date sync...")

    for entity in ("contact", "lead", "account"):
        log(f"Syncing {entity}s...")
        result = sync_last_activity_dates(entity, limit=500)
        log(
            f"  {entity}: {result.get('updated', 0)} updated, "
            f"{result.get('skipped_no_activity', 0)} skipped, "
            f"{result.get('errors', 0)} errors"
        )
        if result.get("error"):
            log(f"  FATAL: {result['error']}")
        for err in (result.get("error_details") or [])[:5]:
            log(f"  ERROR: {err.get('name', '')} — {err.get('error', '')}")

    log("Syncing contact owners from accounts...")
    result = sync_contact_owners_from_accounts()
    log(
        f"  contact owners: {result.get('updated', 0)} updated, "
        f"{result.get('errors', 0)} errors"
    )
    if result.get("error"):
        log(f"  FATAL: {result['error']}")
    for err in (result.get("error_details") or [])[:5]:
        log(f"  ERROR: {err.get('name', '')} — {err.get('error', '')}")

    log("Sync complete.")
