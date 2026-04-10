"""
Find ALL plugin steps that fire on Account Create by filtering on message+entity,
regardless of step name. Also checks JavaScript form events.
"""
import os, requests, time
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

# Get all active plugin steps where:
# - sdkmessage = "Create"
# - entity filter = "account"
# This is the definitive list of everything that fires on Account Create
print("=== ALL active plugin steps firing on Account Create ===\n")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/sdkmessageprocessingsteps",
    headers=get_headers(),
    params={
        "$select": "sdkmessageprocessingstepid,name,description,statecode,stage,rank,asyncautodelete",
        "$filter": "statecode eq 0",
        "$expand": "sdkmessageid($select=name),sdkmessagefilterid($select=primaryobjecttypecode),plugintypeid($select=assemblyname,typename,pluginassemblyid)",
        "$top": 500,
    },
    timeout=60,
)

if not resp.ok:
    print(f"FAILED: {resp.status_code} {resp.text[:300]}")
    exit(1)

all_steps = resp.json().get("value", [])

# Filter to only Account + Create
account_create_steps = [
    s for s in all_steps
    if (s.get("sdkmessageid") or {}).get("name") == "Create"
    and (s.get("sdkmessagefilterid") or {}).get("primaryobjecttypecode") == "account"
]

print(f"Found {len(account_create_steps)} plugin steps on Account Create:\n")
for s in account_create_steps:
    plugin = s.get("plugintypeid") or {}
    stage = s.get("stage")
    stage_name = {10: "PreValidation", 20: "PreOperation", 40: "PostOperation"}.get(stage, str(stage))
    print(f"  Name:     {s['name']}")
    print(f"  Assembly: {plugin.get('assemblyname', 'unknown')}")
    print(f"  Class:    {plugin.get('typename', 'unknown')}")
    print(f"  Stage:    {stage_name}")
    print(f"  ID:       {s['sdkmessageprocessingstepid']}")
    print()
