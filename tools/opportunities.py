# ============================================================
# tools/opportunities.py — Opportunity / Deal Management
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


def search_opportunities(search_term: str = "", status: str = "open", limit: int = 50) -> dict:
    """
    Search for opportunities/deals in the CRM.

    search_term: name or account name to search for (leave blank to get all)
    status: "open", "won", "lost", or "all"
    limit: max results to return (default 50)
    """
    status_filter = {
        "open": "statecode eq 0",
        "won":  "statecode eq 1",
        "lost": "statecode eq 2",
        "all":  None,
    }.get(status.lower(), "statecode eq 0")

    params = {
        "$top": limit,
        "$select": "opportunityid,name,estimatedvalue,closeprobability,estimatedclosedate,statecode,statuscode,createdon,modifiedon,_ownerid_value",
        "$expand": "customerid_account($select=name)",
        "$orderby": "modifiedon desc",
    }

    filters = []
    if status_filter:
        filters.append(status_filter)
    if search_term:
        filters.append(f"contains(name,'{search_term}')")

    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get("opportunities", params)
    opps = result.get("value", [])

    status_labels = {0: "Open", 1: "Won", 2: "Lost"}

    return {
        "total_found": len(opps),
        "opportunities": [
            {
                "id": o.get("opportunityid"),
                "name": o.get("name", "Unnamed"),
                "value": o.get("estimatedvalue"),
                "close_probability": f"{o.get('closeprobability', 0)}%",
                "estimated_close": o.get("estimatedclosedate", ""),
                "status": status_labels.get(o.get("statecode"), "Unknown"),
                "account": (o.get("customerid_account") or {}).get("name", ""),
                "owner": o.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", ""),
                "last_modified": o.get("modifiedon", ""),
            }
            for o in opps
        ],
    }


def get_opportunity_details(opportunity_id: str) -> dict:
    """
    Get all details for a specific opportunity.

    opportunity_id: the unique ID of the opportunity
    """
    params = {
        "$expand": "customerid_account($select=name)",
    }
    o = crm_get(f"opportunities({opportunity_id})", params)

    status_labels = {0: "Open", 1: "Won", 2: "Lost"}

    return {
        "id": o.get("opportunityid"),
        "name": o.get("name", ""),
        "description": o.get("description", ""),
        "value": o.get("estimatedvalue"),
        "actual_value": o.get("actualvalue"),
        "close_probability": f"{o.get('closeprobability', 0)}%",
        "estimated_close": o.get("estimatedclosedate", ""),
        "actual_close": o.get("actualclosedate", ""),
        "status": status_labels.get(o.get("statecode"), "Unknown"),
        "account": (o.get("customerid_account") or {}).get("name", ""),
        "owner": (o.get("ownerid") or {}).get("fullname", ""),
        "created": o.get("createdon", ""),
        "last_modified": o.get("modifiedon", ""),
    }


def update_opportunity(opportunity_id: str, updates: dict) -> dict:
    """
    Update an opportunity's fields.

    opportunity_id: the unique ID of the opportunity
    updates: fields to change, e.g.:
             {"name": "New Name", "estimatedvalue": 50000, "closeprobability": 75}

    Common fields:
      name                 → opportunity name
      estimatedvalue       → estimated deal value
      closeprobability     → % chance of closing (0-100)
      estimatedclosedate   → expected close date (YYYY-MM-DD)
      description          → notes
    """
    crm_patch("opportunities", opportunity_id, updates)
    return {
        "success": True,
        "opportunity_id": opportunity_id,
        "fields_updated": list(updates.keys()),
        "message": f"Opportunity {opportunity_id} updated successfully",
    }


def get_opportunity_summary() -> dict:
    """
    Get a high-level summary of all opportunities: pipeline value, win rate, stage breakdown.
    """
    params_all  = {"$select": "opportunityid,statecode,estimatedvalue,actualvalue", "$top": 5000}
    opps = crm_get("opportunities", params_all).get("value", [])

    total  = len(opps)
    open_  = [o for o in opps if o.get("statecode") == 0]
    won    = [o for o in opps if o.get("statecode") == 1]
    lost   = [o for o in opps if o.get("statecode") == 2]

    pipeline_value = sum(o.get("estimatedvalue") or 0 for o in open_)
    won_value      = sum(o.get("actualvalue") or 0 for o in won)
    closed         = len(won) + len(lost)
    win_rate       = f"{len(won)/closed*100:.1f}%" if closed else "N/A"

    return {
        "total_opportunities": total,
        "open": len(open_),
        "won": len(won),
        "lost": len(lost),
        "pipeline_value": pipeline_value,
        "won_value": won_value,
        "win_rate": win_rate,
    }


def find_stalled_opportunities(days_inactive: int = 30) -> dict:
    """
    Find open opportunities that haven't been updated recently.

    days_inactive: number of days without activity to consider stalled (default 30)
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_inactive)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$top": 100,
        "$select": "opportunityid,name,estimatedvalue,estimatedclosedate,modifiedon,_ownerid_value",
        "$filter": f"statecode eq 0 and modifiedon le {cutoff}",
        "$orderby": "modifiedon asc",
    }

    result = crm_get("opportunities", params)
    opps = result.get("value", [])

    return {
        "days_inactive_threshold": days_inactive,
        "total_stalled": len(opps),
        "message": f"Found {len(opps)} open opportunities not updated in {days_inactive}+ days",
        "opportunities": [
            {
                "id": o.get("opportunityid"),
                "name": o.get("name", ""),
                "value": o.get("estimatedvalue"),
                "estimated_close": o.get("estimatedclosedate", ""),
                "last_modified": o.get("modifiedon", ""),
                "owner": o.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", ""),
            }
            for o in opps
        ],
    }
