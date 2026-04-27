#!/usr/bin/env python3
# ============================================================
# run_crm_monitor.py — CRM Auto-Enforcement Monitor
# ============================================================
# Runs on a schedule and enforces CRM data rules that Dynamics 365
# does not handle automatically without a custom plugin or workflow.
#
# CURRENT RULES ENFORCED:
#   1. Opportunity Stage Sync
#      When an opportunity is marked Closed Won or Closed Lost,
#      update the TYR Stage field to match.
#      Applies to ALL opportunities — existing and new.
#
# USAGE:
#
#   Fix everything right now (one-shot):
#     python run_crm_monitor.py
#
#   Preview what would be fixed without changing anything:
#     python run_crm_monitor.py --dry-run
#
#   Run continuously on a schedule (keeps the process alive):
#     python run_crm_monitor.py --schedule               # every 15 min (default)
#     python run_crm_monitor.py --schedule --every 5m    # every 5 minutes
#     python run_crm_monitor.py --schedule --every 1h    # every hour
#
# PRODUCTION SETUP — set it and forget it:
#
#   Linux / Mac (cron) — edit with: crontab -e
#     */15 * * * * cd /path/to/TYR-Sport && python run_crm_monitor.py >> logs/monitor.log 2>&1
#
#   Windows (Task Scheduler):
#     Program:   python
#     Arguments: C:\path\to\TYR-Sport\run_crm_monitor.py
#     Start in:  C:\path\to\TYR-Sport
#     Trigger:   Repeat every 15 minutes, indefinitely
#
#   Docker / always-on server:
#     python run_crm_monitor.py --schedule --every 5m
#
# ADDING NEW RULES:
#   1. Write the detection + fix logic in tools/
#   2. Call it inside run_all_checks() below
#   3. The monitor will enforce it automatically on the next cycle
#
# REQUIRED .env VARIABLES:
#   ANTHROPIC_API_KEY, DYNAMICS_URL, AZURE_TENANT_ID,
#   AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
# ============================================================

import argparse
import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


BANNER = """
╔══════════════════════════════════════════════════════════╗
║       TYR Sport — CRM Auto-Enforcement Monitor           ║
╠══════════════════════════════════════════════════════════╣
║  Enforces CRM data rules on a schedule.                  ║
║  Run once: python run_crm_monitor.py                     ║
║  Scheduled: python run_crm_monitor.py --schedule         ║
╚══════════════════════════════════════════════════════════╝"""


# ── Setup check ────────────────────────────────────────────────────────────────

def check_setup() -> bool:
    required = {
        "ANTHROPIC_API_KEY": "",
        "DYNAMICS_URL": "",
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_ID": "",
        "AZURE_CLIENT_SECRET": "",
    }
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print("\n  SETUP REQUIRED")
        print("  " + "-" * 48)
        for k in missing:
            print(f"  Missing: {k}")
        print("\n  Add the above to your .env file.\n")
        return False
    return True


# ── Rule: Opportunity Stage Sync ───────────────────────────────────────────────

def enforce_opportunity_stage_sync(stage_field: str = "tyr_stage", dry_run: bool = False) -> dict:
    """
    Rule: Every Won or Lost opportunity must have its TYR Stage field set to
    'Closed Won' or 'Closed Lost' respectively.

    Finds all mismatches and fixes them in a single pass. Safe to run repeatedly —
    already-correct records are skipped without any writes.
    """
    from tools.opportunity_stage_sync import bulk_sync_closed_stages

    result = bulk_sync_closed_stages(stage_field=stage_field, dry_run=dry_run)

    fixed   = result.get("fixed", 0)
    failed  = result.get("failed", 0)
    preview = result.get("would_fix", 0)

    if dry_run:
        print(f"  [Stage Sync] DRY RUN — would fix {preview} opportunity/opportunities")
        for r in result.get("records", []):
            print(f"    → {r['name']} ({r['account']}) : '{r['current_stage']}' → '{r['will_become']}'")
        if preview == 0:
            print("  [Stage Sync] All closed opportunities already have the correct stage")
        return result

    if fixed > 0:
        print(f"  [Stage Sync] Fixed {fixed} opportunity/opportunities")
        for r in result.get("fixed_records", []):
            print(f"    ✓ {r['name']} → {r['new_stage']}")
    if failed > 0:
        print(f"  [Stage Sync] WARNING: {failed} could not be updated — check logs")
        for r in result.get("failed_records", []):
            print(f"    ✗ {r['name']}: {r['reason']}")
    if fixed == 0 and failed == 0:
        print("  [Stage Sync] All closed opportunities have the correct stage — nothing to fix")

    return result


