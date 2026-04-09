"""
Targeted sync: Set tyr_tyrtype = CrossFit (935650004) on all contacts
whose parent account has CrossFit selected.

Strategy:
  1. Single paginated query to get all CrossFit contacts at once
  2. Batch PATCH requests (50 per HTTP call) to update them
"""
import os, time, uuid, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

_token_cache = {"token": None, "expires_at": 0}

def get_headers(extra=None):
    now = time.time()
    if not _token_cache["token"] or now >= _token_cache["expires_at"]:
        print("  Fetching auth token...")
        _token_cache["token"] = get_access_token()
        _token_cache["expires_at"] = now + 3000
    h = {
        "Authorization": f"Bearer {_token_cache['token']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

# --- Step 1: Get all CrossFit contacts in one paginated query ---
print("Step 1: Fetching all contacts from CrossFit accounts...")
all_contacts = []
url = f"{DYNAMICS_URL}/api/data/v9.2/contacts"
params = {
    "$select": "contactid,tyr_tyrtype",
    "$filter": "parentcustomerid_account/Microsoft.Dynamics.CRM.ContainValues(PropertyName='tyr_tyrtype',PropertyValues=['935650004'])",
    "$top": 1000,
}

page = 1
while True:
    print(f"  Page {page}...", end=" ", flush=True)
    resp = requests.get(url, headers=get_headers(), params=params, timeout=60)
    if not resp.ok:
        print(f"\nFAILED: {resp.status_code}")
        print(resp.text[:500])
        exit(1)
    data = resp.json()
    batch = data.get("value", [])
    all_contacts.extend(batch)
    print(f"{len(batch)} contacts")
    next_link = data.get("@odata.nextLink")
    if not next_link:
        break
    url = next_link
    params = None
    page += 1

to_update = [c for c in all_contacts if c.get("tyr_tyrtype") != CROSSFIT_VALUE]
already_correct = len(all_contacts) - len(to_update)
print(f"\nTotal CrossFit contacts: {len(all_contacts)}")
print(f"  Already correct: {already_correct}")
print(f"  Need update:     {len(to_update)}\n")

if not to_update:
    print("Nothing to update!")
    exit(0)

# --- Step 2: Batch update (50 patches per HTTP request) ---
print("Step 2: Updating contacts via batch API...")
BATCH_SIZE = 50
updated = 0
errors = 0
total_batches = (len(to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, batch_start in enumerate(range(0, len(to_update), BATCH_SIZE), 1):
    batch = to_update[batch_start:batch_start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"

    parts = []
    for c in batch:
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({c['contactid']}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\n"
            f"If-Match: *\r\n\r\n"
            f'{{"tyr_tyrtype": {CROSSFIT_VALUE}}}\r\n'
        )
    body = "".join(parts) + f"--{boundary}--\r\n"

    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
        data=body.encode("utf-8"),
        timeout=120,
    )

    if resp.ok:
        ok_count = resp.text.count("HTTP/1.1 204")
        fail_count = len(batch) - ok_count
        updated += ok_count
        errors += fail_count
        print(f"  Batch {batch_num}/{total_batches}: {ok_count} updated, {fail_count} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:200]}")

print(f"\nDone.")
print(f"  Updated:         {updated}")
print(f"  Already correct: {already_correct}")
print(f"  Errors:          {errors}")
