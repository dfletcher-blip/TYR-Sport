# ============================================================
# tools/security.py — Security Roles & User Management Tools
# ============================================================
# Security roles control what each user can see and do in
# Dynamics 365. Getting this right is critical — too much
# access is a compliance risk, too little breaks workflows.
#
# This covers:
#   - Listing security roles and what they allow
#   - Viewing users and their assigned roles
#   - Assigning or removing roles from users
#   - Finding users with no roles, disabled users, and
#     users with unusually broad access
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


# ── SECURITY ROLES ───────────────────────────────────────────


def list_security_roles(limit: int = 100) -> dict:
    """
    List all security roles defined in this Dynamics 365 org.

    limit: max number of roles to return (default 100)

    Returns all roles with their names and business unit.
    """
    params = {
        "$top": limit,
        "$select": "roleid,name,createdon,modifiedon",
        "$orderby": "name asc",
    }

    result = crm_get("roles", params)
    roles = result.get("value", [])

    return {
        "total_roles": len(roles),
        "roles": [
            {
                "id":            r.get("roleid"),
                "name":          r.get("name", "Unnamed"),
                "created":       r.get("createdon", ""),
                "last_modified": r.get("modifiedon", ""),
            }
            for r in roles
        ],
    }


def get_role_details(role_id: str) -> dict:
    """
    Get details about a specific security role.

    role_id: the ID of the security role

    Returns the role name, business unit, and which users have it.
    """
    params = {
        "$select": "roleid,name,createdon,modifiedon",
        "$expand": "systemuserroles_association($select=fullname,systemuserid,internalemailaddress,isdisabled;$top=100)",
    }

    result = crm_get(f"roles({role_id})", params)

    users_with_role = result.get("systemuserroles_association", [])

    return {
        "id":      result.get("roleid"),
        "name":    result.get("name", "Unnamed"),
        "created": result.get("createdon", ""),
        "total_users_assigned": len(users_with_role),
        "users": [
            {
                "id":       u.get("systemuserid"),
                "name":     u.get("fullname", "Unknown"),
                "email":    u.get("internalemailaddress", ""),
                "disabled": u.get("isdisabled", False),
            }
            for u in users_with_role
        ],
    }


def search_roles(search_term: str) -> dict:
    """
    Search for security roles by name.

    search_term: part of the role name to search for

    Returns matching roles.
    """
    params = {
        "$top": 50,
        "$select": "roleid,name",
        "$filter": f"contains(name,'{search_term}')",
        "$orderby": "name asc",
    }

    result = crm_get("roles", params)
    roles = result.get("value", [])

    return {
        "search_term": search_term,
        "total_found": len(roles),
        "roles": [
            {"id": r.get("roleid"), "name": r.get("name", "Unnamed")}
            for r in roles
        ],
    }


# ── USERS ────────────────────────────────────────────────────


def list_users(status: str = "active", limit: int = 100) -> dict:
    """
    List users in the Dynamics 365 org.

    status: "active"   → only enabled/active users
            "disabled" → only disabled/deactivated users
            "all"      → everyone including service accounts

    limit: max number of users to return (default 100)

    Returns users with their names, emails, and access info.
    """
    params = {
        "$top": limit,
        "$select": "systemuserid,fullname,internalemailaddress,domainname,isdisabled,createdon,accessmode",
        "$orderby": "fullname asc",
    }

    if status == "active":
        params["$filter"] = "isdisabled eq false"
    elif status == "disabled":
        params["$filter"] = "isdisabled eq true"

    result = crm_get("systemusers", params)
    users = result.get("value", [])

    access_mode_map = {
        0: "Read-Write",
        1: "Administrative",
        2: "Read",
        3: "Support User",
        4: "Non-interactive",
        5: "Delegated Admin",
    }

    return {
        "total_users": len(users),
        "status_filter": status,
        "users": [
            {
                "id":          u.get("systemuserid"),
                "name":        u.get("fullname", "Unknown"),
                "email":       u.get("internalemailaddress", ""),
                "username":    u.get("domainname", ""),
                "disabled":    u.get("isdisabled", False),
                "access_mode": access_mode_map.get(u.get("accessmode", 0), "Unknown"),
                "created":     u.get("createdon", ""),
            }
            for u in users
        ],
    }


