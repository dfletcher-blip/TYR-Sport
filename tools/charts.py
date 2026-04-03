# ============================================================
# tools/charts.py — Chart Management Tools
# ============================================================
# Charts in Dynamics 365 are stored as XML definitions in the
# savedqueryvisualizations (system charts) and
# userqueryvisualizations (personal charts) entities.
#
# This tool lets the agent read and update chart XML directly,
# enabling changes like switching Y-axis from Count to Sum of
# a field — which the UI chart editor cannot always do.
# ============================================================

import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch


def list_charts(entity: str = "opportunity") -> dict:
    """
    List all system charts for a given entity.

    entity: the entity to list charts for (e.g. "opportunity", "contact", "lead")

    Returns chart names and IDs.
    """
    params = {
        "$top": 100,
        "$select": "savedqueryvisualizationid,name,description,primaryentitytypecode",
        "$filter": f"primaryentitytypecode eq '{entity}'",
        "$orderby": "name asc",
    }

    result = crm_get("savedqueryvisualizations", params)
    charts = result.get("value", [])

    return {
        "entity":       entity,
        "total_charts": len(charts),
        "charts": [
            {
                "id":          c.get("savedqueryvisualizationid"),
                "name":        c.get("name", "Unnamed"),
                "description": c.get("description", ""),
            }
            for c in charts
        ],
    }


def get_chart_xml(chart_id: str) -> dict:
    """
    Get the raw XML definition of a system chart.

    chart_id: the ID of the chart (savedqueryvisualizationid)

    Returns the chart name and its full XML definition — useful
    for inspecting what aggregation (count vs sum) is being used.
    """
    params = {
        "$select": "savedqueryvisualizationid,name,datadescription,presentationdescription",
    }

    result = crm_get(f"savedqueryvisualizations({chart_id})", params)

    return {
        "id":                       result.get("savedqueryvisualizationid"),
        "name":                     result.get("name", "Unnamed"),
        "data_description_xml":     result.get("datadescription", ""),
        "presentation_description": result.get("presentationdescription", ""),
    }


def update_chart_xml(chart_id: str, data_description_xml: str,
                     presentation_description: str = None) -> dict:
    """
    Update the XML definition of a system chart.

    chart_id:                 the ID of the chart to update
    data_description_xml:     the full updated datadescription XML string
    presentation_description: optionally update the presentation XML too

    Returns confirmation the chart was updated.
    """
    data = {"datadescription": data_description_xml}
    if presentation_description:
        data["presentationdescription"] = presentation_description

    crm_patch("savedqueryvisualizations", chart_id, data)
    return {"updated": True, "chart_id": chart_id}


def set_chart_y_axis_to_sum(chart_id: str, field_name: str = "estimatedvalue") -> dict:
    """
    Change a chart's Y-axis from Count to Sum of a field.
    This is the fix for pipeline charts that show count of deals
    instead of total revenue (sum of estimatedvalue).

    chart_id:   the ID of the chart to update
    field_name: the field to sum (default: estimatedvalue for revenue)

    Returns confirmation and shows what was changed.
    """
    # Fetch the current XML
    chart = get_chart_xml(chart_id)
    original_xml = chart.get("data_description_xml", "")

    if not original_xml:
        return {"error": "Could not retrieve chart XML. Chart may not exist."}

    # Replace count aggregation with sum
    # Dynamics chart XML uses: aggregate="count" → aggregate="sum" + add attribute
    # and adds the field: alias="sum_field" attribute="field_name"
    updated_xml = original_xml

    # Pattern: change aggregate="count" to aggregate="sum"
    updated_xml = re.sub(
        r'aggregate=["\']count["\']',
        'aggregate="sum"',
        updated_xml,
        flags=re.IGNORECASE,
    )

    # Pattern: if there's a generic count attribute, replace with the target field
    updated_xml = re.sub(
        r'attribute=["\']opportunityid["\']',
        f'attribute="{field_name}"',
        updated_xml,
        flags=re.IGNORECASE,
    )

    if updated_xml == original_xml:
        return {
            "changed": False,
            "chart_id": chart_id,
            "message": "No count aggregation found to replace. Check the raw XML with get_chart_xml().",
            "current_xml": original_xml[:500],
        }

    crm_patch("savedqueryvisualizations", chart_id, {"datadescription": updated_xml})

    return {
        "updated":   True,
        "chart_id":  chart_id,
        "chart_name": chart.get("name"),
        "change":    f"Changed aggregate from count to sum of {field_name}",
    }


def search_charts(search_term: str, entity: str = "opportunity") -> dict:
    """
    Search for charts by name.

    search_term: part of the chart name to search for
    entity:      the entity to search within (default: opportunity)

    Returns matching charts with their IDs.
    """
    params = {
        "$top": 50,
        "$select": "savedqueryvisualizationid,name,primaryentitytypecode",
        "$filter": (
            f"primaryentitytypecode eq '{entity}' and "
            f"contains(name,'{search_term}')"
        ),
        "$orderby": "name asc",
    }

    result = crm_get("savedqueryvisualizations", params)
    charts = result.get("value", [])

    return {
        "search_term": search_term,
        "total_found": len(charts),
        "charts": [
            {"id": c.get("savedqueryvisualizationid"), "name": c.get("name", "Unnamed")}
            for c in charts
        ],
    }
