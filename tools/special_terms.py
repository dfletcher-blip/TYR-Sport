# ============================================================
# tools/special_terms.py — Special Terms (STR) Management
# ============================================================
# Special Terms Requirements (STR) are discount/pricing approval
# records that require two levels of sign-off:
#   1. Sales Leadership
#   2. Finance
#
# Entity display name: "Special Terms"
# Record format: ST-YYYYMM-NNNNN
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


# ── Entity name discovery ─────────────────────────────────────
# Dynamics custom entities have a publisher prefix (e.g. tyr_, cr_).
# We try common patterns and cache the one that works.
_STR_ENTITY = None

def _get_str_entity() -> str:
    """Return the API entity collection name for Special Terms, auto-discovering if needed."""
    global _STR_ENTITY
    if _STR_ENTITY:
        return _STR_ENTITY

    candidates = [
        "tyr_specialterms",
        "tyr_specialterm",
        "cr_specialterms",
        "cr_specialterm",
        "new_specialterms",
        "new_specialterm",
        "tyr_strs",
        "tyr_str",
    ]

    for name in candidates:
        try:
            result = crm_get(name, {"$top": 1, "$select": "createdon"})
            if "value" in result:
                _STR_ENTITY = name
                return name
        except Exception:
            continue

    # Fall back to metadata search
    try:
        meta = crm_get("EntityDefinitions", {
            "$filter": "contains(tolower(DisplayName/LocalizedLabels/Label),'special term')",
            "$select": "LogicalCollectionName,DisplayName",
            "$top": 5,
        })
        for e in meta.get("value", []):
            name = e.get("LogicalCollectionName", "")
            if name:
                _STR_ENTITY = name
                return name
    except Exception:
        pass

    raise RuntimeError(
        "Could not find the Special Terms entity. "
        "Check that 'Special Terms' exists in your CRM and the API user has access to it."
    )


def search_special_terms(search_term: str = "", status: str = "all", limit: int = 50) -> dict:
    """
    Search for Special Terms (STR) records.

    search_term: STR number (ST-...), title, or account name (leave blank for all)
    status: "all", "submitted", "approved", "rejected", "draft"
    limit: max results to return (default 50)
    """
    entity = _get_str_entity()

    params = {
        "$top": limit,
        "$orderby": "createdon desc",
    }

    filters = []

    status_lower = status.lower()
    if status_lower == "submitted":
        filters.append("contains(tolower(tyr_approvalstatus),'submitted')")
    elif status_lower == "approved":
        filters.append("contains(tolower(tyr_approvalstatus),'approved')")
    elif status_lower == "rejected":
        filters.append("contains(tolower(tyr_approvalstatus),'rejected')")
    elif status_lower == "draft":
        filters.append("contains(tolower(tyr_approvalstatus),'draft')")

    if search_term:
        filters.append(
            f"(contains(tyr_name,'{search_term}') or "
            f"contains(tyr_strtitle,'{search_term}'))"
        )

    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get(entity, params)
    records = result.get("value", [])

    return {
        "total_found": len(records),
        "records": [_format_str(r) for r in records],
    }


def get_special_terms_details(str_id: str) -> dict:
    """
    Get full details for a specific STR record including approval status.

    str_id: the GUID of the Special Terms record
    """
    entity = _get_str_entity()
    r = crm_get(f"{entity}({str_id})")
    return _format_str(r, full=True)


def get_pending_approvals(approver_role: str = "all") -> dict:
    """
    Find STR records that are currently awaiting approval.

    approver_role: "all", "sales" (sales leadership pending), or "finance" (finance pending)

    Returns STRs stuck in the approval queue.
    """
    entity = _get_str_entity()

    params = {
        "$top": 100,
        "$filter": "contains(tolower(tyr_approvalstatus),'submitted')",
        "$orderby": "createdon asc",
    }

    result = crm_get(entity, params)
    records = result.get("value", [])

    return {
        "total_pending": len(records),
        "message": f"Found {len(records)} STR(s) awaiting approval",
        "records": [_format_str(r) for r in records],
    }


def get_special_terms_by_account(account_name: str) -> dict:
    """
    Get all STR records linked to a specific account.

    account_name: full or partial account name (e.g. "South Bay Aquatic")
    """
    entity = _get_str_entity()

    # First find matching accounts
    acct_result = crm_get("accounts", {
        "$select": "accountid,name",
        "$filter": f"contains(name,'{account_name}')",
        "$top": 5,
    })
    accounts = acct_result.get("value", [])

    if not accounts:
        return {"error": f"No accounts found matching '{account_name}'"}

    all_records = []
    for acct in accounts:
        acct_id = acct.get("accountid")
        result = crm_get(entity, {
            "$top": 50,
            "$filter": f"_tyr_account_value eq {acct_id}",
            "$orderby": "createdon desc",
        })
        for r in result.get("value", []):
            r["_account_name"] = acct.get("name", "")
            all_records.append(r)

    return {
        "account_searched": account_name,
        "accounts_matched": len(accounts),
        "total_strs": len(all_records),
        "records": [_format_str(r) for r in all_records],
    }


def get_expiring_special_terms(days: int = 30) -> dict:
    """
    Find approved STR records that are expiring within the next N days.

    days: how many days ahead to look (default 30)
    """
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    entity = _get_str_entity()
    params = {
        "$top": 100,
        "$filter": f"tyr_expirationdate ge {today} and tyr_expirationdate le {future}",
        "$orderby": "tyr_expirationdate asc",
    }

    result = crm_get(entity, params)
    records = result.get("value", [])

    return {
        "days_ahead": days,
        "total_expiring": len(records),
        "message": f"Found {len(records)} STR(s) expiring within {days} days",
        "records": [_format_str(r) for r in records],
    }


