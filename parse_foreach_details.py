"""
Follow-up to diagnose_full_account_flow_structure.py -- that script's
generic printer didn't know how to expand Foreach ("Apply_to_each" /
"Apply_to_each_1") actions, which is almost certainly where the actual
per-value copy/mapping logic lives (the loop body that pushes values
into the 'Tyr Type' / 'Business Type' array variables).

Reads the already-saved account_tyrtype_flow_FULL.json (no network call
needed) and prints the full foreach expression + nested action bodies
for both loops, untruncated.

Read-only against the local file. Makes no changes anywhere.

Usage:
    python parse_foreach_details.py
"""
import json

LOCAL_FILE = "account_tyrtype_flow_FULL.json"

with open(LOCAL_FILE) as f:
    parsed = json.load(f)

definition = parsed.get("properties", {}).get("definition", parsed)
actions = definition.get("actions", {})

def find_action(tree, name):
    for aname, abody in tree.items():
        if aname == name:
            return abody
        atype = abody.get("type")
        if atype == "If":
            for branch_key in ("actions",):
                sub = abody.get(branch_key, {})
                found = find_action(sub, name)
                if found:
                    return found
            else_sub = abody.get("else", {}).get("actions", {})
            found = find_action(else_sub, name)
            if found:
                return found
        if atype == "Switch":
            for case_body in abody.get("cases", {}).values():
                found = find_action(case_body.get("actions", {}), name)
                if found:
                    return found
            found = find_action(abody.get("default", {}).get("actions", {}), name)
            if found:
                return found
    return None

for loop_name in ("Apply_to_each", "Apply_to_each_1"):
    body = find_action(actions, loop_name)
    print("=" * 70)
    print(loop_name)
    print("=" * 70)
    if body is None:
        print("  ! Not found.")
        print()
        continue
    print(f"  type: {body.get('type')}")
    print(f"  foreach: {body.get('foreach')}")
    print(f"  runAfter: {body.get('runAfter')}")
    print()
    print("  nested actions (full, untruncated):")
    print(json.dumps(body.get("actions", {}), indent=4))
    print()

print("Done. This is read-only -- nothing was changed.")
