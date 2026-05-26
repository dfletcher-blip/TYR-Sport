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


def _to_int(val):
    """
    Convert a value to int if possible.
    Handles MultiSelectPicklist strings like "935650004" or "935650001,935650004"
    by taking the first value.
    Returns None if val is None.
    """
    if val is None:
        return None
    s = str(val).strip()
    if "," in s:
        s = s.split(",")[0].strip()
    try:
        return int(s)
    except (ValueError, TypeError):
        return val  # return as-is if not numeric


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
        contact_id   = contact.get("contactid")
        contact_name = contact.get("fullname", "Unknown")
        contact_val  = contact.get(contact_field)
        account_data = contact.get("parentcustomerid_account") or {}
        account_val  = account_data.get(account_field)

        # Skip if account has no value for this field
        if account_val is None:
            skipped += 1
            continue

        # Convert MultiSelectPicklist string to int (single-select Contact field expects int)
        account_val = _to_int(account_val)

        # Skip if already in sync
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
                    "contact":  contact_name,
                    "account":  account_data.get("name", ""),
                    "from":     contact_val,
                    "to":       account_val,
                })

    result = {
        "dry_run":                dry_run,
        "total_contacts_checked": len(contacts),
        "contacts_updated":       updated,
        "contacts_skipped":       skipped,
        "errors":                 len(errors),
        "error_details":          errors[:5],
    }
    if examples:
        result["preview_examples"] = examples
    return result


def get_contacts_with_mismatched_account_field(
    account_field: str = "tyr_tyrtype",
    contact_field: str = "tyr_tyrtype",
    limit: int = 100,
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
        account_val  = _to_int(account_data.get(account_field))

        if account_val is None:
            continue

        if contact_val != account_val:
            mismatches.append({
                "contact_name":   contact.get("fullname", "Unknown"),
                "contact_id":     contact.get("contactid"),
                "email":          contact.get("emailaddress1", ""),
                "account_name":   account_data.get("name", ""),
                "account_value":  account_val,
                "contact_value":  contact_val,
            })
        if len(mismatches) >= limit:
            break

    return {
        "total_mismatches_found": len(mismatches),
        "account_field":          account_field,
        "contact_field":          contact_field,
        "mismatches":             mismatches,
        "message":                f"Found {len(mismatches)} contacts out of sync.",
    }


def sync_contact_owners(dry_run: bool = False) -> dict:
    """
    Sync contact owners to match their parent account's owner.

    Finds all active contacts whose ownerid differs from their account's ownerid
    and updates them to match. Skips contacts with no parent account.

    dry_run: if True, show what WOULD be updated without making changes
    """
    import uuid, time, os, requests
    from config.crm_connection import get_access_token

    DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
    _token: dict = {"value": None, "expires": 0}

    def get_headers():
        if not _token["value"] or time.time() >= _token["expires"]:
            _token["value"] = get_access_token()
            _token["expires"] = time.time() + 3000
        return {
            "Authorization": f"Bearer {_token['value']}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "odata.include-annotations=*",
        }

    # Fetch all active contacts with a parent account, expand account owner
    contacts_to_update = []
    url = f"{DYNAMICS_URL}/api/data/v9.2/contacts"
    params = {
        "$select": "contactid,fullname,_ownerid_value",
        "$expand": "parentcustomerid_account($select=accountid,name,_ownerid_value)",
        "$filter": "_parentcustomerid_value ne null and statecode eq 0",
        "$top": 2000,
    }

    while url:
        r = requests.get(url, headers=get_headers(), params=params, timeout=30)
        if not r.ok:
            return {"success": False, "error": f"{r.status_code}: {r.text[:300]}"}
        data = r.json()
        for c in data.get("value", []):
            account = c.get("parentcustomerid_account") or {}
            acct_owner = account.get("_ownerid_value")
            if not acct_owner or c.get("_ownerid_value") == acct_owner:
                continue
            owner_type = account.get(
                "_ownerid_value@Microsoft.Dynamics.CRM.lookuplogicalname", "systemuser"
            )
            entity_set = "teams" if owner_type == "team" else "systemusers"
            contacts_to_update.append({
                "contactid":    c["contactid"],
                "name":         c.get("fullname", "Unknown"),
                "account_name": account.get("name", ""),
                "bind":         f"/{entity_set}({acct_owner})",
            })
        url = data.get("@odata.nextLink")
        params = None

    if not contacts_to_update:
        return {"success": True, "message": "All contacts already match their account owner.", "updated": 0}

    if dry_run:
        return {
            "dry_run": True,
            "contacts_to_update": len(contacts_to_update),
            "preview": [
                {"contact": c["name"], "account": c["account_name"], "new_owner_bind": c["bind"]}
                for c in contacts_to_update[:20]
            ],
        }

    # Batch PATCH in groups of 50
    BATCH_SIZE = 50
    updated = errors = 0
    total_batches = (len(contacts_to_update) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, start in enumerate(range(0, len(contacts_to_update), BATCH_SIZE), 1):
        batch = contacts_to_update[start:start + BATCH_SIZE]
        boundary = f"batch_{uuid.uuid4().hex}"
        parts = []
        for c in batch:
            payload = f'{{"ownerid@odata.bind":"{c["bind"]}"}}'
            parts.append(
                f"--{boundary}\r\n"
                f"Content-Type: application/http\r\n"
                f"Content-Transfer-Encoding: binary\r\n\r\n"
                f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({c['contactid']}) HTTP/1.1\r\n"
                f"Content-Type: application/json\r\n"
                f"If-Match: *\r\n\r\n"
                f"{payload}\r\n"
            )
        body = "".join(parts) + f"--{boundary}--\r\n"
        resp = requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/$batch",
            headers={**get_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
            data=body.encode("utf-8"),
            timeout=120,
        )
        if resp.ok:
            ok = resp.text.count("HTTP/1.1 204")
            updated += ok
            errors += len(batch) - ok
        else:
            errors += len(batch)
        time.sleep(0.5)

    return {
        "success": errors == 0,
        "contacts_checked": len(contacts_to_update),
        "updated": updated,
        "errors": errors,
        "message": f"Synced {updated} contact owner(s) to match their account. {errors} error(s).",
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
