#!/usr/bin/env python3
"""
Diagnose why Special Terms records submitted but no approval records are created.
Run: python diagnose_str_approval.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get, DYNAMICS_URL

STR_ID = "ST-202608-11463"  # the example record

# Step 1: Find the STR entity logical name
print("=== Step 1: Find STR entity ===")
for entity in ("tyr_specialterms", "tyr_str", "tyr_specialtermsrequirement", "tyr_specialterm"):
    try:
        r = crm_get(entity, {"$top": 1, "$select": f"{entity[4:]}id"})
        if "value" in r:
            print(f"Entity collection: {entity}")
            STR_ENTITY = entity
            break
    except Exception:
        continue
else:
    print("Could not find STR entity. Trying search by title...")
    STR_ENTITY = None

# Step 2: Fetch the specific STR record
print(f"\n=== Step 2: Fetch STR record {STR_ID} ===")
str_record = None
if STR_ENTITY:
    try:
        results = crm_get(STR_ENTITY, {
            "$filter": f"tyr_specialtermsagreement eq '{STR_ID}'",
            "$top": 1,
        })
        records = results.get("value", [])
        if records:
            str_record = records[0]
            str_guid = list(str_record.keys())
            id_field = next((k for k in str_record if k.endswith("id") and "tyr_" in k), None)
            print(f"Found: {str_record.get('tyr_specialtermsagreement')} — GUID field: {id_field}")
            print(f"All fields:")
            for k, v in sorted(str_record.items()):
                if not k.startswith("@") and v is not None:
                    print(f"  {k}: {v}")
    except Exception as e:
        print(f"Error: {e}")

# Step 3: Check active workflows on the STR entity
print(f"\n=== Step 3: Active workflows on STR entity ===")
try:
    wfs = crm_get("workflows", {
        "$select": "workflowid,name,statecode,statuscode,primaryentity,triggeroncreate,triggeronarrival,category",
        "$filter": "statecode eq 1",
        "$top": 200,
    }).get("value", [])

    str_wfs = [w for w in wfs if STR_ENTITY and STR_ENTITY.rstrip("s") in (w.get("primaryentity") or "").lower()
               or "special" in (w.get("name") or "").lower()
               or "approv" in (w.get("name") or "").lower()
               or "str" in (w.get("name") or "").lower()]

    cat_map = {0: "Workflow", 1: "Dialog", 2: "BusinessRule", 3: "Workflow", 4: "BPF", 5: "ModernFlow"}
    print(f"STR/approval-related active workflows: {len(str_wfs)}")
    for w in str_wfs:
        cat = cat_map.get(w.get("category"), str(w.get("category")))
        print(f"  [{cat}] {w['name']} (entity: {w.get('primaryentity')})")

    if not str_wfs:
        print("  NONE — this is likely the problem. No active workflow to route approvals.")
        print(f"\n  All active workflow entities (for reference):")
        entities = sorted({w.get("primaryentity","") for w in wfs if w.get("primaryentity")})
        for e in entities:
            print(f"    {e}")

except Exception as e:
    print(f"Error: {e}")

# Step 4: Check Power Automate flows (category 5)
print(f"\n=== Step 4: Modern Flows (Power Automate) referencing approvals ===")
try:
    flows = crm_get("workflows", {
        "$select": "workflowid,name,statecode,statuscode,primaryentity",
        "$filter": "category eq 5 and statecode eq 1",
        "$top": 200,
    }).get("value", [])

    approval_flows = [f for f in flows if
                      "approv" in (f.get("name") or "").lower() or
                      "special" in (f.get("name") or "").lower() or
                      "str" in (f.get("name") or "").lower() or
                      (STR_ENTITY and STR_ENTITY.rstrip("s") in (f.get("primaryentity") or "").lower())]

    print(f"Approval-related active Power Automate flows: {len(approval_flows)}")
    for f in approval_flows:
        print(f"  {f['name']} (entity: {f.get('primaryentity')})")

    if not approval_flows:
        print("  NONE active.")
        # Show all flows with STR entity
        str_flows = [f for f in flows if STR_ENTITY and STR_ENTITY.rstrip("s") in (f.get("primaryentity") or "").lower()]
        if str_flows:
            print(f"\n  Flows on STR entity (any status):")
            for f in str_flows:
                print(f"    {f['name']} statecode={f.get('statecode')}")

except Exception as e:
    print(f"Error: {e}")

# Step 5: Check if there's a BPF on STR
print(f"\n=== Step 5: Business Process Flows on STR ===")
try:
    bpfs = crm_get("workflows", {
        "$select": "workflowid,name,statecode,primaryentity",
        "$filter": "category eq 4",
        "$top": 100,
    }).get("value", [])
    str_bpfs = [b for b in bpfs if STR_ENTITY and STR_ENTITY.rstrip("s") in (b.get("primaryentity") or "").lower()]
    print(f"BPFs on STR entity: {len(str_bpfs)}")
    for b in str_bpfs:
        print(f"  {b['name']} statecode={b.get('statecode')}")

except Exception as e:
    print(f"Error: {e}")

# Step 6: Check msdyn_approval entity for any recent records
print(f"\n=== Step 6: Recent approval records (msdyn_approval) ===")
try:
    approvals = crm_get("msdyn_approvals", {
        "$select": "msdyn_approvalid,msdyn_title,createdon,statecode,_regardingobjectid_value",
        "$top": 5,
        "$orderby": "createdon desc",
    }).get("value", [])
    print(f"Recent approvals: {len(approvals)}")
    for a in approvals:
        print(f"  {a.get('msdyn_title')} — created: {a.get('createdon')} regarding: {a.get('_regardingobjectid_value')}")
    if not approvals:
        print("  No approval records found at all.")
except Exception as e:
    print(f"  msdyn_approvals not available: {e}")

print("\nDone.")