def get_special_terms_summary() -> dict:
    """
    Get a high-level summary of all STR records: counts by approval status and request type.
    """
    entity = _get_str_entity()
    records = crm_get(entity, {"$top": 2000}).get("value", [])

    total = len(records)
    by_status: dict = {}
    by_type: dict = {}

    for r in records:
        status = _get_field(r, ["tyr_approvalstatus", "statuscode"], "Unknown")
        req_type = _get_field(r, ["tyr_typeofrequest", "tyr_requesttype"], "Unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_type[req_type] = by_type.get(req_type, 0) + 1

    return {
        "total_strs": total,
        "by_approval_status": by_status,
        "by_request_type": dict(sorted(by_type.items(), key=lambda x: x[1], reverse=True)),
    }


def get_str_workflows() -> dict:
    """
    Find all workflows related to the Special Terms approval process.
    Returns workflows triggered by the Special Terms entity plus any
    named 'approval', 'STR', or 'special terms'.
    """
    entity_name = _get_str_entity().rstrip("s")  # strip plural for entity match

    results = {}

    # Workflows by entity
    try:
        by_entity = crm_get("workflows", {
            "$select": "workflowid,name,statecode,statuscode,primaryentity,description",
            "$filter": f"contains(primaryentity,'{entity_name}') and category eq 0",
            "$top": 50,
        }).get("value", [])
        results["by_entity"] = by_entity
    except Exception:
        results["by_entity"] = []

    # Workflows by name keyword
    try:
        by_name = crm_get("workflows", {
            "$select": "workflowid,name,statecode,statuscode,primaryentity,description",
            "$filter": "(contains(tolower(name),'special term') or contains(tolower(name),'str') or contains(tolower(name),'approval')) and category eq 0",
            "$top": 50,
        }).get("value", [])
        results["by_name"] = by_name
    except Exception:
        results["by_name"] = []

    # Deduplicate
    seen = set()
    all_wf = []
    for wf in results["by_entity"] + results["by_name"]:
        wid = wf.get("workflowid")
        if wid and wid not in seen:
            seen.add(wid)
            all_wf.append(wf)

    status_labels = {(1, 2): "Active", (0, 1): "Draft", (0, 3): "Inactive"}

    return {
        "total_found": len(all_wf),
        "workflows": [
            {
                "id": wf.get("workflowid"),
                "name": wf.get("name", ""),
                "status": status_labels.get((wf.get("statecode"), wf.get("statuscode")), "Unknown"),
                "entity": wf.get("primaryentity", ""),
                "description": wf.get("description", ""),
            }
            for wf in all_wf
        ],
    }


def update_special_terms(str_id: str, updates: dict) -> dict:
    """
    Update fields on a Special Terms record.

    str_id: the GUID of the STR record
    updates: fields to change, e.g.:
             {"tyr_expirationdate": "2026-06-30", "tyr_strtitle": "New Title"}

    Common fields:
      tyr_strtitle          → STR title
      tyr_expirationdate    → expiration date (YYYY-MM-DD)
      tyr_effectivedate     → effective date
      tyr_typeofrequest     → type of request
      tyr_discountforallproduct → discount for all products
    """
    entity = _get_str_entity()
    crm_patch(entity, str_id, updates)
    return {
        "success": True,
        "str_id": str_id,
        "fields_updated": list(updates.keys()),
        "message": f"Special Terms record {str_id} updated successfully",
    }


# ── Internal helpers ──────────────────────────────────────────

def _get_field(record: dict, candidates: list, default="") -> str:
    """Try multiple field name candidates, return first match."""
    for key in candidates:
        val = record.get(key)
        if val is not None:
            return str(val)
    return default


def _format_str(r: dict, full: bool = False) -> dict:
    """Format a raw STR record into a clean dict."""
    base = {
        "id": _get_field(r, ["tyr_specialtermsid", "tyr_strid", "activityid"]),
        "record_number": _get_field(r, ["tyr_name", "tyr_specialtermsagreement"]),
        "title": _get_field(r, ["tyr_strtitle", "tyr_title"]),
        "account": r.get("_account_name") or _get_field(r, ["_tyr_account_value@OData.Community.Display.V1.FormattedValue"]),
        "approval_status": _get_field(r, ["tyr_approvalstatus", "statuscode@OData.Community.Display.V1.FormattedValue"]),
        "special_terms_type": _get_field(r, ["tyr_specialtermstype@OData.Community.Display.V1.FormattedValue", "tyr_specialtermstype"]),
        "type_of_request": _get_field(r, ["tyr_typeofrequest@OData.Community.Display.V1.FormattedValue", "tyr_typeofrequest"]),
        "effective_date": _get_field(r, ["tyr_effectivedate"]),
        "expiration_date": _get_field(r, ["tyr_expirationdate"]),
        "owner": _get_field(r, ["_ownerid_value@OData.Community.Display.V1.FormattedValue"]),
        "created": r.get("createdon", ""),
    }

    if full:
        base.update({
            "account_contact": _get_field(r, ["_tyr_accountcontact_value@OData.Community.Display.V1.FormattedValue"]),
            "team": _get_field(r, ["_tyr_team_value@OData.Community.Display.V1.FormattedValue"]),
            "order": _get_field(r, ["tyr_order"]),
            "invoice": _get_field(r, ["tyr_invoice"]),
            "discount_for_all_product": _get_field(r, ["tyr_discountforallproduct"]),
            "lock_in": r.get("tyr_lockin", False),
        })

    return {k: v for k, v in base.items() if v not in ("", None, False) or k in ("lock_in",)}
