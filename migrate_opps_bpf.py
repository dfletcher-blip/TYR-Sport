"""
Migrate opportunities from old Lead-to-Opportunity BPF to the correct
opportunity BPF (the one applied when creating opportunities manually).

The new Copy BPF is lead-only — it has no opportunity stages.
This script finds all active BPFs that cover opportunities, identifies
the target, and migrates opportunities off the old cross-entity BPF.
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
    h = {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

def get_stages(bpf_id):
    r = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/processstages",
        headers=get_headers(),
        params={
            "$select": "processstageid,stagename,primaryentitytypecode",
            "$filter": f"_processid_value eq {bpf_id}",
        },
        timeout=30,
    )
    return r.json().get("value", [])

# ── Step 1: Find the old Lead-to-Opportunity BPF ────────────────────────────
print("Step 1: Finding old Lead-to-Opportunity BPF...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,createdon",
        "$filter": "category eq 4 and contains(name,'Lead to Opportunity') and statecode eq 1",
        "$orderby": "createdon asc",
    },
    timeout=30,
)
lead_bpfs = resp.json().get("value", [])
old_bpf = next((b for b in lead_bpfs if "(Copy)" not in b["name"]), None)
if not old_bpf:
    print("  Could not find old Lead to Opportunity BPF. Exiting.")
    exit(1)
old_bpf_id = old_bpf["workflowid"]
print(f"  Old BPF: {old_bpf['name']} ({old_bpf_id})")

old_stages = get_stages(old_bpf_id)
old_opp_stages = [s for s in old_stages if s["primaryentitytypecode"] == "opportunity"]
print(f"  Old opportunity stages: {[s['stagename'] for s in old_opp_stages]}\n")

# ── Step 2: Find ALL active BPFs that have opportunity stages ───────────────
print("Step 2: Finding all active BPFs with opportunity stages...")
resp2 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,createdon",
        "$filter": "category eq 4 and statecode eq 1",
    },
    timeout=30,
)
all_bpfs = resp2.json().get("value", [])
print(f"  Total active BPFs: {len(all_bpfs)}")

opp_bpfs = []
for bpf in all_bpfs:
    if bpf["workflowid"] == old_bpf_id:
        continue  # skip the old one
    stages = get_stages(bpf["workflowid"])
    opp_stages = [s for s in stages if s["primaryentitytypecode"] == "opportunity"]
    if opp_stages:
        opp_bpfs.append({"bpf": bpf, "stages": opp_stages})
        print(f"  Found: {bpf['name']}")
        for s in opp_stages:
            print(f"    {s['stagename']} ({s['processstageid']})")
    time.sleep(0.2)

print()
if not opp_bpfs:
    print("  No other active BPFs have opportunity stages.")
    print("  The old BPF is the only one covering opportunities.")
    print("  Options:")
    print("    1. Create an Opportunity Sales Process BPF in Dynamics 365")
    print("    2. Or remove the BPF from these opportunities entirely (patch processid to null)")
    print()
    ans = input("  Patch processid to null to detach old BPF? (yes/no): ").strip().lower()
    if ans != "yes":
        print("  Exiting — no changes made.")
        exit(0)
    target_bpf_id = None
    target_stages = []
else:
    if len(opp_bpfs) == 1:
        chosen = opp_bpfs[0]
        print(f"  Using: {chosen['bpf']['name']}")
    else:
        print("  Multiple BPFs found. Choose target:")
        for i, ob in enumerate(opp_bpfs):
            print(f"    {i+1}. {ob['bpf']['name']}")
        idx = int(input("  Enter number: ").strip()) - 1
        chosen = opp_bpfs[idx]
    target_bpf_id = chosen["bpf"]["workflowid"]
    target_stages = chosen["stages"]
    first_stage_id = target_stages[0]["processstageid"]
    print(f"  Target BPF: {chosen['bpf']['name']} ({target_bpf_id})")
    print(f"  First stage: {target_stages[0]['stagename']} ({first_stage_id})\n")

# ── Step 3: Find all open opportunities on old BPF ──────────────────────────
print("Step 3: Fetching all open opportunities (filtering by processid in Python)...")
all_open = []
url = f"{DYNAMICS_URL}/api/data/v9.2/opportunities"
params = {"$select": "opportunityid,name,stageid,processid", "$filter": "statecode eq 0"}
page = 0
while url:
    r = requests.get(url, headers=get_headers({"Prefer": "odata.maxpagesize=5000"}),
                     params=params, timeout=60)
    if not r.ok:
        print(f"  Error: {r.status_code} {r.text[:300]}")
        exit(1)
    data = r.json()
    all_open.extend(data.get("value", []))
    page += 1
    url = data.get("@odata.nextLink")
    params = None
    time.sleep(0.3)

# Show processid distribution to confirm we're matching correctly
from collections import Counter
pid_counts = Counter(o.get("processid") for o in all_open)
print(f"  Fetched {len(all_open)} open opps across {page} page(s)")
print(f"  Process ID distribution (top 5):")
for pid, cnt in pid_counts.most_common(5):
    label = "(old BPF)" if pid == old_bpf_id else ""
    print(f"    {pid}: {cnt} opps {label}")

all_opps = [o for o in all_open if o.get("processid") == old_bpf_id]
print(f"\n  Opportunities on old BPF: {len(all_opps)}\n")
if not all_opps:
    print("  Nothing to migrate.")
    exit(0)

# ── Step 4: Batch migrate ────────────────────────────────────────────────────
print("Step 4: Migrating...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(all_opps) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(all_opps), BATCH_SIZE), 1):
    batch = all_opps[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for opp in batch:
        oid = opp["opportunityid"]
        if target_bpf_id:
            payload = (
                f'{{"processid@odata.bind":"/workflows({target_bpf_id})",'
                f'"stageid@odata.bind":"/processstages({first_stage_id})"}}'
            )
        else:
            # Detach BPF entirely
            payload = '{"processid":null,"stageid":null}'
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/opportunities({oid}) HTTP/1.1\r\n"
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
        errors += len(batch) - ok
        updated += ok
        print(f"  Batch {batch_num}/{total_batches}: {ok} migrated, {len(batch)-ok} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:150]}")
    time.sleep(1)

print(f"\nDone. Migrated: {updated}, Errors: {errors}")
