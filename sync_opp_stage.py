"""
One-time sync: read each opportunity's BPF stageid and write the matching
integer value to tyr_stage so it can be used in view filters.

BPF stage GUID  →  tyr_stage integer
  Discovery     →  935650000
  Proposal      →  935650001
  Negotiation   →  935650002
  Commitment    →  935650003
  Closed (Won)  →  935650004  (statecode eq 1)
  Closed (Lost) →  935650005  (statecode eq 2, default Closed Lost - Price)

Run with --dry-run to preview without making changes.
"""
import os, sys, uuid, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

# BPF stage GUID → tyr_stage integer (pipeline stages)
STAGEID_TO_TYR = {
    "372bb159-2460-4ca3-b32b-f82956cdfe0a": 935650000,  # Discovery
    "c8e504eb-3120-4867-a41b-58eacf9bb645": 935650001,  # Proposal
    "e4555131-862b-4889-87a7-e7fba1f4e57c": 935650002,  # Negotiation
    "ba3b85d0-6049-411d-863c-66444adfd61d": 935650003,  # Commitment
    # Copy BPF stages (same names, different GUIDs)
    "66091d73-ce32-4e5c-9f8f-f8536daa6bf1": 935650000,  # Discovery
    "c0ff0e41-b4da-4e56-916a-c96739b99e7f": 935650001,  # Proposal
    "8ab72105-0c5b-4fa2-ab61-32a7349bd204": 935650002,  # Negotiation
    "e50f5e96-3fef-4d11-a8f6-9d51c0655efa": 935650003,  # Commitment
    # Closed stage → Won or Lost based on statecode
    "bc9f2f84-e80a-4543-b0fe-09cd0b4bade7": None,       # handled below
    "c463d292-4365-45a8-b556-e9706c92321c": None,       # handled below
}

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

# --- Step 1: Fetch all opportunities ---
print("Step 1: Fetching all opportunities...")
all_opps = []
url = f"{DYNAMICS_URL}/api/data/v9.2/opportunities"
params = {
    "$select": "opportunityid,stageid,statecode,tyr_stage",
    "$top": 2000,
}
while url:
    r = _session.get(url, headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        print(f"  ERROR: {r.status_code} {r.text[:200]}")
        exit(1)
    data = r.json()
    all_opps.extend(data.get("value", []))
    url = data.get("@odata.nextLink")
    params = None

print(f"  {len(all_opps)} opportunities fetched\n")

# --- Step 2: Build update list ---
to_update = []
skipped_no_stage = 0
skipped_already_set = 0

for o in all_opps:
    oid       = o["opportunityid"]
    stageid   = (o.get("stageid") or "").lower()
    statecode = o.get("statecode", 0)
    current   = o.get("tyr_stage")

    if not stageid:
        skipped_no_stage += 1
        continue

    tyr_val = STAGEID_TO_TYR.get(stageid)

    # Handle Closed stage based on statecode
    if tyr_val is None and stageid in (
        "bc9f2f84-e80a-4543-b0fe-09cd0b4bade7",
        "c463d292-4365-45a8-b556-e9706c92321c",
    ):
        tyr_val = 935650004 if statecode == 1 else 935650005  # Won or Lost-Price

    if tyr_val is None:
        skipped_no_stage += 1
        continue

    if current == tyr_val:
        skipped_already_set += 1
        continue

    to_update.append({"id": oid, "tyr_stage": tyr_val})

print(f"  To update:        {len(to_update)}")
print(f"  Already correct:  {skipped_already_set}")
print(f"  No stage mapped:  {skipped_no_stage}\n")

if not to_update:
    print("Nothing to update.")
    exit(0)

if DRY_RUN:
    print("DRY RUN — first 10 records:")
    stage_labels = {
        935650000: "Discovery", 935650001: "Proposal",
        935650002: "Negotiation", 935650003: "Commitment",
        935650004: "Closed Won", 935650005: "Closed Lost - Price",
    }
    for rec in to_update[:10]:
        print(f"  {rec['id'][:8]}... → {stage_labels.get(rec['tyr_stage'], rec['tyr_stage'])}")
    if len(to_update) > 10:
        print(f"  ... and {len(to_update) - 10} more")
    print("\nRun without --dry-run to apply.")
    exit(0)

# --- Step 3: Batch PATCH ---
print("Step 3: Updating tyr_stage...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(to_update), BATCH_SIZE), 1):
    batch = to_update[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for rec in batch:
        payload = f'{{"tyr_stage":{rec["tyr_stage"]}}}'
        parts.append(
            f"--{boundary}\r\nContent-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/opportunities({rec['id']}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n{payload}\r\n"
        )
    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers={**get_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
        data=body.encode("utf-8"), timeout=120)
    if resp.ok:
        ok = resp.text.count("HTTP/1.1 204")
        updated += ok
        errors += len(batch) - ok
        print(f"  Batch {batch_num}/{total_batches}: {ok} updated, {len(batch)-ok} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:150]}")
    time.sleep(0.5)

print(f"\nDone. Updated: {updated}, Errors: {errors}")
print("Refresh your browser — 'Stage' field in view filters will now return results.")
