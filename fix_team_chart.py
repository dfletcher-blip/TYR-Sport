# ============================================================
# fix_team_chart.py — Convert Teams chart to Pie + filter TYR
# Run: python fix_team_chart.py
# ============================================================
# 1. Finds the "Teams by Owner and Status" chart in the
#    DTC/Crossfit Overview dashboard entity
# 2. Changes it from Bar to Pie chart
# 3. Filters out teams where current sponsor = "TYR"
# ============================================================

import re
import json
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_patch

# ── Step 1: Discover which entity/chart we're dealing with ──

def find_chart(search_term: str, entity: str = None):
    """Search for a chart by name across entities."""
    params = {
        "$select": "savedqueryvisualizationid,name,primaryentitytypecode,datadescription,presentationdescription",
        "$top": 50,
        "$filter": f"contains(name,'{search_term}')",
    }
    if entity:
        params["$filter"] += f" and primaryentitytypecode eq '{entity}'"

    result = crm_get("savedqueryvisualizations", params)
    return result.get("value", [])


def show_chart_xml(chart):
    print(f"\n{'='*60}")
    print(f"Chart: {chart.get('name')}")
    print(f"Entity: {chart.get('primaryentitytypecode')}")
    print(f"ID: {chart.get('savedqueryvisualizationid')}")
    print(f"\n--- Data Description (fetch XML) ---")
    print(chart.get("datadescription", "")[:1000])
    print(f"\n--- Presentation Description (chart type XML) ---")
    print(chart.get("presentationdescription", "")[:500])


def convert_bar_to_pie(presentation_xml: str) -> str:
    """Change BarChart/VerticalBarChart to Pie in presentationdescription."""
    updated = re.sub(
        r'charttype=["\'](?:VerticalBarChart|HorizontalBarChart|BarChart)["\']',
        'charttype="Pie"',
        presentation_xml,
        flags=re.IGNORECASE,
    )
    # Remove series collection (not needed for pie) and simplify
    # Pie charts need a single series with category grouping
    return updated


def add_sponsor_filter(data_xml: str, sponsor_field: str, sponsor_value: str) -> str:
    """
    Add a filter to exclude records where sponsor_field = sponsor_value.
    Inserts a <condition> into the <filter> block, or creates one if absent.
    """
    condition = f'<condition attribute="{sponsor_field}" operator="ne" value="{sponsor_value}" />'

    if "<filter" in data_xml:
        # Add condition inside existing filter
        updated = re.sub(
            r'(<filter[^>]*>)',
            r'\1\n        ' + condition,
            data_xml,
            count=1,
        )
    elif "</entity>" in data_xml:
        # Add a new filter block before closing entity tag
        filter_block = f'\n        <filter type="and">\n          {condition}\n        </filter>'
        updated = data_xml.replace("</entity>", filter_block + "\n      </entity>", 1)
    else:
        print("  WARNING: Could not find a place to insert filter. XML unchanged.")
        return data_xml

    return updated


def run():
    print("\n=== TYR Sport — Fix Team Chart: Bar → Pie + Filter TYR Sponsor ===\n")

    # Search for the chart
    print("Searching for 'Teams by Owner' chart...")
    charts = find_chart("Teams by Owner")

    if not charts:
        print("Not found. Trying 'Teams'...")
        charts = find_chart("Teams")

    if not charts:
        print("No charts found. Listing all charts for 'team' entity...")
        params = {
            "$select": "savedqueryvisualizationid,name,primaryentitytypecode",
            "$top": 50,
            "$filter": "primaryentitytypecode eq 'team'",
        }
        result = crm_get("savedqueryvisualizations", params)
        charts = result.get("value", [])
        if not charts:
            # Try custom team entity
            for entity in ["tyr_team", "tyr_sportsaccount"]:
                params["$filter"] = f"primaryentitytypecode eq '{entity}'"
                result = crm_get("savedqueryvisualizations", params)
                charts = result.get("value", [])
                if charts:
                    print(f"Found charts on entity: {entity}")
                    break

    if not charts:
        print("Could not find any team-related charts. Please check the entity name.")
        print("All available chart entities:")
        result = crm_get("savedqueryvisualizations", {
            "$select": "name,primaryentitytypecode",
            "$top": 200,
            "$orderby": "primaryentitytypecode asc",
        })
        entities = sorted(set(c.get("primaryentitytypecode","") for c in result.get("value",[])))
        for e in entities:
            print(f"  • {e}")
        return

    # Show what we found
    print(f"\nFound {len(charts)} chart(s):")
    for i, c in enumerate(charts):
        print(f"  [{i}] {c.get('name')} (entity: {c.get('primaryentitytypecode')})")

    # Pick the right one
    chart = charts[0]
    if len(charts) > 1:
        # Try to find best match
        for c in charts:
            if "owner" in c.get("name","").lower() and "status" in c.get("name","").lower():
                chart = c
                break

    show_chart_xml(chart)

    chart_id   = chart.get("savedqueryvisualizationid")
    data_xml   = chart.get("datadescription", "")
    pres_xml   = chart.get("presentationdescription", "")

    # ── Ask about sponsor field name ──
    print("\n" + "="*60)
    print("To filter out TYR sponsors, I need the API field name.")
    print("Common options: tyr_currentsponsor, tyr_sponsor, tyr_sponsorname")
    sponsor_field = input("Enter the sponsor field API name (or press Enter to skip filter): ").strip()
    if not sponsor_field:
        sponsor_field = None

    # ── Apply changes ──
    print("\nApplying changes...")

    new_pres = convert_bar_to_pie(pres_xml)
    if new_pres == pres_xml:
        print("  WARNING: Chart type may not have changed — check the XML above for the exact charttype value.")
    else:
        print("  ✓ Chart type changed to Pie")

    new_data = data_xml
    if sponsor_field:
        new_data = add_sponsor_filter(data_xml, sponsor_field, "TYR")
        print(f"  ✓ Filter added: exclude {sponsor_field} = 'TYR'")

    # ── Preview ──
    print("\n--- Updated Presentation XML ---")
    print(new_pres[:500])
    if sponsor_field:
        print("\n--- Updated Data XML (first 800 chars) ---")
        print(new_data[:800])

    confirm = input("\nApply these changes to the CRM? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled. No changes made.")
        return

    crm_patch("savedqueryvisualizations", chart_id, {
        "datadescription":      new_data,
        "presentationdescription": new_pres,
    })
    print(f"\n✓ Chart updated. Refresh your CRM dashboard to see the changes.")


if __name__ == "__main__":
    run()
