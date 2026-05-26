#!/usr/bin/env python3
"""Quick script to find the actual entity name for Special Terms Agreements."""

from config.crm_connection import crm_get

# Search metadata for any entity with "special" or "term" in its name
try:
    meta = crm_get("EntityDefinitions", {
        "$select": "LogicalName,LogicalCollectionName,DisplayName",
        "$filter": "IsCustomEntity eq true",
        "$top": 500,
    })
    entities = meta.get("value", [])
    print(f"Total custom entities: {len(entities)}\n")
    print("Entities with 'special', 'term', or 'str' in their name:")
    for e in entities:
        name = e.get("LogicalName", "").lower()
        coll = e.get("LogicalCollectionName", "").lower()
        label = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "").lower()
        if any(k in name or k in coll or k in label for k in ["special", "term", " str", "_str"]):
            print(f"  LogicalName: {e['LogicalName']}")
            print(f"  Collection:  {e.get('LogicalCollectionName','?')}")
            print(f"  Display:     {((e.get('DisplayName') or {}).get('UserLocalizedLabel') or {}).get('Label','?')}")
            print()
except Exception as e:
    print(f"Error: {e}")
