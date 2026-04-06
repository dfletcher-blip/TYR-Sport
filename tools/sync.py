# ============================================================
# tools/sync.py — Cross-Entity Field Sync Tools
# ============================================================
# These tools sync field values from parent records (Accounts)
# down to child records (Contacts, Leads, Opportunities).
#
# Use case example:
#   Account has tyr_tyrtype = "Crossfit"
#   → All linked Contacts should also have tyr_tyrtype = "Crossfit"
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch


def sync_contact_field_from_account(
    account_field: str = "tyr_tyrtype",
    contact_field: str = "tyr_tyrtype",
    dry_run: bool = False,
) -> dict:
    """
    Copy a field value from each Account to all Contacts linked to that Account.

    account_field: field name on the Account entity to read from (default: tyr_tyrtype)
    contact_field: field name on the Contact entity to write to (default: tyr_tyrtype)
    dry_run:       if True, show what WOULD be updated without actually updating

    Returns a summary of how many contacts were updated and any errors.
    """
    # Step 1: Get all accounts that have a value in the source field
    params = {
        "$select": f"accountid,name,{account_field}",
        "$filter": f"{account_field} ne null",
        "$top": 5000,
        "$orderby": "name asc",
    }

    accounts = crm_get("accounts", params).get("value", [])

    if not accounts:
        return {
            "message": f"No accounts found with '{account_field}' set.",
            "accounts_checked": 0,
            "contacts_updated": 0,
        }

    updated = 0
    skipped = 0
    errors = []
    account_summaries = []

    for account in accounts:
        account_id   = account.get("accountid")
        account_name = account.get("name", "Unnamed")
        field_value  = account.get(account_field)

        if field_value is None:
            continue

        # Step 2: Get all contacts linked to this account
        contact_params = {
            "$select": f"contactid,fullname,{contact_field}",
            "$filter": f"_parentcustomerid_value eq {account_id}",
            "$top": 1000,
        }

        try:
            contacts = crm_get("contacts", contact_params).get("value", [])
        except Exception as e:
            errors.append(f"Error fetching contacts for {account_name}: {e}")
            continue

        if not contacts:
            continue

        contacts_updated_this_account = 0
        for contact in contacts:
            contact_id    = contact.get("contactid")
            contact_name  = contact.get("fullname", "Unknown")
            current_value = contact.get(contact_field)

            if current_value == field_value:
                skipped += 1
                continue

            if not dry_run:
                try:
                    crm_patch("contacts", contact_id, {contact_field: field_value})
                    updated += 1
                    contacts_updated_this_account += 1
                except Exception as e:
                    errors.append(f"Error updating {contact_name}: {e}")
            else:
                updated += 1  # Count as "would update" in dry run
                contacts_updated_this_account += 1

        if contacts_updated_this_account > 0:
            account_summaries.append({
                "account": account_name,
                "value_set": field_value,
                "contacts_updated": contacts_updated_this_account,
            })

    return {
        "dry_run": dry_run,
        "accounts_with_field_set": len(accounts),
        "contacts_updated": updated,
        "contacts_already_correct": skipped,
        "errors": len(errors),
        "error_details": errors[:10],
        "accounts_affected": account_summaries[:20],
        "message": (
            f"{'DRY RUN — no changes made. ' if dry_run else ''}"
            f"Updated {updated} contacts across {len(account_summaries)} accounts."
        ),
    }


def get_contacts_with_mismatched_account_field(
    account_field: str = "tyr_tyrtype",
    contact_field: str = "tyr_tyrtype",
    limit: int = 200,
) -> dict:
    """
    Find contacts where the field value does NOT match their parent account's value.
    Useful for auditing before or after a sync.

    account_field: field name on Account (default: tyr_tyrtype)
    contact_field: field name on Contact (default: tyr_tyrtype)
    limit:         max number of mismatches to return (default 200)

    Returns a list of contacts where the values are out of sync.
    """
    # Get accounts with the field set
    accounts = crm_get("accounts", {
        "$select": f"accountid,name,{account_field}",
        "$filter": f"{account_field} ne null",
        "$top": 5000,
    }).get("value", [])

    account_map = {a["accountid"]: a for a in accounts}

    mismatches = []

    for account in accounts:
        account_id   = account.get("accountid")
        account_name = account.get("name", "Unnamed")
        account_val  = account.get(account_field)

        contacts = crm_get("contacts", {
            "$select": f"contactid,fullname,emailaddress1,{contact_field}",
            "$filter": f"_parentcustomerid_value eq {account_id}",
            "$top": 1000,
        }).get("value", [])

        for contact in contacts:
            contact_val = contact.get(contact_field)
            if contact_val != account_val:
                mismatches.append({
                    "contact_name":  contact.get("fullname", "Unknown"),
                    "contact_id":    contact.get("contactid"),
                    "email":         contact.get("emailaddress1", ""),
                    "account_name":  account_name,
                    "account_value": account_val,
                    "contact_value": contact_val,
                })

        if len(mismatches) >= limit:
            break

    return {
        "total_mismatches_found": len(mismatches),
        "account_field": account_field,
        "contact_field": contact_field,
        "mismatches": mismatches[:limit],
        "message": (
            f"Found {len(mismatches)} contacts where {contact_field} "
            f"does not match their account's {account_field}."
        ),
    }


def sync_all_crossfit_contacts(dry_run: bool = False) -> dict:
    """
    Convenience function: sync tyr_tyrtype from Account to Contact for all accounts.
    Runs sync_contact_field_from_account with default tyr_tyrtype → tyr_tyrtype.

    dry_run: if True, preview changes without making them

    Returns full sync summary.
    """
    return sync_contact_field_from_account(
        account_field="tyr_tyrtype",
        contact_field="tyr_tyrtype",
        dry_run=dry_run,
    )
