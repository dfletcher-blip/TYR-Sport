"""Quick diagnostic — shows the Run Specialty Dashboard record details."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import crm_get

result = crm_get("systemforms", {
    "$filter": "name eq 'Run Specialty Dashboard' and type eq 0",
    "$select": "formid,name,formactivationstate,objecttypecode,iscustomizable,ismanaged",
    "$top": 5,
})
rows = result.get("value", [])
if not rows:
    print("NOT FOUND in systemforms")
else:
    for r in rows:
        print(r)
