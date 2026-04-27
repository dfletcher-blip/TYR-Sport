# ============================================================
# tools/opportunity_stage_sync.py — Opportunity Stage Auto-Sync
# ============================================================
# Keeps the custom TYR Stage field in sync with the opportunity's
# actual Win/Loss status.
#
# THE PROBLEM:
#   Dynamics 365 has two separate concepts:
#     1. statecode / statuscode — the system status (Open / Won / Lost)
#     2. tyr_stage (custom field) — the human-readable stage label shown on the form
#   When a rep closes an opportunity as Won or Lost, D365 updates #1
#   automatically, but #2 (the custom field) must be updated separately.
#   This module detects and corrects that mismatch.
#
# HOW TO USE (via the CRM agent):
#   "Find all won/lost opportunities where the stage doesn't say Closed Won or Closed Lost"
#   "Sync the stage field on all closed opportunities"
#   "Fix the stage on opportunity <id>"
#
# HOW TO RUN ON A SCHEDULE (for automatic correction):
#   Add this to a cron job or scheduled task:
#     python -c "
#     from tools.opportunity_stage_sync import bulk_sync_closed_stages
#     result = bulk_sync_closed_stages(dry_run=False)
#     print(result['message'])
#     "
#
# NOTE ON NATIVE D365 AUTOMATION:
#   For zero-lag real-time sync (fires the instant someone clicks Won/Lost),
#   create a Power Automate Cloud Flow triggered on "When an opportunity is
#   updated" with a condition on statecode changing to 1 or 2. That approach
#   requires setting up the flow in the Power Automate portal.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch


# ── Option set discovery ───────────────────────────────────────────────────────

def get_opportunity_stage_options(stage_field: str = "tyr_stage") -> dict:
    """
    Discover the available option set values for the custom stage field.

    Returns the full list of label/value pairs so the agent can choose the
    correct integer value for "Closed Won" and "Closed Lost" without hardcoding.

    stage_field: the logical field name on the opportunity entity (default: tyr_stage)
    """
    try:
        meta = crm_get(
            f"EntityDefinitions(LogicalName='opportunity')"
            f"/Attributes(LogicalName='{stage_field}')"
            f"/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
            {"$expand": "OptionSet"},
        )
        options = meta.get("OptionSet", {}).get("Options", [])
        return {
            "field": stage_field,
            "found": True,
            "options": [
                {
                    "value": opt.get("Value"),
                    "label": (opt.get("Label", {}).get("UserLocalizedLabel") or {}).get("Label", ""),
                }
                for opt in options
            ],
        }
    except Exception as e:
        return {"field": stage_field, "found": False, "error": str(e), "options": []}


def _find_stage_value(options: list[dict], keywords: list[str]) -> int | None:
    """Return the integer option value whose label best matches one of the keywords."""
    for keyword in keywords:
        kw = keyword.lower()
        # Exact match first
        for opt in options:
            if opt["label"].lower() == kw:
                return opt["value"]
        # Partial match fallback
        for opt in options:
            if kw in opt["label"].lower():
                return opt["value"]
    return None


# ── Mismatch detection ─────────────────────────────────────────────────────────

def find_mismatched_closed_stages(stage_field: str = "tyr_stage", limit: int = 500) -> dict:
    """
    Find Won or Lost opportunities where the custom stage field does not yet
    reflect the closed status.

    Returns separate lists for won-but-wrong-stage and lost-but-wrong-stage,
    plus counts for how many are already correct.

    stage_field: the logical field name for the custom stage (default: tyr_stage)
    limit: max opportunities to scan (default 500)
    """
    # Fetch all closed opportunities with their stage field
    params = {
        "$select": f"opportunityid,name,statecode,statuscode,{stage_field}",
        "$filter": "statecode ne 0",  # only Won (1) and Lost (2)
        "$expand": "customerid_account($select=name)",
        "$top": limit,
        "$orderby": "modifiedon desc",
    }

    try:
        result = crm_get("opportunities", params)
    except Exception as e:
        # tyr_stage might not exist — try without it to confirm the field name
        return {
            "error": str(e),
            "hint": f"Field '{stage_field}' may not exist on the opportunity entity. "
                    "Use get_opportunity_stage_options() or list_entity_fields() to find the correct field name.",
        }

    opps = result.get("value", [])

    # Keywords that indicate the stage is already correct for closed records
    won_keywords  = {"closed won", "won", "closed-won", "closed_won"}
    lost_keywords = {"closed lost", "lost", "closed-lost", "closed_lost"}

    needs_won_update  = []
    needs_lost_update = []
    already_correct   = []

    status_labels = {0: "Open", 1: "Won", 2: "Lost"}

    for o in opps:
        current_stage_raw = o.get(stage_field)
        # The formatted value (human label) is in the annotation key
        current_stage_label = (
            o.get(f"{stage_field}@OData.Community.Display.V1.FormattedValue") or ""
        ).lower()
        actual_status = o.get("statecode")
        opp_info = {
            "opportunity_id": o.get("opportunityid"),
            "name": o.get("name", ""),
            "account": (o.get("customerid_account") or {}).get("name", ""),
            "actual_status": status_labels.get(actual_status, "Unknown"),
            "current_stage_value": current_stage_raw,
            "current_stage_label": o.get(f"{stage_field}@OData.Community.Display.V1.FormattedValue") or str(current_stage_raw),
        }

        if actual_status == 1:  # Won
            if current_stage_label in won_keywords:
                already_correct.append(opp_info)
            else:
                needs_won_update.append(opp_info)
        elif actual_status == 2:  # Lost
            if current_stage_label in lost_keywords:
                already_correct.append(opp_info)
            else:
                needs_lost_update.append(opp_info)

    total_mismatched = len(needs_won_update) + len(needs_lost_update)

    return {
        "stage_field": stage_field,
        "total_closed": len(opps),
        "total_mismatched": total_mismatched,
        "already_correct": len(already_correct),
        "needs_won_stage_update": needs_won_update,
        "needs_lost_stage_update": needs_lost_update,
        "message": (
            f"{total_mismatched} closed opportunity/opportunities have a mismatched stage field."
            if total_mismatched
            else "All closed opportunities already have the correct stage."
        ),
    }


