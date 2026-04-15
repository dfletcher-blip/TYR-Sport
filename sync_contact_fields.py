"""
Sync tyr_tyrentity AND tyr_tyrtype from Account to Contact in one pass.
Fetches all accounts and contacts once, cross-references by parent account ID,
then batch PATCHes any contacts where either field is out of sync.
"""
import os, json, uuid, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
FIELDS = ["tyr_tyrentity", "tyr_tyrtype"]

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET", "POST", "PATCH"])
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {"Authorization": f"Bearer {_token['value']}",
         "OData-MaxVersion": "4.0", "OData-Version": "4.0",
         "Accept": "application/json", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

PAGE = {"Prefer": "odata.maxpagesize=5000"}

def fetch_all(entity, select_fields, extra_filter=None):
    records = []
    url = f"{DYNAMICS_URL}/api/data/v9.2/{entity}"
    params = {"$select": ",".join(select_fields)}
    if extra_filter:
        params["$filter"] = extra_filter
    page = 0
    while url:
        r = _session.get(url, headers=get_headers(PAGE), params=params, timeout=60)
        if not r.ok:
            print(f"  ERROR fetching {entity}: {r.status_code} {r.text[:300]}")
            exit(1)
        data = r.json()
        records.extend(data.get("value", []))
        page += 1
        url = data.get("@odata.nextLink")
        params = None
        time.sleep(0.2)
    print(f"  {entity}: {len(records)} records ({page} page(s))")
    return records

# ── Step 1: Fetch all accounts ───────────────────────────────────────────────
print("Step 1: Fetching all accounts...")
accounts = fetch_all("accounts", ["accountid"] + FIELDS)
acct_map = {}
for a in accounts:
    vals = {f: a.get(f) for f in FIELDS}
    if any(v is not None for v in vals.values()):
        acct_map[a["accountid"]] = vals

print(f"  Accounts with at least one field set: {len(acct_map)}\n")

# ── Step 2: Fetch all contacts ───────────────────────────────────────────────
print("Step 2: Fetching all contacts...")
contacts = fetch_all("contacts", ["contactid", "_parentcustomerid_value"] + FIELDS)
print(f"  Total contacts: {len(contacts)}\n")

# ── Step 3: Cross-reference ──────────────────────────────────────────────────
print("Step 3: Cross-referencing...")
to_update = []
no_parent = unmatched = already_synced = needs_update = 0

for c in contacts:
    parent_id = c.get("_parentcustomerid_value")
    if not parent_id:
        no_parent += 1
        continue
    acct_vals = acct_map.get(parent_id)
    if not acct_vals:
        unmatched += 1
        continue
    diff = {}
    for f in FIELDS:
        av = acct_vals.get(f)
        cv = c.get(f)
        if av is not None and av != cv:
            diff[f] = av
    if diff:
        needs_update += 1
        diff["contactid"] = c["contactid"]
        to_update.append(diff)
    else:
        already_synced += 1

print(f"  No parent ID:              {no_parent}")
print(f"  Parent not in account map: {unmatched}")
print(f"  Already in sync:           {already_synced}")
print(f"  Need update:               {needs_update}\n")

if not to_update:
    print("All contacts already in sync.")
    exit(0)

# ── Step 4: Batch PATCH ──────────────────────────────────────────────────────
print(f"Step 4: Updating {len(to_update)} contacts...")
BATCH_SIZE = 20
updated = errors = 0
total_batches = (len(to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(to_update), BATCH_SIZE), 1):
    batch = to_update[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for c in batch:
        cid = c["contactid"]
        payload = json.dumps({f: c[f] for f in FIELDS if f in c})
        parts.append(
            f"--{boundary}\r\nContent-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({cid}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n{payload}\r\n"
        )
    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = _session.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
        data=body.encode("utf-8"),
        timeout=120,
    )
    if resp.ok:
        ok = resp.text.count("HTTP/1.1 204")
        fail = len(batch) - ok
        updated += ok
        errors += fail
        print(f"  Batch {batch_num}/{total_batches}: {ok} updated, {fail} errors")
        if fail:
            first_err = next((l.strip() for l in resp.text.splitlines()
                              if '"message"' in l), "")
            if first_err:
                print(f"    {first_err}")
    else:
        errors += len(batch)
        first_err = next((l.strip() for l in resp.text.splitlines()
                          if '"message"' in l or "HTTP/1.1 4" in l), resp.text[:200])
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} — {first_err}")
    time.sleep(1)

print(f"\nDone. Updated: {updated}, Errors: {errors}")
