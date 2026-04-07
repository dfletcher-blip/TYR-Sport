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
    Uses a single bulk query (expand) instead of one call per account.

    account_field: field name on the Account entity to read from (default: tyr_tyrtype)
    contact_field: field name on the Contact entity to write to (default: tyr_tyrtype)
    dry_run:       if True, show what WOULD be updated without actually updating
    """
    # Single query: get all contacts + their parent account's field value in one call
    params = {
        "$select": f"contactid,fullname,{contact_field},_parentcustomerid_value",
        "$expand": f"parentcustomerid_account($select=accountid,name,{account_field})",
        "$filter": f"_parentcustomerid_value ne null",
        "$top": 5000,
    }

    contacts = crm_get("contacts", params).get("value", [])

    if not contacts:
        return {"message": "No contacts with a parent account found.", "contacts_updated": 0}

    updated = 0
    skipped = 0
    errors = []
    examples = []

    for contact in contacts:
        contact_id    = contact.get("contactid")
        contact_name  = contact.get("fullname", "Unknown")
        contact_val   = contact.get(contact_field)
        account_data  = contact.get("parentcustomerid_account") or {}
        account_val   = account_data.get(account_field)

        if account_val is None:
            skipped += 1
            continue

        # Handle multi-select: account may have comma-separated values (e.g. "935650000,935650019")
        # Contact field is single-select — take the LAST value (most specific, not Inactive)
        account_val_str = str(account_val)
        if "," in account_val_str:
            parts = [int(x.strip()) for x in account_val_str.split(",") if x.strip().isdigit()]
            account_val = parts[-1] if parts else account_val  # last = most specific

        if contact_val == account_val:
            skipped += 1
            continue

        if not dry_run:
            try:
                crm_patch("contacts", contact_id, {contact_field: account_val})
                updated += 1
                if updated % 100 == 0:
                    print(f"  ... {updated} contacts updated so far")
            except Exception as e:
                errors.append(f"{contact_name}: {e}")
        else:
            updated += 1
            if len(examples) < 10:
                examples.append({
                    "contact": contact_name,
                    "account": account_data.get("name", ""),
                    "from":    contact_val,
                    "to":      account_val,
                })

    return {
        "dry_run":              dry_run,
        "total_contacts_checked": len(contacts),
        "contacts_updated":     updated,
        "contacts_skipped":     skipped,
        "errors":               len(errors),
        "error_details":        errors[:10],
        "preview_examples":     examples,
        "message": (
            f"{'DRY RUN — no changes made. ' if dry_run else ''}"
            f"{updated} contacts {'would be' if dry_run else 'were'} updated."
        ),
    }


def get_contacts_with_mismatched_account_field(
    account_field: str = "tyr_tyrtype",
    contact_field: str = "tyr_tyrtype",
    limit: int = 200,
) -> dict:
    """
    Find contacts where the field value does NOT match their parent account's value.
    Uses a single bulk query for speed.
    """
    params = {
        "$select": f"contactid,fullname,emailaddress1,{contact_field},_parentcustomerid_value",
        "$expand": f"parentcustomerid_account($select=accountid,name,{account_field})",
        "$filter": "_parentcustomerid_value ne null",
        "$top": 5000,
    }

    contacts = crm_get("contacts", params).get("value", [])

    mismatches = []
    for contact in contacts:
        contact_val  = contact.get(contact_field)
        account_data = contact.get("parentcustomerid_account") or {}
        account_val  = account_data.get(account_field)

        if account_val is None:
            continue

        if contact_val != account_val:
            mismatches.append({
                "contact_name":  contact.get("fullname", "Unknown"),
                "contact_id":    contact.get("contactid"),
                "email":         contact.get("emailaddress1", ""),
                "account_name":  account_data.get("name", ""),
                "account_value": account_val,
                "contact_value": contact_val,
            })
            if len(mismatches) >= limit:
                break

    return {
        "total_mismatches_found": len(mismatches),
        "account_field": account_field,
        "contact_field": contact_field,
        "mismatches": mismatches,
        "message": f"Found {len(mismatches)} contacts out of sync.",
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