# ── Single-opportunity fix ─────────────────────────────────────────────────────

def sync_opportunity_stage(
    opportunity_id: str,
    stage_field: str = "tyr_stage",
    dry_run: bool = False,
) -> dict:
    """
    Update the stage field on a single opportunity to match its actual Win/Loss status.

    Queries the option set metadata to find the correct "Closed Won" or "Closed Lost"
    integer value — no hardcoding required.

    opportunity_id: the GUID of the opportunity to fix
    stage_field:    the logical field name (default: tyr_stage)
    dry_run:        if True, report what would be changed without writing
    """
    # Fetch the opportunity's current status and stage
    params = {"$select": f"opportunityid,name,statecode,statuscode,{stage_field}"}
    opp = crm_get(f"opportunities({opportunity_id})", params)

    actual_status = opp.get("statecode")
    status_labels = {0: "Open", 1: "Won", 2: "Lost"}
    opp_name = opp.get("name", opportunity_id)

    if actual_status == 0:
        return {
            "success": False,
            "message": f"'{opp_name}' is still Open — no stage sync needed.",
        }

    # Discover option set values
    options_result = get_opportunity_stage_options(stage_field)
    if not options_result["found"]:
        return {
            "success": False,
            "message": f"Could not read option set for '{stage_field}': {options_result.get('error')}",
        }

    options = options_result["options"]
    is_won = actual_status == 1

    # Find the right option value
    if is_won:
        new_value = _find_stage_value(options, ["closed won", "won"])
        target_label = "Closed Won"
    else:
        new_value = _find_stage_value(options, ["closed lost", "lost"])
        target_label = "Closed Lost"

    if new_value is None:
        available = [o["label"] for o in options]
        return {
            "success": False,
            "message": (
                f"Could not find a '{target_label}' option in the '{stage_field}' option set. "
                f"Available options: {available}. "
                f"Please specify the correct label or add the option to the option set."
            ),
            "available_options": available,
        }

    current_value = opp.get(stage_field)
    current_label = opp.get(f"{stage_field}@OData.Community.Display.V1.FormattedValue") or str(current_value)

    if current_value == new_value:
        return {
            "success": True,
            "already_correct": True,
            "message": f"'{opp_name}' already has stage '{current_label}' — no change needed.",
        }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "opportunity_id": opportunity_id,
            "name": opp_name,
            "current_stage": current_label,
            "new_stage": target_label,
            "message": f"[DRY RUN] Would update '{opp_name}' stage: '{current_label}' → '{target_label}'",
        }

    crm_patch("opportunities", opportunity_id, {stage_field: new_value})

    return {
        "success": True,
        "opportunity_id": opportunity_id,
        "name": opp_name,
        "previous_stage": current_label,
        "new_stage": target_label,
        "message": f"Updated '{opp_name}': stage '{current_label}' → '{target_label}'",
    }


# ── Bulk fix ───────────────────────────────────────────────────────────────────

def bulk_sync_closed_stages(
    stage_field: str = "tyr_stage",
    dry_run: bool = True,
) -> dict:
    """
    Find all Won/Lost opportunities with a mismatched stage field and fix them all.

    Always runs with dry_run=True by default so you can preview before committing.
    Set dry_run=False to apply changes.

    stage_field: the logical field name (default: tyr_stage)
    dry_run:     if True (default), describe changes without writing them
    """
    # Find all mismatched records
    mismatches = find_mismatched_closed_stages(stage_field=stage_field)

    if "error" in mismatches:
        return mismatches

    all_to_fix = (
        mismatches["needs_won_stage_update"] +
        mismatches["needs_lost_stage_update"]
    )

    if not all_to_fix:
        return {
            "success": True,
            "fixed": 0,
            "message": "All closed opportunities already have the correct stage. Nothing to do.",
        }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "would_fix": len(all_to_fix),
            "won_to_fix": len(mismatches["needs_won_stage_update"]),
            "lost_to_fix": len(mismatches["needs_lost_stage_update"]),
            "records": [
                {
                    "name": o["name"],
                    "account": o["account"],
                    "current_stage": o["current_stage_label"],
                    "will_become": "Closed Won" if o["actual_status"] == "Won" else "Closed Lost",
                }
                for o in all_to_fix
            ],
            "message": (
                f"[DRY RUN] Would update {len(all_to_fix)} opportunity/opportunities. "
                f"Set dry_run=False to apply."
            ),
        }

    # Apply fixes
    fixed = []
    failed = []

    for opp in all_to_fix:
        try:
            result = sync_opportunity_stage(
                opp["opportunity_id"],
                stage_field=stage_field,
                dry_run=False,
            )
            if result.get("success"):
                fixed.append({"name": opp["name"], "new_stage": result.get("new_stage")})
            else:
                failed.append({"name": opp["name"], "reason": result.get("message")})
        except Exception as e:
            failed.append({"name": opp["name"], "reason": str(e)})

    return {
        "success": True,
        "fixed": len(fixed),
        "failed": len(failed),
        "fixed_records": fixed,
        "failed_records": failed,
        "message": (
            f"Stage sync complete: {len(fixed)} updated, {len(failed)} failed."
        ),
    }
