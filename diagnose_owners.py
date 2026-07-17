#!/usr/bin/env python3
"""
Diagnose why contact owner sync returns 0 updates.
Checks Justin Sturgeon's contact owner vs his account owner.
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get

# Step 1: Get Justin's contact
print("=== Step 1: Justin Sturgeon's contact ===")
contacts = crm_get("contacts", {
    "$select": "contactid,fullname,_ownerid_value,_parentcustomerid_value,ownerid",
    "$filter": "fullname eq 'Justin Sturgeon'",
    "$top": 1,
}).get("value", [])
if not contacts:
    print("Contact not found"); sys.exit(1)
c = contacts[0]
print(f"Contact ID: {c['contactid']}")
print(f"Contact owner (_ownerid_value): {c.get('_ownerid_value')}")
print(f"Contact parent account (_parentcustomerid_value): {c.get('_parentcustomerid_value')}")
print(f"Raw owner field: {c.get('ownerid')}")
print(f"All keys: {list(c.keys())}")

acct_id = c.get("_parentcustomerid_value")
contact_owner = c.get("_ownerid_value")

if not acct_id:
    print("\nNo parent account linked."); sys.exit(1)

# Step 2: Get the account's owner
print(f"\n=== Step 2: Account {acct_id} owner ===")
acct = crm_get(f"accounts({acct_id})", {
    "$select": "accountid,name,_ownerid_value,ownerid",
}).get if False else crm_get(f"accounts({acct_id})", {"$select": "accountid,name,_ownerid_value"})
print(f"Account name: {acct.get('name')}")
print(f"Account owner (_ownerid_value): {acct.get('_ownerid_value')}")
print(f"All keys: {list(acct.keys())}")

acct_owner = acct.get("_ownerid_value")

# Step 3: Compare
print(f"\n=== Step 3: Comparison ===")
print(f"Contact owner: {contact_owner}")
print(f"Account owner:  {acct_owner}")
print(f"Match: {contact_owner == acct_owner}")
if contact_owner != acct_owner:
    print(">>> MISMATCH — sync should update this contact")
else:
    print(">>> Same owner — no update needed")

# Step 4: Run the same bulk query the sync uses and check if Justin appears
print(f"\n=== Step 4: Bulk contact query (as sync does it) ===")
page = crm_get("contacts", {
    "$select": "contactid,fullname,_ownerid_value,_parentcustomerid_value",
    "$filter": "statecode eq 0 and _parentcustomerid_value ne null",
    "$top": 2000,
})
contacts_bulk = page.get("value", [])
print(f"Fetched {len(contacts_bulk)} contacts (page 1)")

justin_in_bulk = [c for c in contacts_bulk if c.get("fullname") == "Justin Sturgeon"]
print(f"Justin in bulk: {len(justin_in_bulk)}")
for j in justin_in_bulk:
    print(f"  _ownerid_value: {j.get('_ownerid_value')}")
    print(f"  _parentcustomerid_value: {j.get('_parentcustomerid_value')}")

# Step 5: Check if there are more pages
if page.get("@odata.nextLink"):
    print("Has more pages — Justin might be on page 2+")
else:
    print("Only one page of contacts")
