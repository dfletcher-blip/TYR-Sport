# ============================================================
# sync_contact_tyr_type.py — Standalone TYR Type sync script
# Run directly: python sync_contact_tyr_type.py
# ============================================================
# Copies the tyr_tyrtype field from each Account to all
# Contacts linked to that Account.
#
# Run with --dry-run first to preview what will change.
# ============================================================

import sys
from dotenv import load_dotenv
load_dotenv()

from tools.sync import sync_contact_field_from_account, get_contacts_with_mismatched_account_field

def run():
    dry_run = "--dry-run" in sys.argv or "--preview" in sys.argv

    print("\n=== TYR Sport — Sync TYR Type: Account → Contact ===\n")

    if dry_run:
        print("** DRY RUN MODE — no changes will be made **\n")

    print("Checking for mismatches first...\n")
    audit = get_contacts_with_mismatched_account_field("tyr_tyrtype", "tyr_tyrtype", limit=5)
    print(f"Contacts out of sync: {audit['total_mismatches_found']}")
    if audit["mismatches"]:
        print("Examples:")
        for m in audit["mismatches"][:5]:
            print(f"  • {m['contact_name']} ({m['account_name']}) — contact has {m['contact_value']}, account has {m['account_value']}")

    print(f"\n{'Previewing' if dry_run else 'Running'} sync...\n")
    result = sync_contact_field_from_account("tyr_tyrtype", "tyr_tyrtype", dry_run=dry_run)

    print(f"Contacts checked: {result['total_contacts_checked']}")
    print(f"Contacts {'that would be' if dry_run else ''} updated: {result['contacts_updated']}")
    print(f"Contacts already correct (skipped): {result['contacts_skipped']}")

    if result.get("preview_examples"):
        print("\nExamples of changes:")
        for ex in result["preview_examples"]:
            print(f"  • {ex['contact']} ({ex['account']}) — {ex['from']} → {ex['to']}")

    if result.get("error_details"):
        print(f"\nErrors ({result['errors']}):")
        for e in result["error_details"]:
            print(f"  ✗ {e}")

    if dry_run:
        print("\nRun without --dry-run to apply these changes:")
        print("  python sync_contact_tyr_type.py")
    else:
        print("\nDone. TYR Type is now synced from Account to Contact.")

if __name__ == "__main__":
    run()
