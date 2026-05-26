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


def create_contact(
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    phone: str = "",
    job_title: str = "",
    notes: str = "",
) -> dict:
    """
    Create a new contact in the CRM.
    Duplicate contacts sharing the same email are permitted — no uniqueness check is performed.
    """
    import re

    payload = {}
    if first_name:
        payload["firstname"] = first_name
    if last_name:
        payload["lastname"] = last_name
    if email:
        payload["emailaddress1"] = email
    if phone:
        payload["telephone1"] = phone
    if job_title:
        payload["jobtitle"] = job_title
    if notes:
        payload["description"] = notes

    result = crm_post("contacts", payload)

    record_url = result.get("record_url", "")
    contact_id = ""
    if record_url:
        m = re.search(r'\(([^)]+)\)$', record_url)
        if m:
            contact_id = m.group(1)

    full_name = f"{first_name} {last_name}".strip()
    return {
        "success": True,
        "contact_id": contact_id,
        "name": full_name,
        "message": f"Contact '{full_name}' created successfully.",
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


def configure_contact_duplicate_rule() -> dict:
    """
    Replace existing contact duplicate detection rules with a single rule that
    flags a duplicate only when BOTH email address AND account match.
    Contacts sharing an email but linked to different accounts are allowed.
    """
    import re

    RULE_NAME = "Contact Duplicate - Same Email and Account"

    # Disable all currently active contact duplicate rules (excluding the one we manage)
    existing = crm_get("duplicaterules", {
        "$select": "duplicateruleid,name",
        "$filter": "baseentityname eq 'contact' and statecode eq 0",
    }).get("value", [])

    for rule in existing:
        if rule.get("name") != RULE_NAME:
            crm_patch("duplicaterules", rule["duplicateruleid"], {"statecode": 1, "statuscode": 2})

    # Check if our rule already exists (may have been partially created in a prior attempt)
    rule_id = ""
    existing_managed = crm_get("duplicaterules", {
        "$select": "duplicateruleid",
        "$filter": f"name eq '{RULE_NAME}'",
    }).get("value", [])

    if existing_managed:
        rule_id = existing_managed[0]["duplicateruleid"]
        # Deactivate then delete so we can recreate cleanly
        try:
            crm_patch("duplicaterules", rule_id, {"statecode": 1, "statuscode": 2})
        except Exception:
            pass
        crm_delete("duplicaterules", rule_id)
        rule_id = ""

    if not rule_id:
        rule_result = crm_post("duplicaterules", {
            "name": RULE_NAME,
            "baseentityname": "contact",
            "matchingentityname": "contact",
            "description": "Duplicate only when email address AND account both match.",
        })
        record_url = rule_result.get("record_url", "")
        if record_url:
            m = re.search(r'\(([^)]+)\)$', record_url)
            if m:
                rule_id = m.group(1)

    if not rule_id:
        return {"success": False, "message": "Could not create or locate the duplicate rule."}

    # Condition 1: same email address
    crm_post("duplicateruleconditions", {
        "baseattributename": "emailaddress1",
        "matchingattributename": "emailaddress1",
        "operatorcode": 0,
        "ignoreblankvalues": True,
        "duplicateruleid@odata.bind": f"/duplicaterules({rule_id})",
    })

    # Condition 2: same account (parentcustomerid lookup)
    crm_post("duplicateruleconditions", {
        "baseattributename": "parentcustomerid",
        "matchingattributename": "parentcustomerid",
        "operatorcode": 0,
        "ignoreblankvalues": True,
        "duplicateruleid@odata.bind": f"/duplicaterules({rule_id})",
    })

    # Publish/activate the rule
    crm_action("PublishDuplicateRule", {"DuplicateRuleId": rule_id})

    return {
        "success": True,
        "rule_id": rule_id,
        "old_rules_disabled": [r["name"] for r in existing],
        "message": (
            f"Disabled {len(existing)} old rule(s) and created new rule "
            f"'Contact Duplicate - Same Email and Account'. "
            f"Contacts will only be flagged as duplicates when both email and account match."
        ),
    }


def disable_duplicate_detection_rules(entity: str = "contact") -> dict:
    """
    Find and deactivate all active duplicate detection rules for an entity in Dynamics 365.
    This removes the platform-level block so duplicate records can be created both
    via the API and directly in the CRM UI (e.g. the Qualify Lead button).

    entity: the CRM entity name to target (default "contact")
    """
    params = {
        "$select": "duplicateruleid,name,baseentityname,statecode",
        "$filter": f"baseentityname eq '{entity}' and statecode eq 0",
    }
    result = crm_get("duplicaterules", params)
    rules = result.get("value", [])

    if not rules:
        return {
            "success": True,
            "message": f"No active duplicate detection rules found for '{entity}'. Nothing to disable.",
            "rules_disabled": [],
        }

    disabled = []
    for rule in rules:
        rule_id = rule.get("duplicateruleid")
        rule_name = rule.get("name", "Unknown rule")
        crm_patch("duplicaterules", rule_id, {"statecode": 1, "statuscode": 2})
        disabled.append({"id": rule_id, "name": rule_name})

    return {
        "success": True,
        "message": f"Disabled {len(disabled)} duplicate detection rule(s) for '{entity}'. Duplicates can now be created in the UI and via API.",
        "rules_disabled": disabled,
    }
