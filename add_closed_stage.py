"""
Add a "Closed" processstage record to the Lead to Opportunity BPF.
The clientdata was already patched; this script creates the missing
processstage record (which is what Dynamics 365 reads to render
the stage bubbles in the BPF bar).

Safe to re-run: skips if "Closed" stage already exists.
"""
import os, json, uuid, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
BPF_ID = "c4096776-49c9-40e8-a51b-0569d1bfef45"

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


# ── Step 1: Get existing processstages for this BPF ───────────────────────────
print("Step 1: Fetching existing processstages...")
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    params={
        "$select": "processstageid,stagename,stagecategory,primaryentitytypecode",
        "$filter": f"_processid_value eq {BPF_ID}",
        "$orderby": "stagecategory asc",
    },
    timeout=30,
)
r.raise_for_status()
stages = r.json().get("value", [])
print(f"  Found {len(stages)} existing stage(s):")
for s in stages:
    print(f"    [{s.get('stagecategory')}] {s['stagename']} "
          f"(typecode={s.get('primaryentitytypecode')}) — {s['processstageid']}")

# Guard: skip if Closed already exists
if any(s["stagename"].lower() == "closed" for s in stages):
    print("\n  'Closed' stage already exists — nothing to do.")
    exit(0)

# Get primaryentitytypecode from an existing stage
typecode = next(
    (s.get("primaryentitytypecode") for s in stages if s.get("primaryentitytypecode")),
    None,
)
if typecode is None:
    # Lead entity object type code in Dynamics 365 is 4
    typecode = 4
    print(f"  Could not read typecode from existing stages; defaulting to {typecode} (lead).")
else:
    print(f"\n  Using primaryentitytypecode={typecode} (from existing stages)")

# Determine next stagecategory value (just use max + 1, or 4 if all are 4)
existing_categories = [s.get("stagecategory") or 0 for s in stages]
last_category = max(existing_categories) if existing_categories else 3
# Keep same category as the last stage (Qualify = 4 in BPF terms)
new_category = last_category
print(f"  Using stagecategory={new_category}")


# ── Step 2: Create the Closed processstage ────────────────────────────────────
print("\nStep 2: Creating 'Closed' processstage record...")
new_stage_id = str(uuid.uuid4())

payload = {
    "processstageid":            new_stage_id,
    "stagename":                 "Closed",
    "stagecategory":             new_category,
    "primaryentitytypecode":     typecode,
    "processid@odata.bind":      f"/workflows({BPF_ID})",
}
r = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    json=payload,
    timeout=30,
)
print(f"  Response: {r.status_code}")
if r.status_code in (201, 204):
    print(f"  Created processstage: {new_stage_id}")
else:
    print(f"  ERROR: {r.text[:400]}")
    exit(1)


# ── Step 3: Patch clientdata to add a StageStep for Closed ────────────────────
print("\nStep 3: Adding StageStep to BPF clientdata...")

resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({BPF_ID})",
    headers=get_headers(),
    params={"$select": "clientdata,statecode"},
    timeout=30,
)
resp.raise_for_status()
bpf_data   = resp.json()
clientdata = bpf_data.get("clientdata") or ""
data       = json.loads(clientdata)

# Find the EntityStep
entity_step = None
for item in data.get("steps", {}).get("list", []):
    if item.get("__class", "").startswith("EntityStep"):
        entity_step = item
        break

if not entity_step:
    print("  WARNING: EntityStep not found — skipping clientdata patch.")
else:
    # Check if Closed StageStep already present
    stage_list  = entity_step["steps"]["list"]
    stage_steps = [s for s in stage_list if s.get("__class", "").startswith("StageStep")]
    already_has_closed = any(
        (s.get("stepLabels", {}).get("list") or [{}])[0].get("description", "").strip().lower() == "closed"
        for s in stage_steps
    )

    if already_has_closed:
        print("  StageStep for 'Closed' already in clientdata — skipping.")
    else:
        # Find max numeric ID in the whole definition
        import re
        all_ids = [int(m) for m in re.findall(r'"id"\s*:\s*"[A-Za-z]+(\d+)"', clientdata)]
        next_num  = max(all_ids, default=50) + 1
        stage_id  = f"StageStep{next_num}"

        new_stage_step = {
            "__class":    "StageStep:#Microsoft.Crm.Workflow.ObjectModel",
            "id":         stage_id,
            "description":"Closed",
            "name":       f"Step_{next_num}",
            "stepLabels": {
                "list": [{
                    "labelId":      new_stage_id,
                    "languageCode": 1033,
                    "description":  "Closed",
                }]
            },
            "steps": {"list": []},
        }
        stage_list.append(new_stage_step)
        fixed = json.dumps(data, separators=(",", ":"))

        # Deactivate → patch → reactivate
        print("  Deactivating BPF...")
        r = requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/SetState",
            headers=get_headers(),
            json={
                "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": BPF_ID},
                "State": {"Value": 0}, "Status": {"Value": 1},
            },
            timeout=30,
        )
        print(f"    Deactivate: {r.status_code}")
        time.sleep(3)

        print("  Patching clientdata...")
        r = requests.patch(
            f"{DYNAMICS_URL}/api/data/v9.2/workflows({BPF_ID})",
            headers={**get_headers(), "If-Match": "*"},
            json={"clientdata": fixed},
            timeout=30,
        )
        print(f"    Patch: {r.status_code}")
        if not (r.ok or r.status_code == 204):
            print(f"    ERROR: {r.text[:300]}")
        time.sleep(3)

        print("  Reactivating BPF...")
        r = requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/SetState",
            headers=get_headers(),
            json={
                "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": BPF_ID},
                "State": {"Value": 1}, "Status": {"Value": 2},
            },
            timeout=30,
        )
        print(f"    Activate: {r.status_code}")


print()
print("=" * 60)
print("Done. Refresh the lead form in Dynamics 365.")
print("You should see: New → Contacting → Engaged → Qualified → Closed")
print("=" * 60)
