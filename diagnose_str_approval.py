#!/usr/bin/env python3
"""
Diagnose why ST-202605-11048 was submitted but never routed to an approver.
Checks the STR record details, active approval workflows, and async job history.
"""

import traceback
from config.crm_connection import crm_get

STR_NUMBER = "ST-202605-11048"
STR_ENTITY = "tyr_specialtermses"
APPROVALS_ENTITY = "tyr_specialtermsapprovalses"

try:
    # 1. Find the STR record
    result = crm_get(STR_ENTITY, {
        "$filter": f"tyr_name eq '{STR_NUMBER}'",
        "$top": 1,
    })
    records = result.get("value", [])

    if not records:
        print(f"ERROR: Could not find {STR_NUMBER} in {STR_ENTITY}")
        exit(1)

    r = records[0]
    str_id = r.get("tyr_specialtermsid")

    print("=" * 60)
    print(f"1. STR Record: {STR_NUMBER}")
    print("=" * 60)
    print(f"  ID:              {str_id}")
    print(f"  Approval Status: {r.get('tyr_approvalstatus', '?')}")
    print(f"  Owner:           {r.get('_ownerid_value@OData.Community.Display.V1.FormattedValue', '?')}")
    print(f"  Team:            {r.get('_tyr_team_value@OData.Community.Display.V1.FormattedValue') or '--- EMPTY ---'}")
    print(f"  Account Contact: {r.get('_tyr_accountcontact_value@OData.Community.Display.V1.FormattedValue') or '--- EMPTY ---'}")
    print(f"  Type of Request: {r.get('tyr_typeofrequest@OData.Community.Display.V1.FormattedValue', r.get('tyr_typeofrequest', '?'))}")
    print(f"  STR Type:        {r.get('tyr_specialtermstype@OData.Community.Display.V1.FormattedValue', '?')}")
    print(f"  tyr_tyrentity:   {r.get('tyr_tyrentity@OData.Community.Display.V1.FormattedValue', r.get('tyr_tyrentity', '?'))}")
    print()

    # 2. Check tyr_specialtermsapprovals for any existing approval records
    print("=" * 60)
    print("2. Existing approval records (tyr_specialtermsapprovals)")
    print("=" * 60)
    try:
        approvals = crm_get(APPROVALS_ENTITY, {
            "$top": 20,
            "$orderby": "createdon desc",
        }).get("value", [])
        # Try to find ones linked to this STR
        linked = [a for a in approvals if str_id and str_id.lower() in str(a).lower()]
        if linked:
            print(f"  Found {len(linked)} approval record(s) for this STR:")
            for a in linked:
                print(f"  {a}")
        else:
            # Show schema of first approval record to understand the fields
            if approvals:
                sample = approvals[0]
                print(f"  No approvals found for this STR. Sample approval record fields:")
                for k, v in sample.items():
                    if not k.startswith("@"):
                        print(f"    {k}: {v!r}")
            else:
                print("  No approval records exist at all in this entity.")
    except Exception as e:
        print(f"  Error: {e}")
    print()

    # 3. Find active workflows for the STR entity
    print("=" * 60)
    print("3. Active workflows/flows for tyr_specialterms")
    print("=" * 60)
    wf_results = []
    for keyword_filter in [
        "contains(primaryentity,'tyr_specialterm')",
        "contains(tolower(name),'special term')",
        "contains(tolower(name),'approval') and contains(tolower(name),'str')",
    ]:
        try:
            wfs = crm_get("workflows", {
                "$select": "workflowid,name,statecode,statuscode,primaryentity,category,triggeronupdateattributelist",
                "$filter": f"({keyword_filter}) and statecode eq 1",
                "$top": 20,
            }).get("value", [])
            for w in wfs:
                if not any(x["workflowid"] == w["workflowid"] for x in wf_results):
                    wf_results.append(w)
        except Exception as e:
            print(f"  Query error: {e}")

    cat_labels = {0: "Workflow", 1: "Dialog", 4: "BPF", 5: "ModernFlow"}
    if wf_results:
        print(f"  Found {len(wf_results)} active workflow(s):\n")
        for w in wf_results:
            cat = cat_labels.get(w.get("category"), str(w.get("category")))
            trigger_fields = w.get("triggeronupdateattributelist") or ""
            print(f"  [{cat}] {w['name']}")
            print(f"         Entity: {w.get('primaryentity', '?')}")
            if trigger_fields:
                print(f"         Triggers on: {trigger_fields}")
            print()
    else:
        print("  No active classic workflows found.")
        print("  Approval routing is likely a Power Automate flow — check Power Automate")
        print("  for a flow triggered by tyr_specialterms status changes.")
    print()

    # 4. Check async job history for this STR record
    if str_id:
        print("=" * 60)
        print(f"4. Async job history for {STR_NUMBER}")
        print("=" * 60)
        try:
            jobs = crm_get("asyncoperations", {
                "$select": "asyncoperationid,name,statuscode,statecode,message,createdon,operationtype",
                "$filter": f"_regardingobjectid_value eq {str_id}",
                "$orderby": "createdon desc",
                "$top": 20,
            }).get("value", [])

            status_map = {0: "WaitingForResources", 10: "Waiting", 20: "InProgress",
                          30: "Succeeded", 31: "Failed", 32: "Canceled"}
            if jobs:
                print(f"  Found {len(jobs)} async job(s):\n")
                for j in jobs:
                    sc = j.get("statuscode")
                    print(f"  [{status_map.get(sc, sc)}] {j.get('name', 'Unnamed')}")
                    print(f"    Created: {j.get('createdon', '?')}")
                    msg = (j.get("message") or "")[:300]
                    if msg:
                        print(f"    Message: {msg}")
                    print()
            else:
                print("  No async jobs found — no workflow was ever triggered on this record.")
        except Exception as e:
            print(f"  Error: {e}")
    print()

    # 5. Check owner's manager
    owner_id = r.get("_ownerid_value")
    if owner_id:
        print("=" * 60)
        print("5. Owner's manager (approval may route via manager hierarchy)")
        print("=" * 60)
        try:
            owner = crm_get(f"systemusers({owner_id})", {
                "$select": "fullname,internalemailaddress",
                "$expand": "parentsystemuserid($select=systemuserid,fullname,internalemailaddress)",
            })
            mgr = owner.get("parentsystemuserid")
            print(f"  Owner:   {owner.get('fullname', '?')} <{owner.get('internalemailaddress', '?')}>")
            if mgr:
                print(f"  Manager: {mgr.get('fullname', '?')} <{mgr.get('internalemailaddress', '?')}>")
            else:
                print("  Manager: --- NOT SET --- (may explain routing failure)")
        except Exception as e:
            print(f"  Error: {e}")
    print()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    team_val = r.get("_tyr_team_value")
    contact_val = r.get("_tyr_accountcontact_value")
    print(f"  Team field populated:            {'YES' if team_val else 'NO'}")
    print(f"  Account Contact populated:       {'YES' if contact_val else 'NO'}")
    print(f"  Active approval workflows found: {len(wf_results)}")

except Exception:
    traceback.print_exc()
