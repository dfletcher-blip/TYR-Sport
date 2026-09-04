#!/usr/bin/env python3
"""
Find the field name for 'Sales Representative' on accounts.
Run: python diagnose_account_fields.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get

# Fetch one account (Foot Locker) and print all its fields
# Fetch without $select so ALL fields are returned
print("=== Foot Locker account — all fields ===")
accts = crm_get("accounts", {
    "$filter": "name eq 'FOOT LOCKER'",
    "$top": 1,
}).get("value", [])

if not accts:
    print("Foot Locker not found, fetching first account instead...")
    accts = crm_get("accounts", {"$top": 1}).get("value", [])

if accts:
    a = accts[0]
    print(f"Account: {a.get('name')}")
    print("\nAll fields with values:")
    for k, v in sorted(a.items()):
        if v is not None and v != "":
            print(f"  {k}: {v}")
    print("\nAll lookup fields (_value suffix) including nulls:")
    for k, v in sorted(a.items()):
        if k.endswith("_value") or "owner" in k.lower() or "rep" in k.lower() or "assign" in k.lower() or "tyr_" in k.lower():
            print(f"  {k}: {v}")

    print("\nExpanded ownerid:")
    print(f"  {a.get('ownerid')}")
