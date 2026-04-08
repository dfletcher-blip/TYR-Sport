"""
Count contacts linked to CrossFit accounts and check their tyr_tyrtype.
Run: python count_crossfit_contacts.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

def get_headers():
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
    }

# Total contact count
print("Counting total contacts...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/contacts?$select=contactid&$top=1",
    headers={**get_headers(), "Prefer": "odata.maxpagesize=1,odata.include-annotations=Microsoft.Dynamics.CRM.totalrecordcount"},
    params={"$count": "true"},
)
total = resp.json().get("@odata.count", "unknown")
print(f"  Total contacts: {total}")

# Contacts linked to CrossFit accounts - using $expand to join account
print("\nCounting contacts whose parent account has CrossFit...")
resp2 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/contacts",
    headers=get_headers(),
    params={
        "$select": "contactid,fullname,tyr_tyrtype",
        "$filter": "parentcustomerid_account/tyr_tyrtype eq '935650004'",
        "$top": 5000,
        "$count": "true",
    },
)
if resp2.ok:
    data = resp2.json()
    contacts = data.get("value", [])
    count = data.get("@odata.count", len(contacts))
    print(f"  Contacts linked to CrossFit accounts: {count}")

    # Break down by their current tyr_tyrtype value
    by_value = {}
    for c in contacts:
        v = c.get("tyr_tyrtype")
        by_value[v] = by_value.get(v, 0) + 1
    print("\n  Their current tyr_tyrtype values:")
    for v, cnt in sorted(by_value.items(), key=lambda x: -x[1]):
        print(f"    {v}: {cnt} contacts")
else:
    print(f"  FAILED: {resp2.status_code} {resp2.text[:300]}")
    # Fallback: check the sync script's page size
    print("\n  Checking sync script page size instead...")
    print("  Look in sync_contact_tyr_type.py for '$top' value")
