# Find all fields on the Special Terms Approvals table
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get

# Fetch one record with all fields to see what's available
result = crm_get("tyr_specialtermsapprovalses", {
    "$top": 1,
})
records = result.get("value", [])
if not records:
    print("No records found.")
else:
    rec = records[0]
    print("All fields on Special Terms Approvals:")
    for k, v in sorted(rec.items()):
        print(f"  {k}: {repr(v)[:80]}")