def get_user_details(user_id: str) -> dict:
    """
    Get full details for a specific user, including their assigned roles.

    user_id: the ID of the user (systemuserid)

    Returns the user's profile and every security role they have.
    """
    params = {
        "$select": "systemuserid,fullname,internalemailaddress,domainname,isdisabled,createdon,accessmode,businessunitid",
        "$expand": "systemuserroles_association($select=roleid,name)",
    }

    result = crm_get(f"systemusers({user_id})", params)

    roles = result.get("systemuserroles_association", [])
    access_mode_map = {
        0: "Read-Write",
        1: "Administrative",
        2: "Read",
        3: "Support User",
        4: "Non-interactive",
        5: "Delegated Admin",
    }

    return {
        "id":          result.get("systemuserid"),
        "name":        result.get("fullname", "Unknown"),
        "email":       result.get("internalemailaddress", ""),
        "username":    result.get("domainname", ""),
        "disabled":    result.get("isdisabled", False),
        "access_mode": access_mode_map.get(result.get("accessmode", 0), "Unknown"),
        "created":     result.get("createdon", ""),
        "total_roles": len(roles),
        "roles": [{"id": r.get("roleid"), "name": r.get("name", "Unnamed")} for r in roles],
    }


def search_users(search_term: str) -> dict:
    """
    Search for users by name or email.

    search_term: part of the name or email to search for

    Returns matching users.
    """
    params = {
        "$top": 50,
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,accessmode",
        "$filter": (
            f"contains(fullname,'{search_term}') or "
            f"contains(internalemailaddress,'{search_term}') or "
            f"contains(domainname,'{search_term}')"
        ),
        "$orderby": "fullname asc",
    }

    result = crm_get("systemusers", params)
    users = result.get("value", [])

    return {
        "search_term": search_term,
        "total_found": len(users),
        "users": [
            {
                "id":       u.get("systemuserid"),
                "name":     u.get("fullname", "Unknown"),
                "email":    u.get("internalemailaddress", ""),
                "disabled": u.get("isdisabled", False),
            }
            for u in users
        ],
    }


def assign_role_to_user(user_id: str, role_id: str) -> dict:
    """
    Assign a security role to a user.

    user_id: the ID of the user to give the role to
    role_id: the ID of the security role to assign

    Returns confirmation that the role was assigned.
    WARNING: This changes what the user can access in the CRM.
    Confirm the correct role ID before assigning.
    """
    # Dynamics 365 uses a $ref association to link roles to users
    data = {
        "@odata.id": f"{crm_get.__module__}"  # placeholder — built dynamically below
    }

    # We need the DYNAMICS_URL to build the reference URL
    from config.crm_connection import DYNAMICS_URL
    ref_url = f"{DYNAMICS_URL}/api/data/v9.2/roles({role_id})"

    import requests
    from config.crm_connection import get_access_token

    token = get_access_token()
    url = f"{DYNAMICS_URL}/api/data/v9.2/systemusers({user_id})/systemuserroles_association/$ref"
    headers = {
        "Authorization":  f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version":  "4.0",
        "Content-Type":   "application/json",
    }
    body = {"@odata.id": ref_url}

    response = requests.post(url, headers=headers, json=body)

    if response.status_code in (204, 200):
        return {"assigned": True, "user_id": user_id, "role_id": role_id}
    else:
        raise RuntimeError(
            f"Failed to assign role ({response.status_code}): {response.text[:300]}"
        )


def remove_role_from_user(user_id: str, role_id: str) -> dict:
    """
    Remove a security role from a user.

    user_id: the ID of the user
    role_id: the ID of the security role to remove

    Returns confirmation that the role was removed.
    WARNING: This reduces what the user can do in the CRM.
    """
    from config.crm_connection import DYNAMICS_URL, get_access_token
    import requests

    token = get_access_token()
    url = (
        f"{DYNAMICS_URL}/api/data/v9.2/systemusers({user_id})"
        f"/systemuserroles_association({role_id})/$ref"
    )
    headers = {
        "Authorization":  f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version":  "4.0",
    }

    response = requests.delete(url, headers=headers)

    if response.status_code in (204, 200):
        return {"removed": True, "user_id": user_id, "role_id": role_id}
    else:
        raise RuntimeError(
            f"Failed to remove role ({response.status_code}): {response.text[:300]}"
        )


