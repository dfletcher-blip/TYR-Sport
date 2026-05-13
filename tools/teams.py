# ============================================================
# tools/teams.py — Team Management
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post, crm_delete


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

    # Get team members — fetch IDs first, then look up each user for email
    members_result = crm_get(f"teams({team_id})/teammembership_association", {
        "$select": "fullname,jobtitle,systemuserid",
        "$top": 200,
    })
    raw_members = members_result.get("value", [])

    # Enrich with email by querying each user individually
    members = []
    for m in raw_members:
        uid = m.get("systemuserid", "")
        email = ""
        if uid:
            try:
                user_detail = crm_get(f"systemusers({uid})", {
                    "$select": "internalemailaddress,domainname",
                })
                email = user_detail.get("internalemailaddress") or user_detail.get("domainname", "")
            except Exception:
                pass
        members.append({
            "name": m.get("fullname", ""),
            "id": uid,
            "title": m.get("jobtitle", ""),
            "email": email,
        })


def add_team_member(team_name: str, user_name: str) -> dict:
    """
    Add a user to a team.

    team_name: full or partial name of the team (e.g. "Finance")
    user_name: full or partial name of the user to add (e.g. "Jaaber Saidi")
    """
    import os

    # Find the team
    teams = crm_get("teams", {
        "$select": "teamid,name",
        "$filter": f"contains(name,'{team_name}')",
        "$top": 5,
    }).get("value", [])

    if not teams:
        return {"error": f"No team found matching '{team_name}'"}
    if len(teams) > 1:
        names = [t["name"] for t in teams]
        exact = [t for t in teams if t["name"].lower() == team_name.lower()]
        teams = exact if exact else teams[:1]
        if len(teams) > 1:
            return {"error": f"Multiple teams match '{team_name}': {names}. Use a more specific name."}

    team = teams[0]
    team_id = team["teamid"]

    # Find the user
    users = crm_get("systemusers", {
        "$select": "systemuserid,fullname",
        "$filter": f"contains(fullname,'{user_name}') and isdisabled eq false",
        "$top": 3,
    }).get("value", [])

    if not users:
        return {"error": f"No active user found matching '{user_name}'"}
    if len(users) > 1:
        return {"error": f"Multiple users match '{user_name}': {[u['fullname'] for u in users]}. Use a more specific name."}

    user = users[0]
    user_id = user["systemuserid"]

    dynamics_url = os.getenv("DYNAMICS_URL", "").rstrip("/")
    crm_post(
        f"teams({team_id})/teammembership_association/$ref",
        {"@odata.id": f"{dynamics_url}/api/data/v9.2/systemusers({user_id})"},
    )

    return {
        "success": True,
        "message": f"{user['fullname']} has been added to the '{team['name']}' team.",
        "team_id": team_id,
        "user_id": user_id,
    }


def remove_team_member(team_name: str, user_name: str) -> dict:
    """
    Remove a user from a team.

    team_name: full or partial name of the team
    user_name: full or partial name of the user to remove
    """
    # Find team
    teams = crm_get("teams", {
        "$select": "teamid,name",
        "$filter": f"contains(name,'{team_name}')",
        "$top": 5,
    }).get("value", [])

    if not teams:
        return {"error": f"No team found matching '{team_name}'"}
    exact = [t for t in teams if t["name"].lower() == team_name.lower()]
    team = exact[0] if exact else teams[0]
    team_id = team["teamid"]

    # Find user
    users = crm_get("systemusers", {
        "$select": "systemuserid,fullname",
        "$filter": f"contains(fullname,'{user_name}') and isdisabled eq false",
        "$top": 3,
    }).get("value", [])

    if not users:
        return {"error": f"No active user found matching '{user_name}'"}
    if len(users) > 1:
        return {"error": f"Multiple users match '{user_name}': {[u['fullname'] for u in users]}"}

    user = users[0]
    user_id = user["systemuserid"]

    crm_delete(f"teams({team_id})/teammembership_association({user_id})")

    return {
        "success": True,
        "message": f"{user['fullname']} has been removed from the '{team['name']}' team.",
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
