"""
Sync contact owners to match their parent account's owner.

Contacts whose ownerid differs from their account's ownerid are updated in bulk.
Run with --dry-run to preview changes without applying them.
"""
import os, sys, uuid, time, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

_token: dict = {"value": None, "expires": 0}

def get_headers():
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "odata.include-annotations=*",
    }

# --- Step 1: Fetch contacts with mismatched owners ---
print("Step 1: Fetching contacts with parent accounts...")
contacts_to_update = []
url = f"{DYNAMICS_URL}/api/data/v9.2/contacts"
params = {
    "$select": "contactid,fullname,_ownerid_value",
    "$expand": "parentcustomerid_account($select=accountid,name,_ownerid_value)",
    "$filter": "_parentcustomerid_value ne null and statecode eq 0",
    "$top": 2000,
}

while url:
    r = requests.get(url, headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        print(f"  ERROR: {r.status_code} {r.text[:200]}")
        exit(1)
    data = r.json()
    for c in data.get("value", []):
        account = c.get("parentcustomerid_account") or {}
        acct_owner = account.get("_ownerid_value")
        if not acct_owner or c.get("_ownerid_value") == acct_owner:
            continue
        owner_type = account.get(
            "_ownerid_value@Microsoft.Dynamics.CRM.lookuplogicalname", "systemuser"
        )
        entity_set = "teams" if owner_type == "team" else "systemusers"
        contacts_to_update.append({
            "contactid":    c["contactid"],
            "name":         c.get("fullname", "Unknown"),
            "account_name": account.get("name", ""),
            "bind":         f"/{entity_set}({acct_owner})",
        })
    url = data.get("@odata.nextLink")
    params = None

print(f"  Found {len(contacts_to_update)} contacts with mismatched owners\n")

if not contacts_to_update:
    print("All contacts already match their account owner.")
    exit(0)

if DRY_RUN:
    print("DRY RUN — no changes will be made. First 20 contacts to update:\n")
    for c in contacts_to_update[:20]:
        print(f"  {c['name']} ({c['account_name']}) → {c['bind']}")
    if len(contacts_to_update) > 20:
        print(f"  ... and {len(contacts_to_update) - 20} more")
    exit(0)

# --- Step 2: Batch PATCH ---
print("Step 2: Updating contact owners...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(contacts_to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(contacts_to_update), BATCH_SIZE), 1):
    batch = contacts_to_update[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for c in batch:
        payload = f'{{"ownerid@odata.bind":"{c["bind"]}"}}'
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({c['contactid']}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\n"
            f"If-Match: *\r\n\r\n"
            f"{payload}\r\n"
        )
    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers={**get_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
        data=body.encode("utf-8"),
        timeout=120,
    )
    if resp.ok:
        ok = resp.text.count("HTTP/1.1 204")
        fail = len(batch) - ok
        updated += ok
        errors += fail
        print(f"  Batch {batch_num}/{total_batches}: {ok} updated, {fail} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:150]}")
    time.sleep(0.5)

print(f"\nDone.")
print(f"  Updated: {updated}")
print(f"  Errors:  {errors}")
