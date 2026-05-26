#!/usr/bin/env python3
"""
Fix ST-202605-11048 approval routing:
  1. Set Maxime Rompre's manager to Larry Meltzer
  2. Create the missing approval record so the STR gets actioned
"""

import traceback
from config.crm_connection import crm_get, crm_patch, crm_post

STR_ID = "db4e60f3-3355-f111-a825-00224805fad6"
STR_NUMBER = "ST-202605-11048"

try:
    # 1. Find Larry Meltzer
    larry_results = crm_get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress",
        "$filter": "contains(fullname,'Meltzer') and isdisabled eq false",
    }).get("value", [])

    if not larry_results:
        # Try alternate spelling
        larry_results = crm_get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress",
            "$filter": "contains(fullname,'Metlzer') and isdisabled eq false",
        }).get("value", [])

    if not larry_results:
        print("ERROR: Could not find Larry Meltzer in the CRM. Check spelling.")
        exit(1)

    larry = larry_results[0]
    larry_id = larry["systemuserid"]
    print(f"Found manager: {larry['fullname']} ({larry.get('internalemailaddress', '')}) — {larry_id}")

    # 2. Find Maxime Rompre
    maxime_results = crm_get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress",
        "$filter": "contains(fullname,'Rompre') and isdisabled eq false",
    }).get("value", [])

    if not maxime_results:
        print("ERROR: Could not find Maxime Rompre in the CRM.")
        exit(1)

    maxime = maxime_results[0]
    maxime_id = maxime["systemuserid"]
    print(f"Found submitter: {maxime['fullname']} ({maxime.get('internalemailaddress', '')}) — {maxime_id}")

    # 3. Set Maxime's manager to Larry
    crm_patch("systemusers", maxime_id, {
        "parentsystemuserid@odata.bind": f"/systemusers({larry_id})"
    })
    print(f"\nSet {maxime['fullname']}'s manager to {larry['fullname']}.")
    print("Future STRs submitted by Maxime will now route correctly.")

    # 4. Look up the exact navigation property names for tyr_specialtermsapprovals
    print("\nFetching entity metadata to find correct navigation property names...")
    nav_props = {}
    try:
        rels = crm_get(
            "EntityDefinitions(LogicalName='tyr_specialtermsapprovals')/ManyToOneRelationships",
            {"$select": "SchemaName,ReferencingAttribute,ReferencingEntityNavigationPropertyName"},
        ).get("value", [])
        for rel in rels:
            attr = (rel.get("ReferencingAttribute") or "").lower()
            nav  = rel.get("ReferencingEntityNavigationPropertyName") or ""
            nav_props[attr] = nav
            print(f"  {attr} → {nav}")
    except Exception as e:
        print(f"  Metadata lookup failed: {e}")

    def nav(attr_lower):
        """Return the correct navigation property name for an attribute."""
        return nav_props.get(attr_lower, attr_lower)

    # 5. Fetch the STR to get its type fields for the approval record
    str_record = crm_get(f"tyr_specialtermses({STR_ID})", {
        "$select": "tyr_specialtermstype,tyr_tyrentity,tyr_typeofrequest,tyr_expirationdate,tyr_effectivedate,tyr_strtitle",
    })

    # 6. Create the missing approval record for ST-202605-11048
    approval_payload = {
        f"{nav('tyr_specialtermsagreement')}@odata.bind": f"/tyr_specialtermses({STR_ID})",
        "ownerid@odata.bind":                              f"/systemusers({larry_id})",
        f"{nav('tyr_actualapproverid')}@odata.bind":       f"/systemusers({larry_id})",
        f"{nav('tyr_submitter')}@odata.bind":              f"/systemusers({maxime_id})",
        "tyr_sentto":       "Manager",
        "tyr_approvalstatus": 935650000,  # In Progress
    }

    # Copy type fields from the STR if present
    if str_record.get("tyr_specialtermstype") is not None:
        approval_payload["tyr_specialtermstype"] = str_record["tyr_specialtermstype"]
    if str_record.get("tyr_strtitle"):
        approval_payload["tyr_strtitle"] = str_record["tyr_strtitle"]
    if str_record.get("tyr_expirationdate"):
        approval_payload["tyr_expirationdate"] = str_record["tyr_expirationdate"]
    if str_record.get("tyr_effectivedate"):
        approval_payload["tyr_effectivedate"] = str_record["tyr_effectivedate"]

    print(f"\nPosting approval payload:")
    for k, v in approval_payload.items():
        print(f"  {k}: {v}")

    result = crm_post("tyr_specialtermsapprovalses", approval_payload)
    print(f"\nCreated approval record for {STR_NUMBER}.")
    print(f"  Assigned to: {larry['fullname']}")
    print(f"  Status: In Progress")
    print(f"\nLarry Meltzer should now see this STR in their approval queue.")

except Exception:
    traceback.print_exc()
