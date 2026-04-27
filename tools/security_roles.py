# ============================================================
# tools/security_roles.py — Security Role Management
# ============================================================
# Find CRM users, inspect their security roles, and assign or
# remove roles to control what they can see and do in Dynamics 365.
#
# In Dynamics 365, chart and dashboard visibility is controlled by
# security roles. Users must have a role that grants at least Read
# access to the entities displayed on each dashboard/chart.
# The standard "Salesperson" role covers the most common cases.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
from config.crm_connection import get_access_token, crm_get, DYNAMICS_URL


# ── User lookup ────────────────────────────────────────────────────────────────

def find_crm_user(name: str) -> dict:
    """
    Find a Dynamics 365 system user by full name (or partial name).

    name: full or partial name, e.g. "Michael Gallindo" or "gallindo"

    Returns a dict with matching users and their IDs, or an error.
    """
    params = {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,accessmode",
        "$filter": f"contains(tolower(fullname), '{name.lower()}')",
        "$top": 10,
    }
    result = crm_get("systemusers", params)
    users = result.get("value", [])

    access_labels = {0: "Read-Write", 1: "Administrative", 2: "Read", 3: "Support User", 4: "Non-Interactive", 5: "Delegated Admin"}

    return {
        "count": len(users),
        "users": [
            {
                "user_id": u.get("systemuserid"),
                "name": u.get("fullname"),
                "email": u.get("internalemailaddress"),
                "disabled": u.get("isdisabled", False),
                "access_mode": access_labels.get(u.get("accessmode", 0), "Unknown"),
            }
            for u in users
        ],
    }


# ── Role inspection ────────────────────────────────────────────────────────────

def get_user_security_roles(user_id: str) -> dict:
    """
    List all security roles currently assigned to a specific user.

    user_id: the systemuserid GUID of the user
    """
    params = {
        "$select": "systemuserid,fullname",
        "$expand": "systemuserroles_association($select=roleid,name,description)",
    }
    result = crm_get(f"systemusers({user_id})", params)

    roles = result.get("systemuserroles_association", [])
    return {
        "user_id": user_id,
        "user_name": result.get("fullname"),
        "role_count": len(roles),
        "roles": [
            {
                "role_id": r.get("roleid"),
                "name": r.get("name"),
                "description": r.get("description", ""),
            }
            for r in roles
        ],
    }


def list_security_roles(search_term: str = "") -> dict:
    """
    List security roles available in the CRM.

    search_term: optional filter by role name (leave blank for all roles)

    Returns active roles with their IDs and names.
    """
    params = {
        "$select": "roleid,name,description",
        "$filter": "statecode eq 0",  # active roles only
        "$orderby": "name asc",
        "$top": 100,
    }
    if search_term:
        params["$filter"] += f" and contains(tolower(name), '{search_term.lower()}')"

    result = crm_get("roles", params)
    roles = result.get("value", [])

    return {
        "count": len(roles),
        "roles": [
            {
                "role_id": r.get("roleid"),
                "name": r.get("name"),
                "description": (r.get("description") or "")[:120],
            }
            for r in roles
        ],
    }


# ── Role assignment ────────────────────────────────────────────────────────────

def assign_security_role(user_id: str, role_id: str) -> dict:
    """
    Assign a security role to a user.

    user_id: the systemuserid GUID of the user
    role_id: the roleid GUID of the role to assign

    Uses the OData $ref association pattern required by Dynamics 365.
    Safe to call if the user already has the role — Dynamics will ignore duplicates.
    """
    token = get_access_token()
    url = f"{DYNAMICS_URL}/api/data/v9.2/systemusers({user_id})/systemuserroles_association/$ref"
    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/roles({role_id})"}

    response = requests.post(url, headers=headers, json=body)

    if response.status_code in (204, 200):
        return {"success": True, "message": f"Role assigned successfully to user {user_id}"}

    if response.status_code == 400 and "duplicate" in response.text.lower():
        return {"success": True, "already_assigned": True, "message": "User already has this role"}

    raise RuntimeError(
        f"Failed to assign role ({response.status_code}): {response.text[:400]}"
    )


def remove_security_role(user_id: str, role_id: str) -> dict:
    """
    Remove a security role from a user.

    user_id: the systemuserid GUID of the user
    role_id: the roleid GUID of the role to remove

    Use with care — removing roles may prevent the user from accessing CRM data.
    """
    token = get_access_token()
    url = (
        f"{DYNAMICS_URL}/api/data/v9.2/systemusers({user_id})"
        f"/systemuserroles_association({role_id})/$ref"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }

    response = requests.delete(url, headers=headers)

    if response.status_code in (204, 200):
        return {"success": True, "message": f"Role removed from user {user_id}"}

    raise RuntimeError(
        f"Failed to remove role ({response.status_code}): {response.text[:400]}"
    )


# ── Dashboard / chart access audit ────────────────────────────────────────────

def check_dashboard_access(user_id: str) -> dict:
    """
    Check whether a user has the security roles typically required to view
    charts and dashboards in Dynamics 365.

    Inspects the user's current roles and flags whether any of them are known
    to include dashboard and chart read privileges (prvReadUserDashboard,
    prvReadVisualization). Also lists roles that are likely missing.

    Returns a summary with a recommended action if access is insufficient.
    """
    role_result = get_user_security_roles(user_id)
    assigned_names = {r["name"].lower() for r in role_result["roles"]}

    # Standard D365 roles that include dashboard + chart read access
    dashboard_capable_roles = {
        "salesperson",
        "sales manager",
        "marketing",
        "marketing manager",
        "marketing professional",
        "customer service representative",
        "customer service manager",
        "system administrator",
        "system customizer",
        "vice president of marketing",
        "vice president of sales",
    }

    has_dashboard_role = bool(assigned_names & dashboard_capable_roles)
    has_admin = "system administrator" in assigned_names

    # Look for the Salesperson role in the CRM (most common baseline role)
    salesperson_role = None
    try:
        roles_result = list_security_roles("salesperson")
        for r in roles_result["roles"]:
            if r["name"].lower() == "salesperson":
                salesperson_role = r
                break
    except Exception:
        pass

    return {
        "user_id": user_id,
        "user_name": role_result.get("user_name"),
        "current_roles": role_result["roles"],
        "role_count": role_result["role_count"],
        "has_dashboard_capable_role": has_dashboard_role,
        "has_admin_access": has_admin,
        "recommended_role": salesperson_role,
        "assessment": (
            "User has at least one role that should grant dashboard and chart access."
            if has_dashboard_role
            else "User does not appear to have a role that grants dashboard/chart read access. "
                 "Assigning the 'Salesperson' role is the standard fix."
        ),
    }
