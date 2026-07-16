#!/usr/bin/env python3
"""
Debug why the bulk contact sync misses records that have activities.
Run: python diagnose_sync.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get, crm_patch

TARGET = "Justin Sturgeon"

# Step 1: Get Justin's contact ID
print("=== Step 1: Get contact ID ===")
contacts = crm_get("contacts", {
    "$select": "contactid,fullname",
    "$filter": f"fullname eq '{TARGET}'",
    "$top": 1,
}).get("value", [])
if not contacts:
    print("Not found"); sys.exit(1)
justin_id = contacts[0]["contactid"]
print(f"Contact ID: {justin_id}")

# Step 2: Fetch first 2000 activitypointers (what the bulk sync does)
print("\n=== Step 2: Fetch first 2000 activitypointers (bulk sync page 1) ===")
page = crm_get("activitypointers", {
    "$select": "activityid,createdon,_regardingobjectid_value",
    "$filter": "_regardingobjectid_value ne null",
    "$orderby": "createdon desc",
    "$top": 2000,
})
activities = page.get("value", [])
print(f"Fetched {len(activities)} activities")

# Step 3: Check if Justin appears
justin_matches = [a for a in activities if a.get("_regardingobjectid_value") == justin_id]
print(f"Justin appears in this page: {len(justin_matches)} times")
for a in justin_matches:
    print(f"  {a.get('createdon')} — activityid: {a.get('activityid')}")

if not justin_matches:
    print("\nJustin NOT in first page — checking how many more pages exist...")
    has_next = bool(page.get("@odata.nextLink"))
    print(f"Has nextLink (more pages): {has_next}")

    # Count total pages needed
    page2 = crm_get(page["@odata.nextLink"], {}) if has_next else {}
    acts2 = page2.get("value", [])
    justin_p2 = [a for a in acts2 if a.get("_regardingobjectid_value") == justin_id]
    print(f"Page 2 has {len(acts2)} activities, Justin matches: {len(justin_p2)}")

# Step 4: Directly test patching Justin
print("\n=== Step 4: Directly patch Justin's Last Activity Date ===")
try:
    crm_patch("contacts", justin_id, {"tyr_lastactivitydate": "2026-07-16"})
    print("PATCH succeeded — field should now show 2026-07-16 in D365")
except Exception as e:
    print(f"PATCH FAILED: {e}")
