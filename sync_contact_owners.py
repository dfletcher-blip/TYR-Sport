"""
Set each contact's owner to match its parent account's owner.
Contacts with no parent account are skipped.
"""
import os
from dotenv import load_dotenv
load_dotenv()
from tools.sync import sync_contact_owner_from_account

print("Syncing contact owners from account owners...")
result = sync_contact_owner_from_account(dry_run=False)
print(f"  Checked:  {result['total_contacts_checked']}")
print(f"  Updated:  {result['contacts_updated']}")
print(f"  Skipped:  {result['contacts_skipped']}")
print(f"  Errors:   {result['errors']}")
if result["error_details"]:
    print("  Error details:")
    for e in result["error_details"]:
        print(f"    {e}")
print("\nDone.")
