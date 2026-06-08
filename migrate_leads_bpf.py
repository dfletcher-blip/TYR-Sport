"""
Migrate existing leads from old BPF to new Copy BPF with stage mapping:
  Qualify  → New
  Develop  → Contacting
  Propose  → Engaged
  Close    → Qualified
"""
import os, uuid, time, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

STAGE_MAP = {
    "qualify":  "new",
    "develop":  "contacting",
    "propose":  "engaged",
    "close":    "qualified",
}

_token = {"value": None, "expires": 0}

def get_headers():
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

# --- Step 1: Get both BPFs ---
print("Step 1: Finding BPFs...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,createdon",
        "$filter": "category eq 4 and contains(name,'Lead to Opportunity') and statecode eq 1",
        "$orderby": "createdon asc",
        "$top": 10,
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
print(f"\n  Old BPF: {old_bpf['name']} ({old_bpf_id})")
print(f"  New BPF: {new_bpf['name']} ({new_bpf_id})\n")

# --- Step 2: Get stage IDs for both BPFs ---
def get_stages(bpf_id):
    r = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/processstages",
        headers=get_headers(),
        params={
            "$select": "processstageid,stagename",
            "$filter": f"_processid_value eq {bpf_id}",
        },
        timeout=30,
    )
    return {s["stagename"].lower(): s["processstageid"] for s in r.json().get("value", [])}

print("Step 2: Getting stage IDs...")
old_stages = get_stages(old_bpf_id)
new_stages = get_stages(new_bpf_id)
print(f"  Old stages: {old_stages}")
print(f"  New stages: {new_stages}\n")

# Build old stage ID → new stage ID map
stage_id_map = {}
for old_name, new_name in STAGE_MAP.items():
    old_id = next((v for k, v in old_stages.items() if old_name in k.lower()), None)
    new_id = next((v for k, v in new_stages.items() if new_name in k.lower()), None)
    if old_id and new_id:
        stage_id_map[old_id] = new_id
        print(f"  Mapped: {old_name} ({old_id[:8]}...) → {new_name} ({new_id[:8]}...)")
    else:
        print(f"  WARNING: Could not map '{old_name}' → '{new_name}' (old found: {bool(old_id)}, new found: {bool(new_id)})")

default_new_stage = next((v for k, v in new_stages.items() if "new" in k.lower()), None)
print(f"\n  Default stage for unmapped leads: New ({default_new_stage})\n")

# --- Step 3: Get all leads on old BPF ---
print("Step 3: Getting leads on old BPF...")
all_leads = []
url = f"{DYNAMICS_URL}/api/data/v9.2/leads"
params = {
    "$select": "leadid,fullname,stageid",
    "$filter": f"_processid_value eq {old_bpf_id}",
    "$top": 1000,
}
while url:
    r = requests.get(url, headers=get_headers(), params=params, timeout=30)
    data = r.json()
    all_leads.extend(data.get("value", []))
    url = data.get("@odata.nextLink")
    params = None

print(f"  Found {len(all_leads)} leads to migrate\n")

if not all_leads:
    print("No leads to migrate.")
    exit(0)

# --- Step 4: Batch migrate via PATCH ---
print("Step 4: Migrating leads to new BPF...")
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(all_leads) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(all_leads), BATCH_SIZE), 1):
    batch = all_leads[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"

    parts = []
    for lead in batch:
        old_stage_id = lead.get("_stageid_value") or lead.get("stageid")
        new_stage_id = stage_id_map.get(old_stage_id, default_new_stage)
        lid = lead["leadid"]
        payload = (
            f'{{"processid@odata.bind":"/workflows({new_bpf_id})",'
            f'"stageid@odata.bind":"/processstages({new_stage_id})"}}'
        )
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/leads({lid}) HTTP/1.1\r\n"
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

print(f"\nDone.")
print(f"  Migrated: {updated}")
print(f"  Errors:   {errors}")

# --- Step 5: Deactivate old BPF so new leads default to the new one ---
if errors == 0:
    print("\nStep 5: Deactivating old BPF...")
    r = requests.patch(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows({old_bpf_id})",
        headers=get_headers(),
        json={"statecode": 0, "statuscode": 1},  # Draft = inactive
        timeout=30,
    )
    if r.status_code in (200, 204):
        print("  Old BPF deactivated. New leads will use the new BPF.")
    else:
        print(f"  WARNING: Could not deactivate old BPF: {r.status_code} {r.text[:150]}")
        print("  Deactivate it manually in Dynamics 365 > Settings > Process Center.")
else:
    print("\nStep 5: Skipping old BPF deactivation due to migration errors — fix errors first.")
