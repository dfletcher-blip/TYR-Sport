# ============================================================
# fix_charts.py — Direct chart fix script (no agent needed)
# Run this directly: python fix_charts.py
# ============================================================
# This script finds all pipeline/stage charts on the opportunity
# entity and changes the Y-axis from Count to Sum of Revenue.
# ============================================================

import os
from dotenv import load_dotenv
load_dotenv()

from tools.charts import list_charts, search_charts, get_chart_xml, set_chart_y_axis_to_sum

def run():
    print("\n=== TYR Sport — Pipeline Chart Fix ===\n")

    # Step 1: List all opportunity charts
    print("Fetching all opportunity charts...")
    result = list_charts("opportunity")
    charts = result.get("charts", [])
    print(f"Found {len(charts)} charts total.\n")

    # Step 2: Show all charts so you can see what's there
    for c in charts:
        print(f"  • {c['name']}  (id: {c['id']})")

    # Step 3: Find pipeline/stage charts
    print("\n--- Searching for pipeline charts to fix ---\n")
    targets = [c for c in charts if any(
        kw in c['name'].lower()
        for kw in ['pipeline', 'stage', 'close month', 'owner']
    )]

    if not targets:
        print("No pipeline/stage charts found by keyword. Checking all charts for count aggregation...\n")
        targets = charts  # Try all of them

    fixed = []
    skipped = []

    for chart in targets:
        cid  = chart['id']
        name = chart['name']
        print(f"Checking: {name}")

        xml_data = get_chart_xml(cid)
        xml = xml_data.get("data_description_xml", "")

        if 'aggregate="count"' in xml.lower() or "aggregate='count'" in xml.lower():
            print(f"  → Count found. Fixing to Sum of estimatedvalue...")
            fix_result = set_chart_y_axis_to_sum(cid, "estimatedvalue")
            if fix_result.get("updated"):
                print(f"  ✓ Fixed: {name}")
                fixed.append(name)
            else:
                print(f"  ✗ Fix failed: {fix_result}")
                skipped.append(name)
        else:
            print(f"  — Already using sum or no count aggregation found. Skipping.")
            skipped.append(name)

    print("\n=== Summary ===")
    print(f"Fixed ({len(fixed)}):")
    for n in fixed:
        print(f"  ✓ {n}")
    print(f"\nSkipped ({len(skipped)}):")
    for n in skipped:
        print(f"  — {n}")
    print("\nDone. Refresh your CRM charts to see the changes.")

if __name__ == "__main__":
    run()
