#!/usr/bin/env python3
"""Quick script to find the actual entity name for Special Terms Agreements."""

from config.crm_connection import crm_get

# Fetch all entity definitions and search client-side
try:
    meta = crm_get("EntityDefinitions", {
        "$select": "LogicalName,LogicalCollectionName,DisplayName",
    })
    entities = meta.get("value", [])
    print(f"Total entities: {len(entities)}\n")
    print("Entities with 'special', 'term', or 'str' in their name:")
    found = []
    for e in entities:
        name = e.get("LogicalName", "").lower()
        coll = e.get("LogicalCollectionName", "").lower()
        label = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "").lower()
        if any(k in name or k in coll or k in label for k in ["special", "term", "_str", "agreemen"]):
            found.append(e)
            print(f"  LogicalName: {e['LogicalName']}")
            print(f"  Collection:  {e.get('LogicalCollectionName', '?')}")
            print(f"  Display:     {((e.get('DisplayName') or {}).get('UserLocalizedLabel') or {}).get('Label', '?')}")
            print()
    if not found:
        print("  None found — dumping all tyr_ entities instead:\n")
        for e in entities:
            if e.get("LogicalName", "").startswith("tyr_"):
                print(f"  {e['LogicalName']}  /  {e.get('LogicalCollectionName','?')}  /  {((e.get('DisplayName') or {}).get('UserLocalizedLabel') or {}).get('Label','?')}")
except Exception as e:
    print(f"Error: {e}")
