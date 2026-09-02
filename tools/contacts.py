# ============================================================
# tools/contacts.py — Contact Management Tools
# ============================================================
# These are the "hands" Claude uses to manage contacts
# in your Microsoft Dynamics 365 CRM.
#
# Each function does one specific thing:
#   - Search contacts
#   - Find duplicates
#   - Fix missing data
#   - Update records
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post, crm_delete


def search_contacts(search_term: str = "", limit: int = 50) -> dict:
    """
    Search for contacts in the CRM.

    search_term: name, email, or company to search for (leave blank to get all)
    limit: max number of contacts to return (default 50)

    Returns a list of matching contacts with their key details.
    """
    params = {
        "$top": limit,
        "$select": "contactid,fullname,emailaddress1,telephone1,jobtitle,parentcustomerid,createdon,modifiedon,statecode",
        "$orderby": "modifiedon desc",
    }

    if search_term:
        # Search across name and email
        params["$filter"] = (
            f"contains(fullname,'{search_term}') or "
            f"contains(emailaddress1,'{search_term}') or "
            f"contains(jobtitle,'{search_term}')"
        )

    result = crm_get("contacts", params)
    contacts = result.get("value", [])

    return {
        "total_found": len(contacts),
        "contacts": [
            {
                "id": c.get("contactid"),
                "name": c.get("fullname", "No name"),
                "email": c.get("emailaddress1", "No email"),
                "phone": c.get("telephone1", "No phone"),
                "job_title": c.get("jobtitle", ""),
                "company": c.get("_parentcustomerid_value@OData.Community.Display.V1.FormattedValue", ""),
                "status": "Active" if c.get("statecode") == 0 else "Inactive",
                "last_modified": c.get("modifiedon", ""),
            }
            for c in contacts
        ],
    }


def find_contacts_missing_data(field: str = "email") -> dict:
    """
    Find contacts that are missing important information.

    field: the field to check — options are:
           "email"     → contacts with no email address
           "phone"     → contacts with no phone number
           "company"   → contacts not linked to a company
           "name"      → contacts with no full name

    Returns a list of contacts that need attention.
    """
    field_map = {
        "email":   "emailaddress1",
        "phone":   "telephone1",
        "company": "_parentcustomerid_value",
        "name":    "fullname",
    }

    crm_field = field_map.get(field, "emailaddress1")

    params = {
        "$top": 200,
        "$select": "contactid,fullname,emailaddress1,telephone1,jobtitle,createdon",
        "$filter": f"{crm_field} eq null",
        "$orderby": "createdon desc",
    }

    result = crm_get("contacts", params)
    contacts = result.get("value", [])

    return {
        "field_checked": field,
        "total_missing": len(contacts),
        "message": f"Found {len(contacts)} contacts missing {field}",
        "contacts": [
            {
                "id": c.get("contactid"),
                "name": c.get("fullname", "No name"),
                "email": c.get("emailaddress1", ""),
                "phone": c.get("telephone1", ""),
                "created": c.get("createdon", ""),
            }
            for c in contacts
        ],
    }


def find_duplicate_contacts() -> dict:
    """
    Find contacts that appear to be duplicates.
    Duplicates are contacts that share the same email address.

    Returns groups of duplicates so you can decide what to merge.
    """
    # Fetch all contacts with emails
    params = {
        "$top": 5000,
        "$select": "contactid,fullname,emailaddress1,telephone1,createdon,modifiedon",
        "$filter": "emailaddress1 ne null",
        "$orderby": "emailaddress1 asc",
    }

    result = crm_get("contacts", params)
    contacts = result.get("value", [])

    # Group contacts by email address
    email_groups: dict = {}
    for contact in contacts:
        email = contact.get("emailaddress1", "").lower().strip()
        if email:
            if email not in email_groups:
                email_groups[email] = []
            email_groups[email].append(contact)

    # Find groups with more than one contact (those are duplicates)
    duplicates = {
        email: group
        for email, group in email_groups.items()
        if len(group) > 1
    }

    # Format for readability
    duplicate_list = []
    for email, group in duplicates.items():
        duplicate_list.append({
            "shared_email": email,
            "count": len(group),
            "contacts": [
                {
                    "id": c.get("contactid"),
                    "name": c.get("fullname", "No name"),
                    "created": c.get("createdon", ""),
                    "last_modified": c.get("modifiedon", ""),
                }
                for c in group
            ],
        })

    return {
        "total_duplicate_groups": len(duplicates),
        "total_duplicate_contacts": sum(len(g) for g in duplicates.values()),
        "message": f"Found {len(duplicates)} sets of duplicate contacts",
        "duplicates": duplicate_list,
    }


