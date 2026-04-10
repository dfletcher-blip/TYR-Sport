"""
Deep inspect the plugin steps that fire on Account Create to find the one creating opportunities.
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

# Get full details on plugin steps that fire on Account Create
# Expand sdkmessage (message name), sdkmessagefilter (entity), plugintype (assembly)
print("Getting detailed plugin steps for Account Create...\n")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/sdkmessageprocessingsteps",
    headers=get_headers(),
    params={
        "$select": "sdkmessageprocessingstepid,name,description,statecode,stage,rank",
        "$filter": "statecode eq 0 and contains(name,'ccount') and contains(name,'reate')",
        "$expand": "sdkmessageid($select=name),sdkmessagefilterid($select=primaryobjecttypecode),plugintypeid($select=assemblyname,typename)",
        "$top": 50,
    },
    timeout=30,
)

if not resp.ok:
    print(f"FAILED: {resp.status_code} {resp.text[:300]}")
    exit(1)

steps = resp.json().get("value", [])
print(f"Found {len(steps)} steps:\n")

for s in steps:
    msg = s.get("sdkmessageid") or {}
    filt = s.get("sdkmessagefilterid") or {}
    plugin = s.get("plugintypeid") or {}
    print(f"Name:     {s['name']}")
    print(f"ID:       {s['sdkmessageprocessingstepid']}")
    print(f"Message:  {msg.get('name', 'unknown')}")
    print(f"Entity:   {filt.get('primaryobjecttypecode', 'unknown')}")
    print(f"Assembly: {plugin.get('assemblyname', 'unknown')}")
    print(f"Class:    {plugin.get('typename', 'unknown')}")
    print(f"Stage:    {s.get('stage')} (10=PreValidation, 20=PreOperation, 40=PostOperation)")
    print(f"State:    {'Active' if s.get('statecode') == 0 else 'Inactive'}")
    print()
