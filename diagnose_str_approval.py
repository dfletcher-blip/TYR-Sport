#!/usr/bin/env python3
"""
Diagnose why ST-202605-11048 was submitted but never routed to an approver.
Checks the STR record details, active approval workflows, and async job history.
"""

import traceback
from config.crm_connection import crm_get

STR_NUMBER = "ST-202605-11048"

try:
    # 1. Find the STR record
    entity_candidates = ["tyr_specialtermsagreements", "tyr_specialterms", "tyr_specialterm"]
    str_entity = None
    str_record = None

    for candidate in entity_candidates:
        try:
            result = crm_get(candidate, {
                "$filter": f"tyr_name eq '{STR_NUMBER}'",
                "$top": 1,
            })
            records = result.get("value", [])
            if records:
                str_entity = candidate
                str_record = records[0]
                break
        except Exception:
            continue

    if not str_record:
        print(f"Could not find STR record {STR_NUMBER} — trying broader search...")
        for candidate in entity_candidates:
            try:
                result = crm_get(candidate, {
                    "$filter": f"contains(tyr_name,'ST-202605')",
                    "$top": 5,
                })
                records = result.get("value", [])
                if records:
                    str_entity = candidate
                    str_record = records[0]
                    print(f"Found via broad search in '{candidate}'")
                    break
            except Exception:
                continue

    if not str_record:
        print("ERROR: Could not locate the STR record.")
        exit(1)

    # Get entity ID field name
    id_field = next((k for k in str_record if k.endswith("id") and "tyr_" in k), None)
    str_id = str_record.get(id_field) if id_field else None

    print("=" * 60)
    print(f"1. STR Record: {STR_NUMBER}")
    print("=" * 60)
    print(f"  Entity:          {str_entity}")
    print(f"  ID field:        {id_field} = {str_id}")
    print(f"  Approval Status: {str_record.get('tyr_approvalstatus','?')}")
    print(f"  Owner:           {str_record.get('_ownerid_value@OData.Community.Display.V1.FormattedValue','?')}")
    print(f"  Team:            {str_record.get('_tyr_team_value@OData.Community.Display.V1.FormattedValue', '--- EMPTY ---')}")
    print(f"  Account Contact: {str_record.get('_tyr_accountcontact_value@OData.Community.Display.V1.FormattedValue', '--- EMPTY ---')}")
    print(f"  Type of Request: {str_record.get('tyr_typeofrequest@OData.Community.Display.V1.FormattedValue', str_record.get('tyr_typeofrequest','?'))}")
    print(f"  STR Type:        {str_record.get('tyr_specialtermstype@OData.Community.Display.V1.FormattedValue', '?')}")
    print(f"  tyr_tyrentity:   {str_record.get('tyr_tyrentity@OData.Community.Display.V1.FormattedValue', str_record.get('tyr_tyrentity','?'))}")
    print()

    # 2. Find all active workflows/flows related to STR approval
    print("=" * 60)
    print("2. Active workflows/flows for STR approval")
    print("=" * 60)
    entity_logical = str_entity.rstrip("s")  # tyr_specialtermsagreement or tyr_specialterm

    wf_results = []
    for keyword_filter in [
        f"contains(primaryentity,'{entity_logical}')",
        "contains(tolower(name),'special term')",
        "contains(tolower(name),' str ')",
        "contains(tolower(name),'approval')",
    ]:
        try:
            wfs = crm_get("workflows", {
                "$select": "workflowid,name,statecode,statuscode,primaryentity,category,triggeronupdateattributelist,description",
                "$filter": f"({keyword_filter}) and statecode eq 1",
                "$top": 20,
            }).get("value", [])
            for w in wfs:
                if not any(x["workflowid"] == w["workflowid"] for x in wf_results):
                    wf_results.append(w)
        except Exception as e:
            print(f"  Workflow query error ({keyword_filter[:40]}): {e}")

    cat_labels = {0: "Workflow", 1: "Dialog", 4: "BPF", 5: "ModernFlow"}
    if wf_results:
        print(f"  Found {len(wf_results)} active workflow(s):\n")
        for w in wf_results:
            cat = cat_labels.get(w.get("category"), str(w.get("category")))
            trigger_fields = w.get("triggeronupdateattributelist", "") or ""
            print(f"  [{cat}] {w['name']}")
            print(f"         Entity: {w.get('primaryentity','?')}")
            if trigger_fields:
                print(f"         Triggers on field changes: {trigger_fields}")
            if w.get("description"):
                print(f"         Description: {w['description'][:120]}")
            print()
    else:
        print("  No active workflows found matching STR/approval keywords.")
        print("  The approval routing is likely handled by Power Automate (Modern Flow),")
        print("  not a classic CRM workflow. Check Power Automate for flows on this entity.")
    print()

    # 3. Check async operation history for this specific record
    if str_id:
        print("=" * 60)
        print(f"3. Workflow job history for {STR_NUMBER}")
        print("=" * 60)
        try:
            jobs = crm_get("asyncoperations", {
                "$select": "asyncoperationid,name,statuscode,statecode,message,createdon,completedon,operationtype",
                "$filter": f"_regardingobjectid_value eq {str_id}",
                "$orderby": "createdon desc",
                "$top": 20,
            }).get("value", [])

            status_map = {
                0: "WaitingForResources", 10: "Waiting", 20: "InProgress",
                21: "Pausing", 22: "Canceling", 30: "Succeeded",
                31: "Failed", 32: "Canceled",
            }
            op_type_map = {1: "SystemEvent", 2: "BulkEmail", 3: "ImportFileUpload",
                           9: "Workflow", 12: "MassUpdate", 16: "QuickCampaign",
                           25: "ImportEntitiesData", 27: "BulkDetectDuplicates",
                           28: "BulkDelete", 29: "CleanUpBulkImportJob",
                           31: "MatchCodes", 35: "FullTextCatalogIndex",
                           38: "BulkImpersonation", 40: "Merge", 45: "CalculateOrganizationStorageSize"}
            if jobs:
                print(f"  Found {len(jobs)} async job(s):\n")
                for j in jobs:
                    sc = j.get("statuscode")
                    ot = j.get("operationtype")
                    status_label = status_map.get(sc, str(sc))
                    op_label = op_type_map.get(ot, str(ot))
                    msg = (j.get("message") or "")[:200]
                    print(f"  [{op_label}] {j.get('name','Unnamed')}")
                    print(f"    Status: {status_label}  |  Created: {j.get('createdon','?')}")
                    if msg:
                        print(f"    Message: {msg}")
                    print()
            else:
                print("  No async jobs found for this record.")
                print("  This confirms no workflow was ever triggered on submission.")
        except Exception as e:
            print(f"  Error fetching async jobs: {e}")
    print()

    # 4. Check owner's manager (approval often routes to submitter's manager)
    owner_id = str_record.get("_ownerid_value")
    if owner_id:
        print("=" * 60)
        print("4. Owner (Maxime Rompre) manager hierarchy")
        print("=" * 60)
        try:
            owner = crm_get(f"systemusers({owner_id})", {
                "$select": "fullname,internalemailaddress,_parentsystemuserid_value",
                "$expand": "parentsystemuserid($select=systemuserid,fullname,internalemailaddress)",
            })
            mgr = owner.get("parentsystemuserid")
            print(f"  Owner:   {owner.get('fullname','?')} <{owner.get('internalemailaddress','?')}>")
            if mgr:
                print(f"  Manager: {mgr.get('fullname','?')} <{mgr.get('internalemailaddress','?')}>")
            else:
                print("  Manager: --- NOT SET --- (may explain routing failure)")
        except Exception as e:
            print(f"  Error: {e}")
    print()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    team_val = str_record.get("_tyr_team_value")
    contact_val = str_record.get("_tyr_accountcontact_value")
    print(f"  Team field populated:            {'YES' if team_val else 'NO — likely cause'}")
    print(f"  Account Contact populated:       {'YES' if contact_val else 'NO'}")
    print(f"  Active approval workflows found: {len(wf_results)}")
    if not wf_results:
        print()
        print("  ACTION: Check Power Automate for a flow named something like")
        print("  'STR Approval Routing' or 'Special Terms Submit'. If it exists,")
        print("  check its run history for failures on this record.")

except Exception:
    traceback.print_exc()
