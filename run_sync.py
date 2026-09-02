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
from tools.leads import sync_lead_statuses

LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "sync_activity_dates.log")


def log(msg: str):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    log("Starting Last Activity Date sync...")

    for entity in ("contact", "lead", "account"):
        log(f"Syncing {entity}s...")
        result = sync_last_activity_dates(entity, limit=500)
        log(
            f"  {entity}: {result.get('updated', 0)} updated "
            f"({result.get('fallback_matched', 0)} via email fallback), "
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
        f"  contact owners: {result.get('updated', result.get('contacts_to_update', 0))} updated, "
        f"{result.get('errors', 0)} errors "
        f"(checked {result.get('contacts_checked', 0)} contacts / {result.get('accounts_checked', 0)} accounts; "
        f"null owners — contacts: {result.get('null_contact_owners', '?')}, accounts: {result.get('null_account_owners', '?')})"
    )
    if result.get("message"):
        log(f"  {result['message']}")
    for s in (result.get("sample_comparisons") or []):
        log(f"  SAMPLE: {s['name']} — contact_owner={s['contact_owner']} account_owner={s['account_owner']} account_salesrep={s.get('account_salesrep')} using_salesrep={s.get('using_salesrep_field')} match={s['match']}")
    if result.get("error"):
        log(f"  FATAL: {result['error']}")
    for err in (result.get("error_details") or [])[:5]:
        log(f"  ERROR: {err.get('name', '')} — {err.get('error', '')}")

    log("Syncing lead statuses (New -> Contacting)...")
    result = sync_lead_statuses()
    log(
        f"  lead status: {result.get('updated', 0)} advanced to Contacting, "
        f"{result.get('errors', 0)} errors "
        f"(checked {result.get('new_leads_checked', 0)} New leads, "
        f"{result.get('leads_with_activity', result.get('updated', 0))} had activity)"
    )
    if result.get("error"):
        log(f"  FATAL: {result['error']}")
        if result.get("available_options"):
            for opt in result["available_options"]:
                log(f"    statuscode option: {opt['value']} = {opt['label']}")
    for err in (result.get("error_details") or [])[:5]:
        log(f"  ERROR: {err.get('name', '')} — {err.get('error', '')}")

    log("Sync complete.")
