# ============================================================
# fix_charts.py — Direct chart fix script (no agent needed)
# Run this directly: python fix_charts.py
# ============================================================
# Finds pipeline/revenue charts and changes Y-axis from Count
# to Sum of estimatedvalue (revenue). Skips count-by-design
# charts and handles errors gracefully.
# ============================================================

import os
from dotenv import load_dotenv
load_dotenv()

from tools.charts import list_charts, get_chart_xml, set_chart_y_axis_to_sum

# Charts whose names contain these words are REVENUE charts that should be fixed
FIX_KEYWORDS = ['pipeline', 'revenue', 'close month']

# Charts whose names contain these words should be SKIPPED (they're count-by-design)
SKIP_KEYWORDS = ['count', 'won vs', 'leaderboard', 'by account', 'by rating',
                 'by status', 'by campaign', 'by territory', 'by tyr type',
                 'by fiscal', 'by month', 'progress', 'top ']

def should_fix(name):
    name_lower = name.lower()
    if any(kw in name_lower for kw in SKIP_KEYWORDS):
        return False
    return any(kw in name_lower for kw in FIX_KEYWORDS)

def run():
    print("\n=== TYR Sport — Pipeline Chart Fix ===\n")

    print("Fetching all opportunity charts...")
    result = list_charts("opportunity")
    charts = result.get("charts", [])
    print(f"Found {len(charts)} charts total.\n")

    targets = [c for c in charts if should_fix(c['name'])]

    print(f"Charts selected for fixing ({len(targets)}):")
    for c in targets:
        print(f"  • {c['name']}")

    print()

    fixed = []
    skipped = []
    errors = []

    for chart in targets:
        cid  = chart['id']
        name = chart['name']
        print(f"Checking: {name}")

        try:
            xml_data = get_chart_xml(cid)
            xml = xml_data.get("data_description_xml") or ""

            if not xml:
                print(f"  — No XML found for this chart. Skipping.")
                skipped.append(f"{name}: no XML")
                continue

            if 'aggregate="count"' in xml.lower() or "aggregate='count'" in xml.lower():
                print(f"  → Count aggregation found. Fixing to Sum of estimatedvalue...")
                fix_result = set_chart_y_axis_to_sum(cid, "estimatedvalue")
                if fix_result.get("updated"):
                    print(f"  ✓ Fixed!")
                    fixed.append(name)
                else:
                    msg = fix_result.get("message", str(fix_result))
                    print(f"  — {msg}")
                    skipped.append(f"{name}: {msg}")
            else:
                print(f"  — Already using sum. Skipping.")
                skipped.append(name)

        except Exception as e:
            print(f"  ✗ Error: {e}")
            errors.append(f"{name}: {e}")

    print("\n=== Summary ===")
    if fixed:
        print(f"\nFixed ({len(fixed)}):")
        for n in fixed:
            print(f"  ✓ {n}")
    if skipped:
        print(f"\nSkipped ({len(skipped)}):")
        for n in skipped:
            print(f"  — {n}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for n in errors:
            print(f"  ✗ {n}")

    print("\nDone. Refresh your CRM dashboard to see the changes.")

if __name__ == "__main__":
    run()
