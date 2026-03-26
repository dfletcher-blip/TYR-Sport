# ============================================================
# tools/bulk_updates.py — Bulk Update Operations
# ============================================================
# Update many records at once based on a filter condition.
# Always previews affected records before writing.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch


def bulk_update_contacts(filter_criteria: str, updates: dict, preview_only: bool = False) -> dict:
    """
    Update multiple contacts at once that match a filter.

    filter_criteria: OData filter string, e.g.:
                     "statecode eq 0 and emailaddress1 eq null"
                     "contains(companyname,'Acme')"
    updates: fields to set on every matching record, e.g.:
             {"donotbulkemail": True} or {"statecode": 1}
    preview_only: if True, return the list of matches WITHOUT updating (safe preview)

    Returns how many records were affected.
    """
    params = {
        "$select": "contactid,fullname,emailaddress1,statecode",
        "$filter": filter_criteria,
        "$top": 500,
    }
    result = crm_get("contacts", params)
    contacts = result.get("value", [])

    if not contacts:
        return {"message": "No contacts matched the filter.", "filter": filter_criteria, "count": 0}

    preview = [
        {"id": c.get("contactid"), "name": c.get("fullname", ""), "email": c.get("emailaddress1", "")}
        for c in contacts
    ]

    if preview_only:
        return {
            "preview_only": True,
            "matched_count": len(contacts),
            "filter": filter_criteria,
            "updates_that_would_apply": updates,
            "records": preview,
        }

    errors = []
    updated = 0
    for c in contacts:
        try:
            crm_patch("contacts", c["contactid"], updates)
            updated += 1
        except Exception as e:
            errors.append({"id": c["contactid"], "error": str(e)})

    return {
        "success": True,
        "total_matched": len(contacts),
        "total_updated": updated,
        "errors": errors,
        "fields_updated": list(updates.keys()),
        "filter": filter_criteria,
        "message": f"Updated {updated} of {len(contacts)} contacts",
    }


def bulk_update_leads(filter_criteria: str, updates: dict, preview_only: bool = False) -> dict:
    """
    Update multiple leads at once that match a filter.

    filter_criteria: OData filter string, e.g.:
                     "statecode eq 0 and leadsourcecode eq 8"
    updates: fields to set on matching leads
    preview_only: if True, return matches without updating
    """
    params = {
        "$select": "leadid,fullname,emailaddress1,companyname",
        "$filter": filter_criteria,
        "$top": 500,
    }
    result = crm_get("leads", params)
    leads = result.get("value", [])

    if not leads:
        return {"message": "No leads matched the filter.", "filter": filter_criteria, "count": 0}

    preview = [
        {"id": l.get("leadid"), "name": l.get("fullname", ""), "company": l.get("companyname", "")}
        for l in leads
    ]

    if preview_only:
        return {
            "preview_only": True,
            "matched_count": len(leads),
            "filter": filter_criteria,
            "updates_that_would_apply": updates,
            "records": preview,
        }

    errors = []
    updated = 0
    for l in leads:
        try:
            crm_patch("leads", l["leadid"], updates)
            updated += 1
        except Exception as e:
            errors.append({"id": l["leadid"], "error": str(e)})

    return {
        "success": True,
        "total_matched": len(leads),
        "total_updated": updated,
        "errors": errors,
        "fields_updated": list(updates.keys()),
        "filter": filter_criteria,
        "message": f"Updated {updated} of {len(leads)} leads",
    }


def bulk_update_accounts(filter_criteria: str, updates: dict, preview_only: bool = False) -> dict:
    """
    Update multiple accounts at once that match a filter.

    filter_criteria: OData filter string, e.g.:
                     "address1_stateorprovince eq 'CA'"
    updates: fields to set on matching accounts
    preview_only: if True, return matches without updating
    """
    params = {
        "$select": "accountid,name,emailaddress1,address1_city",
        "$filter": filter_criteria,
        "$top": 500,
    }
    result = crm_get("accounts", params)
    accounts = result.get("value", [])

    if not accounts:
        return {"message": "No accounts matched the filter.", "filter": filter_criteria, "count": 0}

    preview = [
        {"id": a.get("accountid"), "name": a.get("name", ""), "city": a.get("address1_city", "")}
        for a in accounts
    ]

    if preview_only:
        return {
            "preview_only": True,
            "matched_count": len(accounts),
            "filter": filter_criteria,
            "updates_that_would_apply": updates,
            "records": preview,
        }

    errors = []
    updated = 0
    for a in accounts:
        try:
            crm_patch("accounts", a["accountid"], updates)
            updated += 1
        except Exception as e:
            errors.append({"id": a["accountid"], "error": str(e)})

    return {
        "success": True,
        "total_matched": len(accounts),
        "total_updated": updated,
        "errors": errors,
        "fields_updated": list(updates.keys()),
        "filter": filter_criteria,
        "message": f"Updated {updated} of {len(accounts)} accounts",
    }


def bulk_update_opportunities(filter_criteria: str, updates: dict, preview_only: bool = False) -> dict:
    """
    Update multiple opportunities at once that match a filter.

    filter_criteria: OData filter string, e.g.:
                     "statecode eq 0 and closeprobability lt 20"
    updates: fields to set on matching opportunities
    preview_only: if True, return matches without updating
    """
    params = {
        "$select": "opportunityid,name,estimatedvalue,closeprobability",
        "$filter": filter_criteria,
        "$top": 500,
    }
    result = crm_get("opportunities", params)
    opps = result.get("value", [])

    if not opps:
        return {"message": "No opportunities matched the filter.", "filter": filter_criteria, "count": 0}

    preview = [
        {"id": o.get("opportunityid"), "name": o.get("name", ""), "value": o.get("estimatedvalue")}
        for o in opps
    ]

    if preview_only:
        return {
            "preview_only": True,
            "matched_count": len(opps),
            "filter": filter_criteria,
            "updates_that_would_apply": updates,
            "records": preview,
        }

    errors = []
    updated = 0
    for o in opps:
        try:
            crm_patch("opportunities", o["opportunityid"], updates)
            updated += 1
        except Exception as e:
            errors.append({"id": o["opportunityid"], "error": str(e)})

    return {
        "success": True,
        "total_matched": len(opps),
        "total_updated": updated,
        "errors": errors,
        "fields_updated": list(updates.keys()),
        "filter": filter_criteria,
        "message": f"Updated {updated} of {len(opps)} opportunities",
    }
