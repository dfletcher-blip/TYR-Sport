#!/usr/bin/env python3
# Diagnose why tyr_tyrtype / tyr_tyrentity are not sticking on contacts.
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_patch

# ── 1. Fetch Michael Wheeler's raw contact record ──────────────────────────
print("=== Contact: Michael Wheeler ===")
result = crm_get("contacts", {
    "$filter": "fullname eq 'Michael Wheeler'",
    "$select": "contactid,fullname,tyr_tyrtype,tyr_tyrentity,_parentcustomerid_value",
    "$top": 5,
})
contacts = result.get("value", [])
if not contacts:
    print("Contact not found.")
    sys.exit(1)

c = contacts[0]
contact_id = c["contactid"]
acct_id = c.get("_parentcustomerid_value")
print(f"  contactid:              {contact_id}")
print(f"  tyr_tyrtype (current):  {c.get('tyr_tyrtype')!r}")
print(f"  tyr_tyrentity (current):{c.get('tyr_tyrentity')!r}")
print(f"  parent account id:      {acct_id}")

# ── 2. Fetch the parent account raw fields ─────────────────────────────────
print("\n=== Parent Account ===")
acct = crm_get("accounts", {
    "$filter": f"accountid eq '{acct_id}'",
    "$select": "accountid,name,tyr_tyrtype,tyr_tyrentity",
    "$top": 1,
}).get("value", [{}])[0]
print(f"  name:                   {acct.get('name')!r}")
print(f"  tyr_tyrtype (account):  {acct.get('tyr_tyrtype')!r}")
print(f"  tyr_tyrentity (account):{acct.get('tyr_tyrentity')!r}")

# ── 3. Try a test PATCH and read back ──────────────────────────────────────
acct_tyrtype  = acct.get("tyr_tyrtype")
acct_tyrentity = acct.get("tyr_tyrentity")

if acct_tyrtype is None and acct_tyrentity is None:
    print("\nAccount has no tyr values to copy — nothing to patch.")
    sys.exit(0)

patch_body = {}
if acct_tyrtype is not None:
    # If multi-select string, take first value as int
    if isinstance(acct_tyrtype, str) and "," in acct_tyrtype:
        patch_body["tyr_tyrtype"] = int(acct_tyrtype.split(",")[0].strip())
    else:
        patch_body["tyr_tyrtype"] = acct_tyrtype
if acct_tyrentity is not None:
    patch_body["tyr_tyrentity"] = acct_tyrentity

print(f"\n=== PATCH payload ===\n  {patch_body}")
try:
    crm_patch("contacts", contact_id, patch_body)
    print("  PATCH returned success (204)")
except Exception as e:
    print(f"  PATCH ERROR: {e}")
    sys.exit(1)

# ── 4. Read back to verify ─────────────────────────────────────────────────
print("\n=== Contact after PATCH ===")
verify = crm_get("contacts", {
    "$filter": f"contactid eq '{contact_id}'",
    "$select": "contactid,fullname,tyr_tyrtype,tyr_tyrentity",
    "$top": 1,
}).get("value", [{}])[0]
print(f"  tyr_tyrtype (after):    {verify.get('tyr_tyrtype')!r}")
print(f"  tyr_tyrentity (after):  {verify.get('tyr_tyrentity')!r}")

# ── 5. Also list all tyr_* fields on the contact entity ───────────────────
print("\n=== All tyr_ fields visible on this contact record ===")
full = crm_get(f"contacts({contact_id})", {}).get
# Re-fetch without $select to see all returned fields
raw = crm_get("contacts", {
    "$filter": f"contactid eq '{contact_id}'",
    "$top": 1,
})
rec = raw.get("value", [{}])[0]
for k, v in sorted(rec.items()):
    if k.startswith("tyr_") or "tyrtype" in k or "tyrentity" in k:
        print(f"  {k}: {v!r}")
