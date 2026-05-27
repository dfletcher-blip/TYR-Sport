"""
Revert tyr_stage to null on all opportunities that currently have it set.
This undoes the sync_opp_stage.py run.
"""
import os, uuid, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

def make_session():
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PATCH"]
    )))
    return s

_session = make_session()
_token: dict = {"value": None, "expires": 0}

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

# Fetch all opportunities where tyr_stage is set
print("Fetching opportunities with tyr_stage set...")
records = []
url = f"{DYNAMICS_URL}/api/data/v9.2/opportunities"
params = {
    "$select": "opportunityid",
    "$filter": "tyr_stage ne null",
    "$top": 2000,
}
while url:
    r = _session.get(url, headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        print(f"  ERROR: {r.status_code} {r.text[:200]}")
        exit(1)
    data = r.json()
    records.extend(data.get("value", []))
    url = data.get("@odata.nextLink")
    params = None

print(f"  Found {len(records)} opportunities to clear\n")

if not records:
    print("Nothing to revert.")
    exit(0)

# Batch PATCH tyr_stage to null
print("Clearing tyr_stage...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(records), BATCH_SIZE), 1):
    batch = records[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for rec in batch:
        parts.append(
            f"--{boundary}\r\nContent-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/opportunities({rec['opportunityid']}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n"
            f'{{\"tyr_stage\":null}}\r\n'
        )
    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers={**get_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
        data=body.encode("utf-8"), timeout=120)
    if resp.ok:
        ok = resp.text.count("HTTP/1.1 204")
        updated += ok
        errors += len(batch) - ok
        print(f"  Batch {batch_num}/{total_batches}: {ok} cleared, {len(batch)-ok} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:150]}")
    time.sleep(0.5)

print(f"\nDone. Cleared: {updated}, Errors: {errors}")
print("tyr_stage is now null on all opportunities — back to pre-sync state.")
