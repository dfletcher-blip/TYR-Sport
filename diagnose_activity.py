#!/usr/bin/env python3
"""
Diagnose why a contact/lead is missing Last Activity Date.
Usage: python diagnose_activity.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get

NAME = "Justin Sturgeon"

print(f"\n=== Looking up: {NAME} ===")

# Try contact first, then lead
record_id = record_email = record_type = collection = nav_prop = None

contacts = crm_get("contacts", {
    "$select": "contactid,fullname,emailaddress1",
    "$filter": f"fullname eq '{NAME}'",
    "$top": 3,
}).get("value", [])

if contacts:
    c = contacts[0]
    record_id, record_email, record_type = c["contactid"], c.get("emailaddress1",""), "contact"
    collection, nav_prop = "contacts", "Contact_ActivityPointers"
    print(f"Found Contact: {c['fullname']} — ID: {record_id} — Email: {record_email}\n")
else:
    leads = crm_get("leads", {
        "$select": "leadid,fullname,emailaddress1",
        "$filter": f"fullname eq '{NAME}'",
        "$top": 3,
    }).get("value", [])
    if leads:
        l = leads[0]
        record_id, record_email, record_type = l["leadid"], l.get("emailaddress1",""), "lead"
        collection, nav_prop = "leads", "Lead_ActivityPointers"
        print(f"Found Lead: {l['fullname']} — ID: {record_id} — Email: {record_email}\n")
    else:
        print("Not found as contact or lead.")
        sys.exit(1)

# Try 1: Navigation property
print(f"--- Try 1: {nav_prop} navigation property ---")
try:
    r = crm_get(f"{collection}({record_id})/{nav_prop}", {
        "$select": "activityid,activitytypecode,subject,createdon,statecode",
        "$top": 5,
    })
    acts = r.get("value", [])
    print(f"Found {len(acts)} activities")
    for a in acts:
        print(f"  {a.get('activitytypecode')} | {a.get('subject','')} | {a.get('createdon','')} | statecode:{a.get('statecode')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 2: Direct activitypointer filter
print("\n--- Try 2: activitypointers _regardingobjectid_value filter ---")
try:
    r = crm_get("activitypointers", {
        "$select": "activityid,activitytypecode,subject,createdon,statecode",
        "$filter": f"_regardingobjectid_value eq '{record_id}'",
        "$top": 5,
    })
    acts = r.get("value", [])
    print(f"Found {len(acts)} activities")
    for a in acts:
        print(f"  {a.get('activitytypecode')} | {a.get('subject','')} | {a.get('createdon','')} | statecode:{a.get('statecode')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 3: activityparties by record ID
print("\n--- Try 3: activityparties where _partyid_value = record ID ---")
try:
    r = crm_get("activityparties", {
        "$select": "activityid,participationtypemask,_partyid_value",
        "$filter": f"_partyid_value eq '{record_id}'",
        "$top": 10,
    })
    parties = r.get("value", [])
    print(f"Found {len(parties)} party records")
    for p in parties:
        try:
            act = crm_get(f"activitypointers({p['activityid']})", {"$select": "activitytypecode,subject,createdon"})
            print(f"  {act.get('activitytypecode')} | {act.get('subject','')} | {act.get('createdon','')}")
        except Exception:
            print(f"  activityid:{p.get('activityid')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 4: activityparties by email address
if record_email:
    print(f"\n--- Try 4: activityparties where addressused = {record_email} ---")
    try:
        r = crm_get("activityparties", {
            "$select": "activityid,participationtypemask,addressused",
            "$filter": f"addressused eq '{record_email}'",
            "$top": 10,
        })
        parties = r.get("value", [])
        print(f"Found {len(parties)} party records by email address")
        for p in parties:
            print(f"  activityid:{p.get('activityid')} type:{p.get('participationtypemask')}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone.")