def update_contact(contact_id: str, updates: dict) -> dict:
    """
    Update a contact's information in the CRM.

    contact_id: the unique ID of the contact (from search results)
    updates: a dictionary of fields to change, for example:
             {"emailaddress1": "new@email.com", "telephone1": "555-1234"}

    Common field names:
      fullname         → full name
      emailaddress1    → primary email
      telephone1       → business phone
      jobtitle         → job title
      description      → notes about the contact

    Returns confirmation of what was updated.
    """
    result = crm_patch("contacts", contact_id, updates)
    return {
        "success": True,
        "contact_id": contact_id,
        "fields_updated": list(updates.keys()),
        "message": f"Successfully updated contact {contact_id}",
    }


def get_contact_details(contact_id: str) -> dict:
    """
    Get all details for a single contact.

    contact_id: the unique ID of the contact

    Returns all available information about the contact.
    """
    result = crm_get(f"contacts({contact_id})")
    c = result

    return {
        "id": c.get("contactid"),
        "name": c.get("fullname", ""),
        "email": c.get("emailaddress1", ""),
        "email2": c.get("emailaddress2", ""),
        "phone": c.get("telephone1", ""),
        "mobile": c.get("mobilephone", ""),
        "job_title": c.get("jobtitle", ""),
        "department": c.get("department", ""),
        "description": c.get("description", ""),
        "address": {
            "street": c.get("address1_line1", ""),
            "city": c.get("address1_city", ""),
            "state": c.get("address1_stateorprovince", ""),
            "zip": c.get("address1_postalcode", ""),
            "country": c.get("address1_country", ""),
        },
        "status": "Active" if c.get("statecode") == 0 else "Inactive",
        "created": c.get("createdon", ""),
        "last_modified": c.get("modifiedon", ""),
    }


def get_contact_summary() -> dict:
    """
    Get a high-level summary of all contacts in the CRM.
    Useful for a quick data quality overview.

    Returns total counts, active vs inactive, and data quality metrics.
    """
    # Total contacts
    total_result = crm_get("contacts", {"$select": "contactid", "$top": 1})
    # Note: OData count requires a separate query
    params_total   = {"$select": "contactid,statecode", "$top": 5000}
    params_no_email = {"$select": "contactid", "$filter": "emailaddress1 eq null", "$top": 5000}
    params_no_phone = {"$select": "contactid", "$filter": "telephone1 eq null", "$top": 5000}
    params_no_co    = {"$select": "contactid", "$filter": "_parentcustomerid_value eq null", "$top": 5000}

    all_contacts = crm_get("contacts", params_total).get("value", [])
    no_email     = crm_get("contacts", params_no_email).get("value", [])
    no_phone     = crm_get("contacts", params_no_phone).get("value", [])
    no_company   = crm_get("contacts", params_no_co).get("value", [])

    total    = len(all_contacts)
    active   = sum(1 for c in all_contacts if c.get("statecode") == 0)
    inactive = total - active

    return {
        "total_contacts": total,
        "active_contacts": active,
        "inactive_contacts": inactive,
        "data_quality": {
            "missing_email":   {"count": len(no_email),   "percent": f"{len(no_email)/total*100:.1f}%" if total else "0%"},
            "missing_phone":   {"count": len(no_phone),   "percent": f"{len(no_phone)/total*100:.1f}%" if total else "0%"},
            "missing_company": {"count": len(no_company), "percent": f"{len(no_company)/total*100:.1f}%" if total else "0%"},
        },
        "overall_health": "Good" if len(no_email) / total < 0.1 else "Needs Attention" if total else "No Data",
    }


