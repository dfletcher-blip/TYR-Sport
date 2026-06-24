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

NAME = "Mike Wilkinson"

print(f"\n=== Looking up lead: {NAME} ===")
leads = crm_get("leads", {
    "$select": "leadid,fullname,emailaddress1",
    "$filter": f"fullname eq '{NAME}'",
    "$top": 3,
}).get("value", [])

if not leads:
    print("Lead not found.")
    sys.exit(1)

lead = leads[0]
lead_id = lead["leadid"]
lead_email = lead.get("emailaddress1", "")
print(f"Found: {lead['fullname']} — ID: {lead_id} — Email: {lead_email}\n")

# Try: activityparty — find emails where this lead appears as a party
print("--- Try: activityparties where partyid = lead ID ---")
try:
    r = crm_get("activityparties", {
        "$select": "activityid,participationtypemask,_partyid_value",
        "$filter": f"_partyid_value eq '{lead_id}'",
        "$top": 10,
    })
    parties = r.get("value", [])
    print(f"Found {len(parties)} party records")
    for p in parties:
        print(f"  activityid:{p.get('activityid')} type:{p.get('participationtypemask')}")
        # Look up the activity
        try:
            act = crm_get(f"activitypointers({p['activityid']})", {
                "$select": "activitytypecode,subject,createdon"
            })
            print(f"    → {act.get('activitytypecode')} | {act.get('subject','')} | {act.get('createdon','')}")
        except Exception:
            pass
except Exception as e:
    print(f"  ERROR: {e}")

# Also try with the lead's email address
if lead_email:
    print(f"\n--- Try: emails where emailaddress matches {lead_email} ---")
    try:
        r = crm_get("activityparties", {
            "$select": "activityid,participationtypemask,addressused",
            "$filter": f"addressused eq '{lead_email}'",
            "$top": 10,
        })
        parties = r.get("value", [])
        print(f"Found {len(parties)} party records by email address")
        for p in parties:
            print(f"  activityid:{p.get('activityid')} type:{p.get('participationtypemask')}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone.")


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

# Try 4: Look for a Contact with the same name — activities might be linked to Contact not Lead
print("\n--- Try 4: Check for Contact record with same name ---")
try:
    r = crm_get("contacts", {
        "$select": "contactid,fullname",
        "$filter": f"fullname eq '{NAME}'",
        "$top": 3,
    })
    contacts = r.get("value", [])
    if contacts:
        for c in contacts:
            cid = c["contactid"]
            print(f"  Found contact: {c['fullname']} — {cid}")
            acts = crm_get(f"contacts({cid})/Contact_ActivityPointers", {
                "$select": "activityid,activitytypecode,subject,createdon,statecode",
                "$top": 5,
            }).get("value", [])
            print(f"  Activities on contact: {len(acts)}")
            for a in acts:
                print(f"    {a.get('activitytypecode')} | {a.get('subject','')} | {a.get('createdon','')}")
    else:
        print("  No contact found with this name.")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 5: Most recent 5 emails in the system (any record)
print("\n--- Try 5: Most recent 5 emails in the system ---")
try:
    r = crm_get("emails", {
        "$select": "activityid,subject,createdon,_regardingobjectid_value",
        "$orderby": "createdon desc",
        "$top": 5,
    })
    emails = r.get("value", [])
    print(f"Found {len(emails)} emails")
    for a in emails:
        print(f"  subject:'{a.get('subject','')}' | regarding:{a.get('_regardingobjectid_value','')} | created:{a.get('createdon','')}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try 6: Most recent 5 activitypointers (any record, any type)
print("\n--- Try 6: Most recent 5 activities of any type in the system ---")
try:
    r = crm_get("activitypointers", {
        "$select": "activityid,activitytypecode,subject,createdon,_regardingobjectid_value",
        "$orderby": "createdon desc",
        "$top": 5,
    })
    acts = r.get("value", [])
    print(f"Found {len(acts)} activities")
    for a in acts:
        print(f"  {a.get('activitytypecode')} | '{a.get('subject','')}' | regarding:{a.get('_regardingobjectid_value','')} | created:{a.get('createdon','')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\nDone.")

# --- Extra: what record does the regarding GUID belong to? ---
print("\n--- EXTRA: Look up what records the 'regarding' GUIDs from emails belong to ---")
try:
    emails = crm_get("emails", {
        "$select": "subject,createdon,_regardingobjectid_value",
        "$filter": "_regardingobjectid_value ne null",
        "$orderby": "createdon desc",
        "$top": 5,
    }).get("value", [])

    seen = set()
    for e in emails:
        rid = e.get("_regardingobjectid_value")
        if rid and rid not in seen:
            seen.add(rid)
            # Try contact
            try:
                c = crm_get(f"contacts({rid})", {"$select": "fullname"})
                if c.get("fullname"):
                    print(f"  {rid} → Contact: {c['fullname']}")
                    continue
            except Exception:
                pass
            # Try lead
            try:
                l = crm_get(f"leads({rid})", {"$select": "fullname"})
                if l.get("fullname"):
                    print(f"  {rid} → Lead: {l['fullname']}")
                    continue
            except Exception:
                pass
            # Try account
            try:
                a = crm_get(f"accounts({rid})", {"$select": "name"})
                if a.get("name"):
                    print(f"  {rid} → Account: {a['name']}")
                    continue
            except Exception:
                pass
            print(f"  {rid} → Unknown record type")
except Exception as e:
    print(f"  ERROR: {e}")
