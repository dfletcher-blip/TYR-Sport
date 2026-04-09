"""
Phase 2 sync: Update null tyr_tyrtype contacts from CrossFit accounts.
Uses requests.Session with urllib3 automatic retry for stability.
"""
import os, time, uuid, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

# Session with automatic retry on 429/500/502/503/504
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5,
    backoff_factor=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PATCH"],
    respect_retry_after_header=True,
)))

_token = {"value": None, "expires": 0}

def auth_headers(content_type="application/json"):
    if not _token["value"] or time.time() >= _token["expires"]:
        print("  Getting auth token...")
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": content_type,
    }

def get_all(label, url, params):
    results, page = [], 1
    while url:
        print(f"  [{label}] page {page}...", end=" ", flush=True)
        resp = session.get(url, headers=auth_headers(), params=params, timeout=60)
        if not resp.ok:
            raise Exception(f"{label} query failed {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        batch = data.get("value", [])
        results.extend(batch)
        print(f"{len(batch)} (running total: {len(results)})")
        url = data.get("@odata.nextLink")
        params = None
        page += 1
        time.sleep(1)
    return results

print("=" * 50)
print("Step 1: CrossFit account IDs")
print("=" * 50)
accounts = get_all("accounts", f"{DYNAMICS_URL}/api/data/v9.2/accounts", {
    "$select": "accountid",
    "$filter": "Microsoft.Dynamics.CRM.ContainValues(PropertyName='tyr_tyrtype',PropertyValues=['935650004'])",
    "$top": 5000,
})
crossfit_ids = {a["accountid"] for a in accounts}
print(f"  Total: {len(crossfit_ids)} CrossFit accounts\n")

print("=" * 50)
print("Step 2: Contacts with null tyr_tyrtype")
print("=" * 50)
null_contacts = get_all("contacts", f"{DYNAMICS_URL}/api/data/v9.2/contacts", {
    "$select": "contactid,_parentcustomerid_value",
    "$filter": "tyr_tyrtype eq null",
    "$top": 5000,
})
print(f"  Total: {len(null_contacts)} null contacts\n")

print("=" * 50)
print("Step 3: Cross-reference")
print("=" * 50)
to_update = [c for c in null_contacts if c.get("_parentcustomerid_value") in crossfit_ids]
skipped = len(null_contacts) - len(to_update)
print(f"  To update (CrossFit parent): {len(to_update)}")
print(f"  Skipped (no CrossFit parent): {skipped}\n")

if not to_update:
    print("Nothing to update!")
    exit(0)

print("=" * 50)
print("Step 4: Batch PATCH updates")
print("=" * 50)
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(to_update), BATCH_SIZE), 1):
    batch = to_update[start:start + BATCH_SIZE]
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

    resp = session.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers={**auth_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
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
        print(f"  Batch {batch_num}/{total_batches} FAILED {resp.status_code}: {resp.text[:150]}")
    time.sleep(2)

print(f"\nFinal:")
print(f"  Updated: {updated}")
print(f"  Errors:  {errors}")