def sync_contact_owners_from_accounts(preview_only: bool = False, limit: int = 5000) -> dict:
    """
    Sync contact owners to match their parent account's owner.

    For every active contact that has a parent account, if the contact's
    owner differs from the account's owner, update the contact to match.

    preview_only: if True, show what would change without writing anything
    limit: max contacts to process (default 5000)
    """
    # Fetch all active contacts with their owner and parent account.
    # Select the navigation field name (without underscores) so D365 reliably
    # returns the backing _value GUIDs in the response.
    try:
        contacts = []
        page = crm_get("contacts", {
            "$select": "contactid,fullname,_ownerid_value,_parentcustomerid_value",
            "$filter": "statecode eq 0 and _parentcustomerid_value ne null",
            "$top": 2000,
        })
        contacts.extend(page.get("value", []))
        next_link = page.get("@odata.nextLink")
        while next_link and len(contacts) < limit:
            # nextLink is a full URL; strip the base so crm_get can prefix it
            from config.crm_connection import DYNAMICS_URL
            base_prefix = f"{DYNAMICS_URL}/api/data/v9.2/"
            relative = next_link[len(base_prefix):] if next_link.startswith(base_prefix) else next_link
            page = crm_get(relative, {})
            contacts.extend(page.get("value", []))
            next_link = page.get("@odata.nextLink")
    except Exception as e:
        return {"error": f"Could not fetch contacts: {e}"}

    if not contacts:
        return {"message": "No active contacts with a parent account found.", "count": 0}

    # Pull owner GUIDs — D365 returns them as _ownerid_value / _parentcustomerid_value
    # regardless of whether we selected "ownerid" or "_ownerid_value".
    def _owner(record):
        return record.get("_ownerid_value")

    def _parent_acct(record):
        return record.get("_parentcustomerid_value")

    # Collect unique account IDs and fetch their owners in bulk.
    # Also fetch tyr_salesrepresentativeid in case the "Sales Representative"
    # field shown in the UI is a custom lookup rather than the standard ownerid.
    account_ids = list({_parent_acct(c) for c in contacts if _parent_acct(c)})

    account_owner_map = {}       # account_id → owner_id (standard ownerid)
    account_salesrep_map = {}    # account_id → salesrep_id (custom field, may be null)
    try:
        batch_size = 100
        for i in range(0, len(account_ids), batch_size):
            batch = account_ids[i:i + batch_size]
            filter_str = " or ".join(f"accountid eq '{aid}'" for aid in batch)
            accts = crm_get("accounts", {
                "$select": "accountid,_ownerid_value,_tyr_salesrepresentativeid_value",
                "$filter": filter_str,
                "$top": batch_size,
            }).get("value", [])
            for a in accts:
                account_owner_map[a["accountid"]] = a.get("_ownerid_value")
                account_salesrep_map[a["accountid"]] = a.get("_tyr_salesrepresentativeid_value")
    except Exception as e:
        return {"error": f"Could not fetch account owners: {e}"}

    # Diagnostic: count how many contacts/accounts have null owners
    null_contact_owners = sum(1 for c in contacts if not _owner(c))
    null_acct_owners = sum(1 for aid in account_ids if not account_owner_map.get(aid))

    # Determine which account field drives contact ownership.
    # If the custom tyr_salesrepresentativeid field is populated on any account,
    # use that; otherwise fall back to the standard ownerid.
    any_salesrep = any(v for v in account_salesrep_map.values() if v)
    use_salesrep = any_salesrep

    # Find contacts where owner doesn't match the account's designated owner
    to_update = []
    for c in contacts:
        acct_id = _parent_acct(c)
        if use_salesrep:
            acct_owner = account_salesrep_map.get(acct_id) or account_owner_map.get(acct_id)
        else:
            acct_owner = account_owner_map.get(acct_id)
        contact_owner = _owner(c)
        if acct_owner and acct_owner != contact_owner:
            to_update.append({
                "contactid": c["contactid"],
                "name": c.get("fullname", ""),
                "account_id": acct_id,
                "new_owner_id": acct_owner,
                "old_owner_id": contact_owner,
            })

    # Sample of first 3 contacts for diagnostics
    sample = [
        {
            "name": c.get("fullname", ""),
            "contact_owner": _owner(c),
            "account_owner": account_owner_map.get(_parent_acct(c)),
            "account_salesrep": account_salesrep_map.get(_parent_acct(c)),
            "using_salesrep_field": use_salesrep,
            "match": _owner(c) == (
                (account_salesrep_map.get(_parent_acct(c)) or account_owner_map.get(_parent_acct(c)))
                if use_salesrep else account_owner_map.get(_parent_acct(c))
            ),
        }
        for c in contacts[:3]
    ]

    if preview_only or not to_update:
        return {
            "preview_only": preview_only,
            "contacts_checked": len(contacts),
            "accounts_checked": len(account_ids),
            "contacts_to_update": len(to_update),
            "null_contact_owners": null_contact_owners,
            "null_account_owners": null_acct_owners,
            "sample_comparisons": sample,
            "changes": [
                {"contact": r["name"], "new_owner_id": r["new_owner_id"], "old_owner_id": r["old_owner_id"]}
                for r in to_update[:50]
            ],
            "message": (
                f"Checked {len(contacts)} contacts against {len(account_ids)} accounts. "
                f"{len(to_update)} contact(s) have a different owner than their account. "
                f"({null_contact_owners} contacts with null owner, {null_acct_owners} accounts with null owner.) "
                + ("Set preview_only=False to apply." if preview_only else "No changes needed.")
            ),
        }

    # Apply updates
    updated = []
    errors = []
    for r in to_update:
        try:
            crm_patch("contacts", r["contactid"], {
                "ownerid@odata.bind": f"/systemusers({r['new_owner_id']})"
            })
            updated.append(r["name"])
        except Exception as e:
            errors.append({"name": r["name"], "error": str(e)})

    return {
        "success": True,
        "contacts_checked": len(contacts),
        "accounts_checked": len(account_ids),
        "updated": len(updated),
        "errors": len(errors),
        "error_details": errors,
        "null_contact_owners": null_contact_owners,
        "null_account_owners": null_acct_owners,
        "message": f"Updated {len(updated)} contact owner(s) to match their account. {len(errors)} error(s).",
    }
