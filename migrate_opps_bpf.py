"""
Migrate opportunities from old Lead-to-Opportunity BPF to a standalone
Opportunity BPF.

For cross-entity BPFs the process state is stored in a BPF instance entity
(e.g. leadtoopportunitysalesprocesses), NOT directly on the opportunity.
This script finds those instances, extracts the opportunity IDs, then patches
processid + stageid on each opportunity to switch it to the target BPF.
"""
import os, uuid, time, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

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

def get_stages(bpf_id):
    r = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/processstages",
        headers=get_headers(),
        params={"$select": "processstageid,stagename,primaryentitytypecode",
                "$filter": f"_processid_value eq {bpf_id}"},
        timeout=30)
    return r.json().get("value", [])

# ── Step 1: Find the old BPF and its instance entity name ───────────────────
print("Step 1: Finding old Lead-to-Opportunity BPF...")
resp = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={"$select": "workflowid,name,uniquename,primaryentity",
            "$filter": "category eq 4 and contains(name,'Lead to Opportunity') and statecode eq 1",
            "$orderby": "createdon asc"},
    timeout=30)
bpfs = resp.json().get("value", [])
old_bpf = next((b for b in bpfs if "(Copy)" not in b["name"]), None)
if not old_bpf:
    print("Could not find old BPF. Exiting.")
    exit(1)

old_bpf_id   = old_bpf["workflowid"]
unique_name  = (old_bpf.get("uniquename") or "").lower().strip()
entity_set   = unique_name + "es" if unique_name else "leadtoopportunitysalesprocesses"
print(f"  Name:        {old_bpf['name']}")
print(f"  ID:          {old_bpf_id}")
print(f"  Uniquename:  {unique_name}")
print(f"  Entity set:  {entity_set}\n")

# ── Step 2: Probe BPF instance entity to find field names ───────────────────
print("Step 2: Probing BPF instance entity...")
r_probe = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/{entity_set}",
    headers=get_headers(), params={"$top": 2}, timeout=30)
print(f"  Status: {r_probe.status_code}")

opp_field = None
if r_probe.ok:
    instances = r_probe.json().get("value", [])
    if instances:
        all_keys = sorted(instances[0].keys())
        print(f"  Fields: {all_keys}")
        # Find field that links to opportunity
        for k in all_keys:
            if "opportunity" in k.lower() and not k.startswith("@"):
                opp_field = k
                print(f"  -> Opportunity link field: {opp_field}")
                break
    else:
        print("  No instances found in entity.")
else:
    # Try alternate entity set name (without trailing 'es')
    r_probe2 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/{unique_name}",
        headers=get_headers(), params={"$top": 2}, timeout=30)
    print(f"  Alternate ({unique_name}) status: {r_probe2.status_code}")
    if r_probe2.ok:
        entity_set = unique_name
        instances = r_probe2.json().get("value", [])
        if instances:
            all_keys = sorted(instances[0].keys())
            print(f"  Fields: {all_keys}")
            for k in all_keys:
                if "opportunity" in k.lower() and not k.startswith("@"):
                    opp_field = k
                    print(f"  -> Opportunity link field: {opp_field}")
                    break
print()

if not opp_field:
    print("Could not find opportunity link field on BPF instance entity.")
    print("Check entity set name or field names above and update script.")
    exit(1)

# ── Step 3: Find target opportunity BPF ─────────────────────────────────────
print("Step 3: Finding active BPFs with opportunity stages...")
resp2 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={"$select": "workflowid,name", "$filter": "category eq 4 and statecode eq 1"},
    timeout=30)
all_bpfs = resp2.json().get("value", [])

opp_bpfs = []
for bpf in all_bpfs:
    if bpf["workflowid"] == old_bpf_id:
        continue
    stages = get_stages(bpf["workflowid"])
    opp_stages = [s for s in stages if s["primaryentitytypecode"] == "opportunity"]
    if opp_stages:
        opp_bpfs.append({"bpf": bpf, "stages": opp_stages})
        print(f"  {len(opp_bpfs)}. {bpf['name']}")
        for s in opp_stages:
            print(f"       {s['stagename']:25s} {s['processstageid']}")
    time.sleep(0.1)

if not opp_bpfs:
    print("No other BPF has opportunity stages — cannot migrate.")
    exit(1)

idx = int(input("\nEnter number of target BPF: ").strip()) - 1
chosen       = opp_bpfs[idx]
target_id    = chosen["bpf"]["workflowid"]
first_stage  = chosen["stages"][0]["processstageid"]
print(f"\nTarget: {chosen['bpf']['name']}")
print(f"First stage: {chosen['stages'][0]['stagename']} ({first_stage})\n")

# ── Step 4: Get opportunity IDs from BPF instance entity ────────────────────
print("Step 4: Fetching opportunity IDs from BPF instances...")
opp_ids = []
url = f"{DYNAMICS_URL}/api/data/v9.2/{entity_set}"
params = {"$select": opp_field}
page = 0
while url:
    r = requests.get(url, headers=get_headers({"Prefer": "odata.maxpagesize=5000"}),
                     params=params, timeout=60)
    if not r.ok:
        print(f"  Error: {r.status_code} {r.text[:300]}")
        exit(1)
    for inst in r.json().get("value", []):
        oid = inst.get(opp_field) or inst.get(f"_{opp_field}_value")
        if oid:
            opp_ids.append(str(oid))
    page += 1
    url = r.json().get("@odata.nextLink")
    params = None
    time.sleep(0.2)

# Deduplicate
opp_ids = list(set(opp_ids))
print(f"  Found {len(opp_ids)} unique opportunity IDs from BPF instances\n")

if not opp_ids:
    print("No opportunities linked to BPF instances. Nothing to migrate.")
    exit(0)

# ── Step 5: Batch migrate ────────────────────────────────────────────────────
print(f"Step 5: Migrating {len(opp_ids)} opportunities to '{chosen['bpf']['name']}'...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(opp_ids) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(opp_ids), BATCH_SIZE), 1):
    batch = opp_ids[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for oid in batch:
        # processid and stageid are plain GUID fields, not navigation properties
        payload = f'{{"processid":"{target_id}","stageid":"{first_stage}"}}'
        parts.append(
            f"--{boundary}\r\nContent-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/opportunities({oid}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n{payload}\r\n"
        )
    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = requests.post(f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers={**get_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
        data=body.encode("utf-8"), timeout=120)
    if resp.ok:
        ok = resp.text.count("HTTP/1.1 204")
        fail = len(batch) - ok
        errors += fail
        updated += ok
        print(f"  Batch {batch_num}/{total_batches}: {ok} migrated, {fail} errors")
        if fail:
            # Show first individual error from batch response
            for line in resp.text.splitlines():
                if "HTTP/1.1 4" in line or '"message"' in line:
                    print(f"    {line.strip()}")
                    break
    else:
        errors += len(batch)
        # Parse first individual error out of multipart body
        first_err = next((l.strip() for l in resp.text.splitlines()
                          if '"message"' in l or "HTTP/1.1 4" in l), resp.text[:200])
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} — {first_err}")
    time.sleep(1)

print(f"\nDone. Migrated: {updated}, Errors: {errors}")
