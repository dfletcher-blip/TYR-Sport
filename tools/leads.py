# ============================================================
# tools/leads.py — Lead Management
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post, crm_action


def search_leads(search_term: str = "", status: str = "open", limit: int = 50) -> dict:
    """
    Search for leads in the CRM.

    search_term: name, email, or company to search for (leave blank for all)
    status: "open", "qualified", "disqualified", or "all"
    limit: max results to return (default 50)
    """
    status_filter = {
        "open":           "statecode eq 0",
        "qualified":      "statecode eq 1",
        "disqualified":   "statecode eq 2",
        "all":            None,
    }.get(status.lower(), "statecode eq 0")

    params = {
        "$top": limit,
        "$select": "leadid,fullname,emailaddress1,telephone1,jobtitle,companyname,subject,statecode,leadsourcecode,createdon,modifiedon",
        "$expand": "ownerid($select=fullname)",
        "$orderby": "modifiedon desc",
    }

    filters = []
    if status_filter:
        filters.append(status_filter)
    if search_term:
        filters.append(
            f"(contains(fullname,'{search_term}') or "
            f"contains(emailaddress1,'{search_term}') or "
            f"contains(companyname,'{search_term}'))"
        )

    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get("leads", params)
    leads = result.get("value", [])

    source_labels = {
        1: "Advertisement", 2: "Employee Referral", 3: "External Referral",
        4: "Partner", 5: "Public Relations", 6: "Seminar", 7: "Trade Show",
        8: "Web", 9: "Word of Mouth", 10: "Other",
    }
    status_labels = {0: "Open", 1: "Qualified", 2: "Disqualified"}

    return {
        "total_found": len(leads),
        "leads": [
            {
                "id": l.get("leadid"),
                "name": l.get("fullname", "No name"),
                "email": l.get("emailaddress1", ""),
                "phone": l.get("telephone1", ""),
                "job_title": l.get("jobtitle", ""),
                "company": l.get("companyname", ""),
                "subject": l.get("subject", ""),
                "source": source_labels.get(l.get("leadsourcecode"), "Unknown"),
                "status": status_labels.get(l.get("statecode"), "Unknown"),
                "owner": (l.get("ownerid") or {}).get("fullname", ""),
                "last_modified": l.get("modifiedon", ""),
            }
            for l in leads
        ],
    }


def get_lead_details(lead_id: str) -> dict:
    """
    Get all details for a specific lead.

    lead_id: the unique ID of the lead
    """
    params = {"$expand": "ownerid($select=fullname)"}
    l = crm_get(f"leads({lead_id})", params)

    status_labels = {0: "Open", 1: "Qualified", 2: "Disqualified"}

    return {
        "id": l.get("leadid"),
        "name": l.get("fullname", ""),
        "email": l.get("emailaddress1", ""),
        "phone": l.get("telephone1", ""),
        "mobile": l.get("mobilephone", ""),
        "job_title": l.get("jobtitle", ""),
        "company": l.get("companyname", ""),
        "subject": l.get("subject", ""),
        "description": l.get("description", ""),
        "status": status_labels.get(l.get("statecode"), "Unknown"),
        "owner": (l.get("ownerid") or {}).get("fullname", ""),
        "address": {
            "street": l.get("address1_line1", ""),
            "city": l.get("address1_city", ""),
            "state": l.get("address1_stateorprovince", ""),
            "zip": l.get("address1_postalcode", ""),
        },
        "created": l.get("createdon", ""),
        "last_modified": l.get("modifiedon", ""),
    }


def update_lead(lead_id: str, updates: dict) -> dict:
    """
    Update a lead's information.

    lead_id: the unique ID of the lead
    updates: fields to change, e.g.:
             {"emailaddress1": "new@email.com", "companyname": "Acme Corp"}

    Common fields:
      fullname        → full name
      emailaddress1   → email
      telephone1      → phone
      jobtitle        → job title
      companyname     → company name
      subject         → lead topic/subject
      description     → notes
    """
    crm_patch("leads", lead_id, updates)
    return {
        "success": True,
        "lead_id": lead_id,
        "fields_updated": list(updates.keys()),
        "message": f"Lead {lead_id} updated successfully",
    }


def qualify_lead(lead_id: str) -> dict:
    """
    Qualify a lead — marks it as qualified and creates a contact/opportunity.

    lead_id: the unique ID of the lead to qualify
    """
    payload = {
        "LeadId": {"leadid": lead_id, "@odata.type": "Microsoft.Dynamics.CRM.lead"},
        "Status": 3,  # Qualified
        "CreateContact": True,
        "CreateOpportunity": True,
        "CreateAccount": True,
    }
    result = crm_action("QualifyLead", payload)
    return {
        "success": True,
        "lead_id": lead_id,
        "message": "Lead qualified. Contact and opportunity created.",
        "result": result,
    }


def get_lead_summary() -> dict:
    """
    Get a high-level summary of all leads: counts by status and source.
    """
    params = {"$select": "leadid,statecode,leadsourcecode", "$top": 5000}
    leads = crm_get("leads", params).get("value", [])

    total        = len(leads)
    open_leads   = sum(1 for l in leads if l.get("statecode") == 0)
    qualified    = sum(1 for l in leads if l.get("statecode") == 1)
    disqualified = sum(1 for l in leads if l.get("statecode") == 2)

    source_labels = {
        1: "Advertisement", 2: "Employee Referral", 3: "External Referral",
        4: "Partner", 5: "Public Relations", 6: "Seminar", 7: "Trade Show",
        8: "Web", 9: "Word of Mouth", 10: "Other",
    }
    source_counts: dict = {}
    for l in leads:
        src = source_labels.get(l.get("leadsourcecode"), "Unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    top_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_leads": total,
        "open": open_leads,
        "qualified": qualified,
        "disqualified": disqualified,
        "top_sources": [{"source": s, "count": c} for s, c in top_sources],
    }


def find_stale_leads(days_inactive: int = 14) -> dict:
    """
    Find open leads that haven't been touched recently.

    days_inactive: days without activity to flag as stale (default 14)
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_inactive)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$top": 100,
        "$select": "leadid,fullname,emailaddress1,companyname,modifiedon",
        "$filter": f"statecode eq 0 and modifiedon le {cutoff}",
        "$orderby": "modifiedon asc",
        "$expand": "ownerid($select=fullname)",
    }

    result = crm_get("leads", params)
    leads = result.get("value", [])

    return {
        "days_inactive_threshold": days_inactive,
        "total_stale": len(leads),
        "message": f"Found {len(leads)} open leads not updated in {days_inactive}+ days",
        "leads": [
            {
                "id": l.get("leadid"),
                "name": l.get("fullname", ""),
                "email": l.get("emailaddress1", ""),
                "company": l.get("companyname", ""),
                "last_modified": l.get("modifiedon", ""),
                "owner": (l.get("ownerid") or {}).get("fullname", ""),
            }
            for l in leads
        ],
    }
