"""
Add a "Closed" stage to the end of the Lead to Opportunity BPF.
Handles the Microsoft.Crm.Workflow.ObjectModel nested StageStep format.
Safe to re-run: skips if "Closed" stage already exists.
"""
import os, json, uuid, re, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

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


def all_numeric_ids(obj):
    """Collect all numeric suffixes from id fields like 'StageStep3', 'StepStep4'."""
    ids = []
    if isinstance(obj, dict):
        raw = obj.get("id", "")
        m = re.search(r"(\d+)$", str(raw))
        if m:
            ids.append(int(m.group(1)))
        for v in obj.values():
            ids.extend(all_numeric_ids(v))
    elif isinstance(obj, list):
        for item in obj:
            ids.extend(all_numeric_ids(item))
    return ids


# ── Step 1: Fetch the active Lead to Opportunity BPF ──────────────────────────
print("Step 1: Fetching BPF...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,clientdata,statecode",
        "$filter": "category eq 4 and contains(name,'Lead to Opportunity') and statecode eq 1",
        "$orderby": "createdon desc",
        "$top": 1,
    },
    timeout=30,
)
resp.raise_for_status()
bpfs = resp.json().get("value", [])
if not bpfs:
    print("ERROR: No active 'Lead to Opportunity' BPF found.")
    exit(1)

bpf        = bpfs[0]
bpf_id     = bpf["workflowid"]
bpf_name   = bpf["name"]
clientdata = bpf.get("clientdata") or ""
print(f"  Name: {bpf_name}")
print(f"  ID:   {bpf_id}")
print(f"  Size: {len(clientdata)} chars\n")

data = json.loads(clientdata)


# ── Step 2: Navigate to the EntityStep's steps list ───────────────────────────
print("Step 2: Locating stage list...")

entity_step = None
for item in data.get("steps", {}).get("list", []):
    if item.get("__class", "").startswith("EntityStep"):
        entity_step = item
        break

if not entity_step:
    print("ERROR: Could not find EntityStep in clientdata.")
    exit(1)

stage_list = entity_step["steps"]["list"]
stage_steps = [s for s in stage_list if s.get("__class", "").startswith("StageStep")]
print(f"  Found {len(stage_steps)} stage(s):")
for s in stage_steps:
    labels = s.get("stepLabels", {}).get("list", [])
    label  = labels[0].get("description", "(no label)") if labels else s.get("description", "(no label)")
    print(f"    [{s['id']}] {label.strip()}")
print()


# ── Step 3: Guard — skip if Closed already exists ─────────────────────────────
for s in stage_steps:
    labels = s.get("stepLabels", {}).get("list", [])
    label  = (labels[0].get("description", "") if labels else s.get("description", "")).strip().lower()
    if label == "closed":
        print("  'Closed' stage already exists — nothing to do.")
        exit(0)


# ── Step 4: Build the new Closed StageStep ────────────────────────────────────
print("Step 3: Building 'Closed' stage...")

# Find highest numeric ID used anywhere in the definition so we don't collide
max_id    = max(all_numeric_ids(data), default=100)
new_num   = max_id + 1
stage_id  = f"StageStep{new_num}"
step_name = f"Step_{new_num}"

# The labelId is also the processstageid Dynamics registers for this stage
label_id  = str(uuid.uuid4())

new_stage = {
    "__class":    "StageStep:#Microsoft.Crm.Workflow.ObjectModel",
    "id":         stage_id,
    "description":"Closed",
    "name":       step_name,
    "stepLabels": {
        "list": [
            {
                "labelId":      label_id,
                "languageCode": 1033,
                "description":  "Closed",
            }
        ]
    },
    "steps": {"list": []},
}

stage_list.append(new_stage)
print(f"  New stage id:    {stage_id}")
print(f"  New labelId:     {label_id}")
print()

fixed = json.dumps(data, separators=(",", ":"))
print(f"  Updated def size: {len(fixed)} chars\n")


# ── Step 5: Register the processstage record ──────────────────────────────────
print("Step 4: Creating processstage record...")
ps_payload = {
    "processstageid":           label_id,
    "stagename":                "Closed",
    "stagecategory":            4,
    "processid@odata.bind":     f"/workflows({bpf_id})",
}
r_ps = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    json=ps_payload,
    timeout=30,
)
if r_ps.status_code in (201, 204):
    print(f"  processstage created ({label_id})")
elif r_ps.status_code == 409 or "duplicate" in r_ps.text.lower():
    print(f"  processstage already exists — continuing.")
else:
    print(f"  WARNING ({r_ps.status_code}): {r_ps.text[:200]}")
    print("  Continuing — clientdata patch may still work.\n")
print()


# ── Step 6: Deactivate BPF ────────────────────────────────────────────────────
print("Step 5: Deactivating BPF...")
r = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/SetState",
    headers=get_headers(),
    json={
        "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": bpf_id},
        "State":  {"Value": 0},
        "Status": {"Value": 1},
    },
    timeout=30,
)
if not (r.ok or r.status_code == 204):
    r = requests.patch(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
        headers={**get_headers(), "If-Match": "*"},
        json={"statecode": 0, "statuscode": 1},
        timeout=30,
    )
print(f"  Deactivate: {r.status_code}")
time.sleep(3)


# ── Step 7: Patch clientdata ───────────────────────────────────────────────────
print("Step 6: Patching clientdata...")
r = requests.patch(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
    headers={**get_headers(), "If-Match": "*"},
    json={"clientdata": fixed},
    timeout=30,
)
print(f"  Patch: {r.status_code}")
if not (r.ok or r.status_code == 204):
    print(f"  ERROR: {r.text[:400]}")
    # Reactivate without changes so BPF isn't left dormant
    requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/SetState",
        headers=get_headers(),
        json={
            "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": bpf_id},
            "State":  {"Value": 1},
            "Status": {"Value": 2},
        },
        timeout=30,
    )
    print("  BPF reactivated without changes.")
    exit(1)
time.sleep(3)


# ── Step 8: Reactivate BPF ────────────────────────────────────────────────────
print("Step 7: Reactivating BPF...")
r = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/SetState",
    headers=get_headers(),
    json={
        "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": bpf_id},
        "State":  {"Value": 1},
        "Status": {"Value": 2},
    },
    timeout=30,
)
if not (r.ok or r.status_code == 204):
    r = requests.patch(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
        headers={**get_headers(), "If-Match": "*"},
        json={"statecode": 1, "statuscode": 2},
        timeout=30,
    )
print(f"  Activate: {r.status_code}\n")

if r.ok or r.status_code == 204:
    print("=" * 60)
    print("SUCCESS — 'Closed' stage added.")
    print("Refresh the lead form to see: New → Contacting → Engaged → Qualified → Closed")
    print("=" * 60)
else:
    print(f"WARNING: Reactivation failed ({r.status_code}): {r.text[:300]}")
    print("BPF is currently inactive — reactivate manually in CRM.")
