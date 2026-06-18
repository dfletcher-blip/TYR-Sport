#!/usr/bin/env python3
"""
Quick diagnostic: find what activities D365 has for a specific lead by name.
Run: python diagnose_activity.py
"""
import os, sys, json
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get

NAME = "Mike Wilkinson"  # change this if needed

print(f"\n=== Looking up lead: {NAME} ===")
leads = crm_get("leads", {
    "$select": "leadid,fullname",
    "$filter": f"fullname eq '{NAME}'",
    "$top": 3,
}).get("value", [])

if not leads:
    print("Lead not found.")
    sys.exit(1)

lead = leads[0]
lead_id = lead["leadid"]
print(f"Found: {lead['fullname']} — ID: {lead_id}\n")

# Try 1: Navigation property
print("--- Try 1: Lead_ActivityPointers navigation property ---")
try:
    r = crm_get(f"leads({lead_id})/Lead_ActivityPointers", {
        "$select": "activityid,activitytypecode,subject,createdon,actualend,statecode",
        "$top": 5,
    })
    activities = r.get("value", [])
    print(f"Found {len(activities)} activities")
    for a in activities:
        print(f"  {a.get('activitytypecode')} | {a.get('subject','')} | created:{a.get('createdon','')} | statecode:{a.get('statecode')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 2: Direct activitypointer filter
print("\n--- Try 2: activitypointers with _regardingobjectid_value filter ---")
try:
    r = crm_get("activitypointers", {
        "$select": "activityid,activitytypecode,subject,createdon,statecode",
        "$filter": f"_regardingobjectid_value eq '{lead_id}'",
        "$top": 5,
    })
    activities = r.get("value", [])
    print(f"Found {len(activities)} activities")
    for a in activities:
        print(f"  {a.get('activitytypecode')} | {a.get('subject','')} | created:{a.get('createdon','')} | statecode:{a.get('statecode')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 3: Emails entity directly
print("\n--- Try 3: emails entity with _regardingobjectid_value filter ---")
try:
    r = crm_get("emails", {
        "$select": "activityid,subject,createdon,statecode",
        "$filter": f"_regardingobjectid_value eq '{lead_id}'",
        "$top": 5,
    })
    activities = r.get("value", [])
    print(f"Found {len(activities)} emails")
    for a in activities:
        print(f"  {a.get('subject','')} | created:{a.get('createdon','')} | statecode:{a.get('statecode')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 4: Look for any Outreach custom entities
print("\n--- Try 4: Search for Outreach custom tables in D365 ---")
try:
    r = crm_get("EntityDefinitions", {
        "$select": "LogicalName,DisplayName",
        "$filter": "contains(LogicalName,'outreach') or contains(LogicalName,'outreach')",
        "$top": 20,
    })
    entities = r.get("value", [])
    if entities:
        for e in entities:
            print(f"  {e.get('LogicalName')} — {e.get('DisplayName',{}).get('UserLocalizedLabel',{}).get('Label','')}")
    else:
        print("  No Outreach custom entities found.")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 5: Check all recent emails regardless of regarding
print("\n--- Try 5: Most recent 5 emails in the system (any record) ---")
try:
    r = crm_get("emails", {
        "$select": "activityid,subject,createdon,_regardingobjectid_value,regardingobjecttypecode",
        "$orderby": "createdon desc",
        "$top": 5,
    })
    emails = r.get("value", [])
    print(f"Found {len(emails)} emails")
    for a in emails:
        print(f"  subject:'{a.get('subject','')}' | regarding:{a.get('regardingobjecttypecode')} | created:{a.get('createdon','')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\nDone.")
