"""
Add a "Closed" stage to the end of the Lead to Opportunity BPF.
Follows the same deactivate → patch clientdata → reactivate pattern
used by fix_bpf_errors.py.

Safe to re-run: skips if "Closed" stage already exists.
"""
import os, json, uuid, requests, time
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


# ── Step 1: Fetch the active Lead to Opportunity BPF ──────────────────────────
print("Step 1: Fetching BPF...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,clientdata,statecode,ismanaged",
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

bpf       = bpfs[0]
bpf_id    = bpf["workflowid"]
bpf_name  = bpf["name"]
clientdata = bpf.get("clientdata") or ""
print(f"  Name:    {bpf_name}")
print(f"  ID:      {bpf_id}")
print(f"  Managed: {bpf.get('ismanaged')}")
print(f"  Def size:{len(clientdata)} chars\n")

if not clientdata:
    print("ERROR: clientdata is empty — cannot modify.")
    exit(1)


# ── Step 2: Parse the clientdata and inspect stage structure ───────────────────
print("Step 2: Parsing clientdata...")
try:
    data = json.loads(clientdata)
except json.JSONDecodeError as e:
    print(f"ERROR: Could not parse clientdata as JSON: {e}")
    exit(1)

# Dynamics 365 BPF clientdata can use either a "stages" dict keyed by GUID
# or a top-level list. Detect which format we have.
stages_raw = data.get("stages")
stage_order = data.get("stageOrder") or data.get("StageOrder") or []

if isinstance(stages_raw, dict):
    # Format A: {"stages": {"<guid>": {...}}, "stageOrder": [...]}
    fmt = "dict"
    print(f"  Stage format: dict ({len(stages_raw)} stages)")
    for sid, s in stages_raw.items():
        name = s.get("DisplayName") or s.get("displayName") or s.get("name") or "(unnamed)"
        order = s.get("stepOrder") or s.get("order") or "?"
        print(f"    [{order}] {name} ({sid[:8]}...)")
elif isinstance(stages_raw, list):
    # Format B: {"stages": [{"stageId": "...", ...}, ...]}
    fmt = "list"
    print(f"  Stage format: list ({len(stages_raw)} stages)")
    for s in stages_raw:
        sid   = s.get("stageId") or s.get("id") or "?"
        name  = s.get("DisplayName") or s.get("displayName") or s.get("stageName") or "(unnamed)"
        order = s.get("stepOrder") or s.get("order") or "?"
        print(f"    [{order}] {name} ({str(sid)[:8]}...)")
else:
    print(f"  WARNING: Unexpected stages structure type: {type(stages_raw)}")
    print("  Top-level keys:", list(data.keys())[:20])
    fmt = "unknown"

print()


# ── Step 3: Guard — skip if "Closed" already exists ───────────────────────────
def stage_names(data, fmt):
    if fmt == "dict":
        return [
            (s.get("DisplayName") or s.get("displayName") or s.get("name") or "").lower()
            for s in data["stages"].values()
        ]
    if fmt == "list":
        return [
            (s.get("DisplayName") or s.get("displayName") or s.get("stageName") or "").lower()
            for s in data["stages"]
        ]
    return []

if "closed" in stage_names(data, fmt):
    print("  'Closed' stage already exists — nothing to do.")
    exit(0)


# ── Step 4: Build the new "Closed" stage and append it ────────────────────────
print("Step 3: Adding 'Closed' stage...")
new_stage_id = str(uuid.uuid4())

if fmt == "dict":
    existing_orders = [
        s.get("stepOrder") or s.get("order") or 0
        for s in data["stages"].values()
    ]
    next_order = max((o for o in existing_orders if isinstance(o, int)), default=4) + 1

    # Copy structure from the last stage as a template, then clear its steps
    last_stage_id = stage_order[-1] if stage_order else list(data["stages"].keys())[-1]
    template = dict(data["stages"].get(last_stage_id, {}))

    new_stage = {
        "DisplayName":       "Closed",
        "EntityLogicalName": template.get("EntityLogicalName", "lead"),
        "stepOrder":         next_order,
        "steps":             {},
    }
    data["stages"][new_stage_id] = new_stage
    if isinstance(stage_order, list):
        data["stageOrder"] = stage_order + [new_stage_id]
    print(f"  Added stage '{new_stage['DisplayName']}' as order {next_order} (id {new_stage_id[:8]}...)")

elif fmt == "list":
    existing_orders = [
        s.get("stepOrder") or s.get("order") or 0
        for s in data["stages"]
    ]
    next_order = max((o for o in existing_orders if isinstance(o, int)), default=4) + 1

    template = data["stages"][-1] if data["stages"] else {}
    new_stage = {
        "stageId":           new_stage_id,
        "DisplayName":       "Closed",
        "displayName":       "Closed",
        "EntityLogicalName": template.get("EntityLogicalName", "lead"),
        "stepOrder":         next_order,
        "steps":             [],
    }
    data["stages"].append(new_stage)
    print(f"  Added stage 'Closed' as order {next_order} (id {new_stage_id[:8]}...)")

else:
    print("ERROR: Cannot add stage to unrecognised clientdata structure.")
    print("  Dumping first 2000 chars of clientdata for inspection:")
    print(clientdata[:2000])
    exit(1)

fixed = json.dumps(data, separators=(",", ":"))
print(f"  New def size: {len(fixed)} chars\n")


# ── Step 5: Also create a processstage record so Dynamics tracks the stage ────
print("Step 4: Creating processstage record in CRM...")
ps_payload = {
    "processstageid": new_stage_id,
    "stagename":      "Closed",
    "stagecategory":  4,   # 4 = Qualify (last meaningful stage; no standard "closed" category)
    "processid@odata.bind": f"/workflows({bpf_id})",
}
r_ps = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    json=ps_payload,
    timeout=30,
)
if r_ps.status_code in (201, 204):
    print(f"  processstage created: {new_stage_id}")
elif r_ps.status_code == 400 and "duplicate" in r_ps.text.lower():
    print(f"  processstage already exists — continuing.")
else:
    print(f"  WARNING: processstage create returned {r_ps.status_code}: {r_ps.text[:200]}")
    print("  Continuing anyway — the clientdata patch may still work.\n")
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
    # Try to reactivate before exiting so the BPF isn't left dormant
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
    print("  BPF reactivated (without changes). Exiting.")
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
    print("SUCCESS — 'Closed' stage added to the BPF.")
    print("Refresh the lead form in Dynamics 365 to see the new stage.")
    print("=" * 60)
else:
    print(f"WARNING: Reactivation failed ({r.status_code}): {r.text[:300]}")
    print("BPF is currently inactive — reactivate manually in the CRM.")
