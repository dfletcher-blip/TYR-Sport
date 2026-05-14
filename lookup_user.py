"""Look up a specific user by ID and show all their key fields."""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
USER_ID = "9230596d-3308-f111-8406-000d3a5b4f5f"

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=3,
    status_forcelist=[429,500,502,503,504], allowed_methods=["GET"])))

def get_headers():
    token = get_access_token()
    return {"Authorization": f"Bearer {token}", "OData-MaxVersion": "4.0",
            "OData-Version": "4.0", "Accept": "application/json",
            "Prefer": "odata.include-annotations=*"}

r = _session.get(
    f"{DYNAMICS_URL}/api/data/v9.2/systemusers({USER_ID})",
    headers=get_headers(),
    params={
        "$select": "fullname,internalemailaddress,isdisabled,islicensed,title,_parentsystemuserid_value",
        "$expand": "parentsystemuserid($select=systemuserid,fullname)",
    },
    timeout=30
)
if not r.ok:
    print(f"Error: {r.status_code} {r.text[:300]}")
else:
    d = r.json()
    print(f"Full name  : {d.get('fullname')}")
    print(f"Email      : {d.get('internalemailaddress')}")
    print(f"Title      : {d.get('title')}")
    print(f"Disabled   : {d.get('isdisabled')}")
    print(f"Licensed   : {d.get('islicensed')}")
    mgr = d.get("parentsystemuserid")
    print(f"Manager    : {mgr['fullname'] if mgr else 'NONE — no manager set'}")
