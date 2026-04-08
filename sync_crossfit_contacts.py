"""
Targeted sync: Set tyr_tyrtype = CrossFit (935650004) on all contacts
whose parent account has CrossFit selected.

Run: python sync_crossfit_contacts.py
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
        "Content-Type": "application/json",
    }

# Step 1: Get all CrossFit account IDs
print("Getting all CrossFit accounts...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/accounts",
    headers=get_headers(),
    params={
        "$select": "accountid,name",
        "$filter": "Microsoft.Dynamics.CRM.ContainValues(PropertyName='tyr_tyrtype',PropertyValues=['935650004'])",
        "$top": 5000,
    },
)
if not resp.ok:
    print(f"FAILED to get accounts: {resp.status_code} {resp.text[:200]}")
    exit(1)

crossfit_accounts = resp.json().get("value", [])
print(f"Found {len(crossfit_accounts)} CrossFit accounts\n")

# Step 2: For each account, update its contacts
updated = 0
already_correct = 0
errors = 0

for i, acct in enumerate(crossfit_accounts):
    acct_id = acct["accountid"]

    resp2 = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/contacts",
        headers=get_headers(),
        params={
            "$select": "contactid,fullname,tyr_tyrtype",
            "$filter": f"_parentcustomerid_value eq {acct_id}",
            "$top": 500,
        },
    )
    if not resp2.ok:
        continue

    for contact in resp2.json().get("value", []):
        if contact.get("tyr_tyrtype") == CROSSFIT_VALUE:
            already_correct += 1
            continue

        patch = requests.patch(
            f"{DYNAMICS_URL}/api/data/v9.2/contacts({contact['contactid']})",
            headers={**get_headers(), "If-Match": "*"},
            json={"tyr_tyrtype": CROSSFIT_VALUE},  # integer, not string
        )
        if patch.ok:
            updated += 1
        else:
            errors += 1
            print(f"  Error on {contact.get('fullname')}: {patch.text[:150]}")

    if (i + 1) % 200 == 0:
        print(f"  {i+1}/{len(crossfit_accounts)} accounts processed — {updated} contacts updated so far")

print(f"\nDone.")
print(f"  Updated:         {updated}")
print(f"  Already correct: {already_correct}")
print(f"  Errors:          {errors}")
