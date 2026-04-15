"""
Migrate opportunities from old Lead-to-Opportunity BPF to the Copy BPF.
Opportunities inherit the BPF from the lead that created them — any lead
still on the old BPF will create opportunities on the old BPF.

Stage mapping (opportunity side of BPF):
  Old → New  (names discovered at runtime from processstages API)
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

# ── Step 1: Find both BPFs ───────────────────────────────────────────────────
print("Step 1: Finding BPFs...")
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
bpfs = resp.json().get("value", [])
for b in bpfs:
    print(f"  {b['name']} — {b['workflowid']}")

old_bpf = next((b for b in bpfs if "(Copy)" not in b["name"]), None)
new_bpf = next((b for b in bpfs if "(Copy)" in b["name"]), None)

if not old_bpf or not new_bpf:
    print("Could not find both BPFs. Exiting.")
    exit(1)

old_bpf_id = old_bpf["workflowid"]
new_bpf_id = new_bpf["workflowid"]
print(f"\n  Old: {old_bpf['name']} ({old_bpf_id})")
print(f"  New: {new_bpf['name']} ({new_bpf_id})\n")

# ── Step 2: Get stages for both BPFs ────────────────────────────────────────
print("Step 2: Getting stages...")
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
    stages = r.json().get("value", [])
    return stages

old_stages = get_stages(old_bpf_id)
new_stages = get_stages(new_bpf_id)

print(f"  Old BPF stages ({len(old_stages)}):")
for s in old_stages:
    print(f"    {s['stagename']:20s} ({s['primaryentitytypecode']:15s}) {s['processstageid']}")

print(f"\n  New BPF stages ({len(new_stages)}):")
for s in new_stages:
    print(f"    {s['stagename']:20s} ({s['primaryentitytypecode']:15s}) {s['processstageid']}")
print()

# Opportunity stages only (primaryentitytypecode = 'opportunity')
old_opp_stages = {s["stagename"].lower(): s["processstageid"]
                  for s in old_stages if s["primaryentitytypecode"] == "opportunity"}
new_opp_stages  = {s["stagename"].lower(): s["processstageid"]
                  for s in new_stages if s["primaryentitytypecode"] == "opportunity"}

print(f"  Old opportunity stages: {list(old_opp_stages.keys())}")
print(f"  New opportunity stages: {list(new_opp_stages.keys())}")

if not old_opp_stages or not new_opp_stages:
    print("\n  WARNING: could not find opportunity-specific stages.")
    print("  Falling back to all stages for both BPFs.")
    old_opp_stages = {s["stagename"].lower(): s["processstageid"] for s in old_stages}
    new_opp_stages  = {s["stagename"].lower(): s["processstageid"] for s in new_stages}

# Map old stage ID → new stage ID by position (first old → first new, etc.)
old_ids_ordered = [s["processstageid"] for s in old_stages
                   if s["primaryentitytypecode"] in ("opportunity", "")]
new_ids_ordered = [s["processstageid"] for s in new_stages
                   if s["primaryentitytypecode"] in ("opportunity", "")]

# Also build a name-based map for known stage names
STAGE_NAME_MAP = {
    "qualify":  None,
    "develop":  None,
    "propose":  None,
    "close":    None,
}
for old_name in list(STAGE_NAME_MAP.keys()):
    old_id = next((v for k, v in old_opp_stages.items() if old_name in k), None)
    # Map to new stage by index position
    if old_id and old_id in old_ids_ordered:
        idx = old_ids_ordered.index(old_id)
        new_id = new_ids_ordered[idx] if idx < len(new_ids_ordered) else None
        STAGE_NAME_MAP[old_name] = (old_id, new_id)

stage_id_map = {}  # old stage ID → new stage ID
for name, val in STAGE_NAME_MAP.items():
    if val:
        old_id, new_id = val
        if old_id and new_id:
            stage_id_map[old_id] = new_id
            print(f"  Mapped: {name} ({old_id[:8]}...) → ({new_id[:8]}...)")

# Default: first new opportunity stage
default_new_stage = next(iter(new_opp_stages.values()), None) if new_opp_stages else new_ids_ordered[0] if new_ids_ordered else None
print(f"\n  Default new stage for unmapped: {default_new_stage}\n")

# ── Step 3: Find opportunities on the old BPF ───────────────────────────────
print("Step 3: Finding opportunities on old BPF...")
all_opps = []
url = f"{DYNAMICS_URL}/api/data/v9.2/opportunities"
params = {
    "$select": "opportunityid,name,_stageid_value,stageid",
    "$filter": f"_processid_value eq {old_bpf_id} and statecode eq 0",
    "$top": 1000,
}
while url:
    r = requests.get(url, headers=get_headers(), params=params, timeout=30)
    data = r.json()
    if not r.ok:
        print(f"  Error: {r.status_code} {r.text[:300]}")
        exit(1)
    all_opps.extend(data.get("value", []))
    url = data.get("@odata.nextLink")
    params = None

print(f"  Found {len(all_opps)} open opportunities on old BPF\n")

if not all_opps:
    # Try without processid filter — show sample to diagnose
    print("  Checking sample opportunities to diagnose BPF field name...")
    r_sample = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/opportunities",
        headers=get_headers(),
        params={"$top": 2, "$select": "opportunityid,name"},
        timeout=30,
    )
    if r_sample.ok and r_sample.json().get("value"):
        opp = r_sample.json()["value"][0]
        opp_id = opp["opportunityid"]
        # Fetch full record to see process fields
        r_full = requests.get(
            f"{DYNAMICS_URL}/api/data/v9.2/opportunities({opp_id})",
            headers=get_headers(),
            timeout=30,
        )
        if r_full.ok:
            fields = {k: v for k, v in r_full.json().items()
                      if any(x in k.lower() for x in ["process", "stage", "bpf"])
                      and not k.startswith("@")}
            print(f"  Sample opp '{opp['name']}' process/stage fields:")
            for k, v in fields.items():
                print(f"    {k}: {v}")
    print("\n  No opportunities to migrate.")
    exit(0)

# ── Step 4: Batch migrate ────────────────────────────────────────────────────
print("Step 4: Migrating opportunities to new BPF...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(all_opps) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(all_opps), BATCH_SIZE), 1):
    batch = all_opps[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for opp in batch:
        old_stage_id = opp.get("_stageid_value") or opp.get("stageid")
        new_stage_id = stage_id_map.get(old_stage_id, default_new_stage)
        oid = opp["opportunityid"]
        payload = (
            f'{{"processid@odata.bind":"/workflows({new_bpf_id})",'
            f'"stageid@odata.bind":"/processstages({new_stage_id})"}}'
        )
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
        fail = len(batch) - ok
        updated += ok
        errors += fail
        print(f"  Batch {batch_num}/{total_batches}: {ok} migrated, {fail} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:150]}")
    time.sleep(1)

print(f"\nDone. Migrated: {updated}, Errors: {errors}")