# ── SECURITY AUDIT ───────────────────────────────────────────


def get_users_with_no_roles() -> dict:
    """
    Find users who have no security roles assigned.

    Users with no roles typically can't do anything useful in the CRM.
    This often indicates onboarding that wasn't completed.

    Returns a list of users who need roles assigned.
    """
    params = {
        "$top": 200,
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,createdon",
        "$filter": "isdisabled eq false",
        "$expand": "systemuserroles_association($select=roleid;$top=1)",
    }

    result = crm_get("systemusers", params)
    users = result.get("value", [])

    no_roles = [
        u for u in users
        if not u.get("systemuserroles_association")
    ]

    return {
        "total_active_users": len(users),
        "users_with_no_roles": len(no_roles),
        "users": [
            {
                "id":      u.get("systemuserid"),
                "name":    u.get("fullname", "Unknown"),
                "email":   u.get("internalemailaddress", ""),
                "created": u.get("createdon", ""),
            }
            for u in no_roles
        ],
    }


def get_admin_users() -> dict:
    """
    Find all users with System Administrator access.

    System Administrator is the highest privilege role in Dynamics 365.
    Keeping this list small and reviewed is a security best practice.

    Returns all users with admin-level access.
    """
    # First find the System Administrator role ID
    role_result = crm_get("roles", {
        "$top": 5,
        "$select": "roleid,name",
        "$filter": "name eq 'System Administrator'",
    })

    roles = role_result.get("value", [])
    if not roles:
        return {"error": "System Administrator role not found in this org."}

    admin_role_id = roles[0]["roleid"]

    # Get all users with that role
    details = get_role_details(admin_role_id)

    active_admins   = [u for u in details.get("users", []) if not u.get("disabled")]
    disabled_admins = [u for u in details.get("users", []) if u.get("disabled")]

    return {
        "role_name":       "System Administrator",
        "role_id":         admin_role_id,
        "total_admins":    len(details.get("users", [])),
        "active_admins":   len(active_admins),
        "disabled_admins": len(disabled_admins),
        "recommendation": (
            "Admin count looks reasonable."
            if len(active_admins) <= 5
            else f"Warning: {len(active_admins)} active admins is high. Review and reduce where possible."
        ),
        "active_admin_users":   active_admins,
        "disabled_admin_users": disabled_admins,
    }


def get_security_summary() -> dict:
    """
    Get a high-level security overview of the Dynamics 365 org.

    Returns key counts and flags for a quick security health check —
    total users, admins, disabled accounts, and role coverage.
    """
    # Active users
    active = crm_get("systemusers", {
        "$top": 1,
        "$select": "systemuserid",
        "$filter": "isdisabled eq false",
        "$count": "true",
    })
    active_count = active.get("@odata.count", len(active.get("value", [])))

    # Disabled users
    disabled = crm_get("systemusers", {
        "$top": 1,
        "$select": "systemuserid",
        "$filter": "isdisabled eq true",
        "$count": "true",
    })
    disabled_count = disabled.get("@odata.count", len(disabled.get("value", [])))

    # Total roles
    roles = crm_get("roles", {
        "$top": 1,
        "$select": "roleid",
        "$count": "true",
    })
    role_count = roles.get("@odata.count", len(roles.get("value", [])))

    return {
        "active_users":    active_count,
        "disabled_users":  disabled_count,
        "total_users":     active_count + disabled_count,
        "total_roles":     role_count,
        "actions_to_take": [
            "Run get_admin_users() to review who has System Administrator access",
            "Run get_users_with_no_roles() to find users who can't do anything",
            "Review disabled users — remove their licenses if they've left the company",
        ],
    }
