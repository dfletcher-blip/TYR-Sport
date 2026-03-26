# ============================================================
# tools/teams.py — Team Management
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


def list_teams(team_type: str = "all") -> dict:
    """
    List all teams in the CRM.

    team_type: "owner" (owning teams), "access" (access teams), or "all"
    """
    type_filter = {
        "owner":  "teamtype eq 0",
        "access": "teamtype eq 1",
        "all":    None,
    }.get(team_type.lower(), None)

    params = {
        "$top": 100,
        "$select": "teamid,name,description,teamtype,createdon,modifiedon",
        "$expand": "businessunitid($select=name)",
        "$orderby": "name asc",
    }

    if type_filter:
        params["$filter"] = type_filter

    result = crm_get("teams", params)
    teams = result.get("value", [])

    type_labels = {0: "Owner", 1: "Access", 2: "AAD Security Group", 3: "AAD Office Group"}

    return {
        "total_found": len(teams),
        "teams": [
            {
                "id": t.get("teamid"),
                "name": t.get("name", "Unnamed"),
                "description": t.get("description", ""),
                "type": type_labels.get(t.get("teamtype"), "Unknown"),
                "business_unit": (t.get("businessunitid") or {}).get("name", ""),
                "created": t.get("createdon", ""),
            }
            for t in teams
        ],
    }


def get_team_details(team_id: str) -> dict:
    """
    Get full details for a team, including its members.

    team_id: the unique ID of the team
    """
    params = {"$expand": "businessunitid($select=name)"}
    t = crm_get(f"teams({team_id})", params)

    # Get team members
    members_result = crm_get(f"teams({team_id})/teammembership_association", {
        "$select": "fullname,emailaddress1,jobtitle",
        "$top": 200,
    })
    members = members_result.get("value", [])

    type_labels = {0: "Owner", 1: "Access", 2: "AAD Security Group", 3: "AAD Office Group"}

    return {
        "id": t.get("teamid"),
        "name": t.get("name", ""),
        "description": t.get("description", ""),
        "type": type_labels.get(t.get("teamtype"), "Unknown"),
        "business_unit": (t.get("businessunitid") or {}).get("name", ""),
        "created": t.get("createdon", ""),
        "last_modified": t.get("modifiedon", ""),
        "member_count": len(members),
        "members": [
            {
                "name": m.get("fullname", ""),
                "email": m.get("emailaddress1", ""),
                "title": m.get("jobtitle", ""),
            }
            for m in members
        ],
    }


def search_teams(search_term: str) -> dict:
    """
    Search for teams by name.

    search_term: part of the team name to search for
    """
    params = {
        "$top": 50,
        "$select": "teamid,name,description,teamtype",
        "$filter": f"contains(name,'{search_term}')",
        "$orderby": "name asc",
        "$expand": "businessunitid($select=name)",
    }

    result = crm_get("teams", params)
    teams = result.get("value", [])

    type_labels = {0: "Owner", 1: "Access", 2: "AAD Security Group", 3: "AAD Office Group"}

    return {
        "total_found": len(teams),
        "teams": [
            {
                "id": t.get("teamid"),
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "type": type_labels.get(t.get("teamtype"), "Unknown"),
                "business_unit": (t.get("businessunitid") or {}).get("name", ""),
            }
            for t in teams
        ],
    }


def get_team_summary() -> dict:
    """
    Get a summary of all teams: counts by type and business unit.
    """
    params = {"$select": "teamid,teamtype", "$expand": "businessunitid($select=name)", "$top": 500}
    teams = crm_get("teams", params).get("value", [])

    total  = len(teams)
    owner  = sum(1 for t in teams if t.get("teamtype") == 0)
    access = sum(1 for t in teams if t.get("teamtype") == 1)

    bu_counts: dict = {}
    for t in teams:
        bu = (t.get("businessunitid") or {}).get("name", "Unknown") or "Unknown"
        bu_counts[bu] = bu_counts.get(bu, 0) + 1
    top_bus = sorted(bu_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_teams": total,
        "owner_teams": owner,
        "access_teams": access,
        "teams_by_business_unit": [{"business_unit": bu, "count": c} for bu, c in top_bus],
    }
