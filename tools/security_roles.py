# ============================================================
# tools/security_roles.py — User Security Role Management
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_post, crm_delete


def get_user_security_roles(user_name: str) -> dict:
    """
    Get the security roles assigned to a CRM user.

    user_name: full or partial name of the user (e.g. "Jennifer Brandow")
    """
    # Find the user
    users = crm_get("systemusers", {
        "$select": "systemuserid,fullname,domainname,isdisabled",
        "$filter": f"contains(fullname,'{user_name}') and isdisabled eq false",
        "$top": 5,
    }).get("value", [])

    if not users:
        return {"error": f"No active user found matching '{user_name}'"}

    results = []
    for user in users:
        uid = user["systemuserid"]
        roles_resp = crm_get(f"systemusers({uid})/systemuserroles_association", {
            "$select": "roleid,name,businessunitid",
        })
        roles = roles_resp.get("value", [])
        results.append({
            "user_id": uid,
            "full_name": user.get("fullname"),
            "domain": user.get("domainname"),
            "roles": [{"role_id": r["roleid"], "name": r.get("name", "")} for r in roles],
            "role_count": len(roles),
        })

    return {"users_found": len(results), "results": results}


def compare_user_roles(user_a: str, user_b: str) -> dict:
    """
    Compare security roles between two users and show what's different.
    Useful for diagnosing why one user can't access something another can.

    user_a: name of first user (e.g. the one with the problem)
    user_b: name of second user (e.g. a working user to compare against)
    """
    result_a = get_user_security_roles(user_a)
    result_b = get_user_security_roles(user_b)

    if "error" in result_a:
        return {"error": f"User A ({user_a}): {result_a['error']}"}
    if "error" in result_b:
        return {"error": f"User B ({user_b}): {result_b['error']}"}

    roles_a = {r["name"] for r in result_a["results"][0]["roles"]}
    roles_b = {r["name"] for r in result_b["results"][0]["roles"]}

    return {
        user_a: sorted(roles_a),
        user_b: sorted(roles_b),
        "missing_from_" + user_a.split()[0]: sorted(roles_b - roles_a),
        "extra_in_" + user_a.split()[0]: sorted(roles_a - roles_b),
        "shared_roles": sorted(roles_a & roles_b),
    }


def assign_role_to_user(user_name: str, role_name: str) -> dict:
    """
    Assign a security role to a user.

    user_name: full or partial name of the user (e.g. "Jennifer Brandow")
    role_name: exact or partial name of the role to assign (e.g. "Salesperson")
    """
    # Find user
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
    uid = user["systemuserid"]

    # Find role
    roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": f"contains(name,'{role_name}')",
        "$top": 5,
    }).get("value", [])

    if not roles:
        return {"error": f"No role found matching '{role_name}'"}
    if len(roles) > 1:
        names = [r["name"] for r in roles]
        # Prefer exact match
        exact = [r for r in roles if r["name"].lower() == role_name.lower()]
        if exact:
            roles = exact
        else:
            return {"error": f"Multiple roles match '{role_name}': {names}. Use the exact name."}

    role = roles[0]
    rid = role["roleid"]

    # Check if already assigned
    existing = crm_get(f"systemusers({uid})/systemuserroles_association", {
        "$select": "roleid",
        "$filter": f"roleid eq {rid}",
    }).get("value", [])

    if existing:
        return {
            "success": True,
            "message": f"'{role['name']}' is already assigned to {user['fullname']} — no change needed.",
        }

    # Assign the role
    dynamics_url = os.getenv("DYNAMICS_URL", "").rstrip("/")
    crm_post(
        f"systemusers({uid})/systemuserroles_association/$ref",
        {"@odata.id": f"{dynamics_url}/api/data/v9.2/roles({rid})"},
    )

    return {
        "success": True,
        "message": f"Role '{role['name']}' successfully assigned to {user['fullname']}.",
        "user_id": uid,
        "role_id": rid,
    }


def remove_role_from_user(user_name: str, role_name: str) -> dict:
    """
    Remove a security role from a user.

    user_name: full or partial name of the user
    role_name: exact or partial name of the role to remove
    """
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
    uid = user["systemuserid"]

    roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": f"contains(name,'{role_name}')",
        "$top": 5,
    }).get("value", [])

    if not roles:
        return {"error": f"No role found matching '{role_name}'"}

    exact = [r for r in roles if r["name"].lower() == role_name.lower()]
    role = exact[0] if exact else roles[0]
    rid = role["roleid"]

    crm_delete(f"systemusers({uid})/systemuserroles_association({rid})")

    return {
        "success": True,
        "message": f"Role '{role['name']}' removed from {user['fullname']}.",
    }


def list_available_roles() -> dict:
    """
    List all security roles available in the CRM.
    """
    roles = crm_get("roles", {
        "$select": "roleid,name,businessunitid",
        "$orderby": "name asc",
        "$top": 200,
    }).get("value", [])

    return {
        "total_roles": len(roles),
        "roles": [{"id": r["roleid"], "name": r.get("name", "")} for r in roles],
    }
