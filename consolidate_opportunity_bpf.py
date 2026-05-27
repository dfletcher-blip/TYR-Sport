"""
Consolidate opportunities onto one BPF (Opportunity Sales Procedure),
then deactivate the Copy BPF.

Stage mapping (Copy → Original):
  Discovery   → Discovery
  Proposal    → Proposal
  Negotiation → Negotiation
  Commitment  → Commitment
  Closed      → Closed

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

# Known BPF IDs (from list_opportunity_bpf_stages.py output)
KEEP_BPF_ID   = "16c9f727-09db-f011-8543-000d3a5a5d81"  # Opportunity Sales Procedure
REMOVE_BPF_ID = "7ccb8970-532e-42d0-a9e2-b9952c70e85a"  # Opportunity Sales Procedure (Copy)

# Stage mapping: Copy stage ID → Original stage ID (matched by name)
STAGE_MAP = {
    "66091d73-ce32-4e5c-9f8f-f8536daa6bf1": "372bb159-2460-4ca3-b32b-f82956cdfe0a",  # Discovery
    "c0ff0e41-b4da-4e56-916a-c96739b99e7f": "c8e504eb-3120-4867-a41b-58eacf9bb645",  # Proposal
    "8ab72105-0c5b-4fa2-ab61-32a7349bd204": "e4555131-862b-4889-87a7-e7fba1f4e57c",  # Negotiation
    "e50f5e96-3fef-4d11-a8f6-9d51c0655efa": "ba3b85d0-6049-411d-863c-66444adfd61d",  # Commitment
    "c463d292-4365-45a8-b556-e9706c92321c": "bc9f2f84-e80a-4543-b0fe-09cd0b4bade7",  # Closed
}
DEFAULT_STAGE = "372bb159-2460-4ca3-b32b-f82956cdfe0a"  # Discovery

def make_session():
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=3,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST", "PATCH"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
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

# --- Step 1: Find opportunities not on the keeper BPF ---
print("Step 1: Finding opportunities not on 'Opportunity Sales Procedure'...")
to_migrate = []
url = f"{DYNAMICS_URL}/api/data/v9.2/opportunities"
params = {
    "$select": "opportunityid,name,processid,stageid",
    "$filter": f"processid ne {KEEP_BPF_ID} and statecode eq 0",
    "$top": 2000,
}
while url:
    r = _session.get(url, headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        print(f"  ERROR: {r.status_code} {r.text[:200]}")
        exit(1)
    data = r.json()
    to_migrate.extend(data.get("value", []))
    url = data.get("@odata.nextLink")
    params = None

print(f"  Found {len(to_migrate)} opportunities to migrate\n")

if not to_migrate:
    print("All opportunities already on the correct BPF.")
else:
    if DRY_RUN:
        print("DRY RUN — first 10 opportunities that would be migrated:")
        for o in to_migrate[:10]:
            old_stage = o.get("stageid") or ""
            new_stage = STAGE_MAP.get(old_stage, DEFAULT_STAGE)
            print(f"  {o.get('name','')[:50]:52} → stage {new_stage[:8]}...")
        if len(to_migrate) > 10:
            print(f"  ... and {len(to_migrate) - 10} more")
    else:
        # --- Step 2: Batch migrate ---
        print("Step 2: Migrating opportunities...")
        BATCH_SIZE = 20
        updated = errors = 0
        total_batches = (len(to_migrate) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num, start in enumerate(range(0, len(to_migrate), BATCH_SIZE), 1):
            batch = to_migrate[start:start + BATCH_SIZE]
            boundary = f"batch_{uuid.uuid4().hex}"
            parts = []
            for o in batch:
                old_stage = o.get("stageid") or ""
                new_stage = STAGE_MAP.get(old_stage, DEFAULT_STAGE)
                payload = f'{{"processid":"{KEEP_BPF_ID}","stageid":"{new_stage}"}}'
                oid = o["opportunityid"]
                parts.append(
                    f"--{boundary}\r\nContent-Type: application/http\r\n"
                    f"Content-Transfer-Encoding: binary\r\n\r\n"
                    f"PATCH {DYNAMICS_URL}/api/data/v9.2/opportunities({oid}) HTTP/1.1\r\n"
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
                print(f"  Batch {batch_num}/{total_batches}: {ok} migrated, {len(batch)-ok} errors")
            else:
                errors += len(batch)
                print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:150]}")
            time.sleep(1)

        print(f"\n  Migrated: {updated}, Errors: {errors}\n")

if DRY_RUN:
    print("\nDRY RUN complete — run without --dry-run to apply changes and deactivate the Copy BPF.")
    exit(0)

# --- Step 3: Deactivate the Copy BPF ---
print("Step 3: Deactivating 'Opportunity Sales Procedure (Copy)'...")
r = _session.patch(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({REMOVE_BPF_ID})",
    headers={**get_headers(), "If-Match": "*"},
    json={"statecode": 0, "statuscode": 1},
    timeout=30,
)
if r.ok or r.status_code == 204:
    print("  Deactivated successfully.")
else:
    print(f"  WARNING: {r.status_code} {r.text[:200]}")
    print("  You may need to deactivate the Copy BPF manually in Settings > Processes.")

print("\nDone. All opportunities are now on 'Opportunity Sales Procedure'.")
print("Refresh your browser to confirm.")
