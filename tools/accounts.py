# ============================================================
# tools/accounts.py — Account / Company Management
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


def search_accounts(search_term: str = "", limit: int = 50) -> dict:
    """
    Search for accounts (companies) in the CRM.

    search_term: company name or city to search for (leave blank to get all)
    limit: max results to return (default 50)
    """
    params = {
        "$top": limit,
        "$select": "accountid,name,emailaddress1,telephone1,websiteurl,address1_city,address1_stateorprovince,statecode,createdon,modifiedon",
        "$orderby": "modifiedon desc",
    }

    if search_term:
        params["$filter"] = (
            f"contains(name,'{search_term}') or "
            f"contains(address1_city,'{search_term}')"
        )

    result = crm_get("accounts", params)
    accounts = result.get("value", [])

    return {
        "total_found": len(accounts),
        "accounts": [
            {
                "id": a.get("accountid"),
                "name": a.get("name", "Unnamed"),
                "email": a.get("emailaddress1", ""),
                "phone": a.get("telephone1", ""),
                "website": a.get("websiteurl", ""),
                "city": a.get("address1_city", ""),
                "state": a.get("address1_stateorprovince", ""),
                "status": "Active" if a.get("statecode") == 0 else "Inactive",
                "last_modified": a.get("modifiedon", ""),
            }
            for a in accounts
        ],
    }


def get_account_details(account_id: str) -> dict:
    """
    Get all details for a specific account, including its contacts and opportunities.

    account_id: the unique ID of the account
    """
    a = crm_get(f"accounts({account_id})")

    # Get contacts linked to this account
    contacts_result = crm_get("contacts", {
        "$select": "contactid,fullname,emailaddress1,jobtitle",
        "$filter": f"_parentcustomerid_value eq {account_id}",
        "$top": 50,
    })
    contacts = contacts_result.get("value", [])

    # Get open opportunities for this account
    opps_result = crm_get("opportunities", {
        "$select": "opportunityid,name,estimatedvalue,statecode",
        "$filter": f"_customerid_value eq {account_id} and statecode eq 0",
        "$top": 50,
    })
    opps = opps_result.get("value", [])

    return {
        "id": a.get("accountid"),
        "name": a.get("name", ""),
        "email": a.get("emailaddress1", ""),
        "phone": a.get("telephone1", ""),
        "website": a.get("websiteurl", ""),
        "address": {
            "street": a.get("address1_line1", ""),
            "city": a.get("address1_city", ""),
            "state": a.get("address1_stateorprovince", ""),
            "zip": a.get("address1_postalcode", ""),
            "country": a.get("address1_country", ""),
        },
        "employees": a.get("numberofemployees"),
        "revenue": a.get("revenue"),
        "description": a.get("description", ""),
        "status": "Active" if a.get("statecode") == 0 else "Inactive",
        "created": a.get("createdon", ""),
        "last_modified": a.get("modifiedon", ""),
        "contacts": [
            {"id": c.get("contactid"), "name": c.get("fullname", ""), "email": c.get("emailaddress1", ""), "title": c.get("jobtitle", "")}
            for c in contacts
        ],
        "open_opportunities": [
            {"id": o.get("opportunityid"), "name": o.get("name", ""), "value": o.get("estimatedvalue")}
            for o in opps
        ],
    }


def update_account(account_id: str, updates: dict) -> dict:
    """
    Update an account's fields.

    account_id: the unique ID of the account
    updates: fields to change, e.g.:
             {"telephone1": "555-1234", "websiteurl": "https://example.com"}

    Common fields:
      name                      → company name
      emailaddress1             → primary email
      telephone1                → phone number
      websiteurl                → website
      address1_city             → city
      address1_stateorprovince  → state
      description               → notes
    """
    crm_patch("accounts", account_id, updates)
    return {
        "success": True,
        "account_id": account_id,
        "fields_updated": list(updates.keys()),
        "message": f"Account {account_id} updated successfully",
    }


def get_account_summary() -> dict:
    """
    Get a high-level summary of all accounts in the CRM.
    """
    params = {"$select": "accountid,statecode,address1_stateorprovince", "$top": 5000}
    accounts = crm_get("accounts", params).get("value", [])

    total    = len(accounts)
    active   = sum(1 for a in accounts if a.get("statecode") == 0)
    inactive = total - active

    # State breakdown
    state_counts: dict = {}
    for a in accounts:
        state = a.get("address1_stateorprovince", "Unknown") or "Unknown"
        state_counts[state] = state_counts.get(state, 0) + 1
    top_states = sorted(state_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_accounts": total,
        "active": active,
        "inactive": inactive,
        "top_states": [{"state": s, "count": c} for s, c in top_states],
    }


def find_accounts_missing_data(field: str = "email") -> dict:
    """
    Find accounts missing important information.

    field: "email", "phone", "website", or "address"
    """
    field_map = {
        "email":   "emailaddress1",
        "phone":   "telephone1",
        "website": "websiteurl",
        "address": "address1_city",
    }
    crm_field = field_map.get(field, "emailaddress1")

    params = {
        "$top": 200,
        "$select": "accountid,name,emailaddress1,telephone1,websiteurl",
        "$filter": f"{crm_field} eq null and statecode eq 0",
        "$orderby": "name asc",
    }

    result = crm_get("accounts", params)
    accounts = result.get("value", [])

    return {
        "field_checked": field,
        "total_missing": len(accounts),
        "message": f"Found {len(accounts)} active accounts missing {field}",
        "accounts": [
            {
                "id": a.get("accountid"),
                "name": a.get("name", ""),
                "email": a.get("emailaddress1", ""),
                "phone": a.get("telephone1", ""),
            }
            for a in accounts
        ],
    }
