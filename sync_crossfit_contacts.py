"""
Phase 2 sync: Update remaining null-tyr_tyrtype contacts whose parent account has CrossFit.

Strategy:
  1. Get all CrossFit account IDs (simple filter on accounts)
  2. Get all contacts with null tyr_tyrtype
  3. Cross-reference in Python
  4. Batch PATCH updates (50 per request)
"""
import os, time, uuid, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

_token_cache = {"token": None, "expires_at": 0}

def get_token():
    now = time.time()
    if not _token_cache["token"] or now >= _token_cache["expires_at"]:
        print("  Refreshing auth token...")
        _token_cache["token"] = get_access_token()
        _token_cache["expires_at"] = now + 3000
    return _token_cache["token"]

def get_headers(extra=None):
    h = {
        "Authorization": f"Bearer {get_token()}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

def paginate(label, url, params):
    results = []
    page = 1
    while url:
        print(f"  {label} page {page}...", end=" ", flush=True)
        for attempt in range(4):
            try:
                resp = requests.get(url, headers=get_headers(), params=params, timeout=30)
                break
            except Exception as e:
                if attempt == 3:
                    raise
                wait = 2 ** attempt
                print(f"retry({e})...", end=" ", flush=True)
                time.sleep(wait)
        if not resp.ok:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        batch = data.get("value", [])
        results.extend(batch)
        print(f"{len(batch)} (total {len(results)})")
        url = data.get("@odata.nextLink")
        params = None
        page += 1
    return results

# --- Step 1: CrossFit account IDs ---
print("Step 1: Getting CrossFit account IDs...")
crossfit_accounts = paginate(
    "accounts",
    f"{DYNAMICS_URL}/api/data/v9.2/accounts",
    {
        "$select": "accountid",
        "$filter": "Microsoft.Dynamics.CRM.ContainValues(PropertyName='tyr_tyrtype',PropertyValues=['935650004'])",
        "$top": 1000,
    },
)
crossfit_ids = {a["accountid"] for a in crossfit_accounts}
print(f"  CrossFit account count: {len(crossfit_ids)}\n")

# --- Step 2: Contacts with null tyr_tyrtype ---
print("Step 2: Getting contacts with null tyr_tyrtype...")
null_contacts = paginate(
    "contacts",
    f"{DYNAMICS_URL}/api/data/v9.2/contacts",
    {
        "$select": "contactid,_parentcustomerid_value",
        "$filter": "tyr_tyrtype eq null",
        "$top": 1000,
    },
)
print(f"  Null-tyr_tyrtype contact count: {len(null_contacts)}\n")

# --- Step 3: Cross-reference ---
to_update = [c for c in null_contacts if c.get("_parentcustomerid_value") in crossfit_ids]
skipped = len(null_contacts) - len(to_update)
print(f"Step 3: {len(to_update)} contacts need CrossFit value ({skipped} skipped - no CrossFit parent)\n")

if not to_update:
    print("Nothing to update!")
    exit(0)

# --- Step 4: Batch PATCH ---
print("Step 4: Updating via $batch API...")
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

    resp = None
    for attempt in range(4):
        try:
            resp = requests.post(
                f"{DYNAMICS_URL}/api/data/v9.2/$batch",
                headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
                data=body.encode("utf-8"),
                timeout=120,
            )
            break
        except Exception as e:
            if attempt == 3:
                errors += len(batch)
                print(f"  Batch {batch_num}/{total_batches} NETWORK ERROR: {e}")
                resp = None
                break
            time.sleep(2 ** attempt)

    if resp is not None and resp.ok:
        ok_count = resp.text.count("HTTP/1.1 204")
        fail_count = len(batch) - ok_count
        updated += ok_count
        errors += fail_count
        print(f"  Batch {batch_num}/{total_batches}: {ok_count} updated, {fail_count} errors")
    elif resp is not None:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:200]}")

print(f"\nDone.")
print(f"  Updated: {updated}")
print(f"  Errors:  {errors}")