# ── Main enforcement loop ──────────────────────────────────────────────────────

def run_all_checks(dry_run: bool = False) -> dict:
    """
    Run every enforcement rule in sequence.
    Add new rules here as needed.
    """
    run_at = datetime.now()
    print(f"\n[{run_at.strftime('%Y-%m-%d %H:%M:%S')}] Running CRM enforcement checks...")
    print("─" * 54)

    results = {}

    # ── Rule 1: Opportunity Stage Sync ────────────────────────
    try:
        results["opportunity_stage_sync"] = enforce_opportunity_stage_sync(dry_run=dry_run)
    except Exception as e:
        print(f"  [Stage Sync] ERROR: {e}")
        results["opportunity_stage_sync"] = {"error": str(e)}

    # ── Add future rules here ──────────────────────────────────
    # Example:
    #   try:
    #       results["some_other_rule"] = enforce_some_other_rule(dry_run=dry_run)
    #   except Exception as e:
    #       results["some_other_rule"] = {"error": str(e)}

    print("─" * 54)

    # Log to file
    _log_run(run_at, results, dry_run)

    return results


# ── Logging ────────────────────────────────────────────────────────────────────

def _log_run(run_at: datetime, results: dict, dry_run: bool) -> None:
    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", f"monitor_{run_at.strftime('%Y%m%d_%H%M%S')}.json")
    with open(log_path, "w") as f:
        json.dump(
            {"run_at": run_at.isoformat(), "dry_run": dry_run, "results": results},
            f,
            indent=2,
            default=str,
        )


# ── Interval parser ────────────────────────────────────────────────────────────

def _parse_interval(value: str) -> int:
    value = value.strip().lower()
    if value.endswith("h"):
        return int(value[:-1]) * 3600
    if value.endswith("m"):
        return int(value[:-1]) * 60
    if value.endswith("s"):
        return int(value[:-1])
    raise ValueError(f"Cannot parse '{value}'. Use formats like: 5m, 15m, 1h")


# ── Scheduled runner ───────────────────────────────────────────────────────────

def run_scheduled(interval_seconds: int, dry_run: bool = False) -> None:
    hours   = interval_seconds // 3600
    minutes = (interval_seconds % 3600) // 60
    label   = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    print(f"\n  Scheduled mode — enforcing rules every {label}")
    if dry_run:
        print("  DRY RUN — previewing only, no changes will be written")
    print("  Press Ctrl+C to stop\n")

    # Run immediately on start so the first check doesn't wait
    run_all_checks(dry_run=dry_run)
    next_run = time.time() + interval_seconds

    while True:
        try:
            remaining = next_run - time.time()
            if remaining <= 0:
                run_all_checks(dry_run=dry_run)
                next_run = time.time() + interval_seconds
            else:
                next_str = datetime.fromtimestamp(next_run).strftime("%H:%M:%S")
                print(f"  Sleeping — next check at {next_str}  ", end="\r")
                time.sleep(min(30, remaining))
        except KeyboardInterrupt:
            print("\n\n  Monitor stopped. Goodbye!")
            break


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print(BANNER)

    parser = argparse.ArgumentParser(
        description="TYR Sport CRM Auto-Enforcement Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be fixed without making any changes",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run continuously on a recurring schedule (keeps the process alive)",
    )
    parser.add_argument(
        "--every",
        default="15m",
        metavar="INTERVAL",
        help="How often to run checks in scheduled mode. Examples: 5m, 15m, 1h (default: 15m)",
    )
    args = parser.parse_args()

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
        run_all_checks(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
