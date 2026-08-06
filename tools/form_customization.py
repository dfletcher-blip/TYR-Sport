# ============================================================
# tools/form_customization.py — Entity Form Customization
# ============================================================
# Read and modify Dynamics 365 entity forms (add fields,
# add subgrids, create custom fields, publish changes).
# ============================================================

import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import xml.etree.ElementTree as ET
from config.crm_connection import crm_get, crm_patch, crm_post, crm_action


# ── Helpers ───────────────────────────────────────────────────

def _get_main_form(entity: str) -> tuple:
    """Return (form_record, form_id, formxml) for the main form of an entity."""
    params = {
        "$select": "formid,name,formxml",
        "$filter": f"objecttypecode eq '{entity}' and type eq 2",  # type 2 = Main form
        "$orderby": "name asc",
        "$top": 5,
    }
    rows = crm_get("systemforms", params).get("value", [])
    if not rows:
        raise ValueError(f"No main form found for entity '{entity}'")
    # Prefer a form named 'Information' or 'Main', otherwise take first
    preferred = next((r for r in rows if r.get("name", "").lower() in ("information", "main")), rows[0])
    return preferred, preferred["formid"], preferred.get("formxml", "")


def _publish(entity: str):
    """Publish customizations for an entity so changes appear immediately."""
    crm_action("PublishXml", {
        "ParameterXml": f"<importexportxml><entities><entity>{entity}</entity></entities></importexportxml>"
    })


# ── Public tools ──────────────────────────────────────────────

def get_entity_form(entity: str, form_name: str = "") -> dict:
    """
    Fetch the current form definition for an entity.

    entity: e.g. "opportunity", "contact", "lead", "account"
    form_name: optional — specific form name to retrieve (default: main form)

    Returns the form name, ID, and the list of fields currently on it.
    """
    try:
        form, form_id, formxml = _get_main_form(entity)
    except ValueError as e:
        return {"error": str(e)}

    fields_on_form = []
    if formxml:
        try:
            root = ET.fromstring(formxml)
            for cell in root.iter("cell"):
                control = cell.find("control")
                if control is not None:
                    fields_on_form.append({
                        "field": control.get("datafieldname", ""),
                        "label": next(
                            (lb.get("description", "") for lb in cell.iter("label") if lb.get("description")),
                            ""
                        ),
                    })
        except ET.ParseError:
            pass

    return {
        "entity": entity,
        "form_name": form.get("name", ""),
        "form_id": form_id,
        "fields_on_form": [f for f in fields_on_form if f["field"]],
        "total_fields": len([f for f in fields_on_form if f["field"]]),
    }


def list_entity_fields(entity: str, search_term: str = "") -> dict:
    """
    List all available fields on an entity — useful to find exact field names
    before adding them to a form, or to find option set values.

    entity: e.g. "opportunity", "contact", "lead"
    search_term: optional filter by field name or display name
    """
    try:
        meta = crm_get(
            f"EntityDefinitions(LogicalName='{entity}')/Attributes",
            {
                "$select": "LogicalName,DisplayName,AttributeType,IsCustomAttribute",
                "$top": 500,
            }
        )
    except Exception as e:
        return {"error": f"Could not fetch fields for '{entity}': {e}"}

    fields = meta.get("value", [])

    result = []
    for f in fields:
        display = ""
        dn = f.get("DisplayName")
        if isinstance(dn, dict):
            lls = dn.get("UserLocalizedLabel") or {}
            display = lls.get("Label", "")
        result.append({
            "logical_name": f.get("LogicalName", ""),
            "display_name": display,
            "type": f.get("AttributeType", ""),
            "is_custom": f.get("IsCustomAttribute", False),
        })

    if search_term:
        lower = search_term.lower()
        result = [
            f for f in result
            if lower in f["logical_name"].lower() or lower in f["display_name"].lower()
        ]

    return {
        "entity": entity,
        "total_found": len(result),
        "fields": sorted(result, key=lambda x: x["logical_name"]),
    }


def get_optionset_values(entity: str, field_name: str) -> dict:
    """
    Get all available dropdown options for an option set field.

    entity: e.g. "opportunity"
    field_name: the logical field name, e.g. "tyr_tyrtype"

    Returns all option labels and values for the dropdown.
    """
    try:
        meta = crm_get(
            f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='{field_name}')/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
            {"$select": "LogicalName", "$expand": "OptionSet"}
        )
    except Exception as e:
        return {"error": f"Could not fetch option set for '{field_name}': {e}"}

    option_set = meta.get("OptionSet", {})
    options = option_set.get("Options", [])

    result = []
    for opt in options:
        label_obj = opt.get("Label", {})
        lls = label_obj.get("UserLocalizedLabel") or {}
        result.append({
            "value": opt.get("Value"),
            "label": lls.get("Label", ""),
        })

    return {
        "entity": entity,
        "field": field_name,
        "options": result,
        "total": len(result),
    }


def _get_optionset_metadata(entity: str, field_name: str) -> dict:
    """
    Fetch option set metadata for a field, trying single-select (Picklist)
    then multi-select (MultiSelectPicklist) — Account's tyr_tyrtype, for
    example, is a MultiSelectPicklist while Contact's is a plain Picklist.
    """
    for cast in ("PicklistAttributeMetadata", "MultiSelectPicklistAttributeMetadata"):
        try:
            meta = crm_get(
                f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='{field_name}')"
                f"/Microsoft.Dynamics.CRM.{cast}",
                {"$select": "LogicalName", "$expand": "OptionSet"},
            )
        except Exception:
            continue
        option_set = meta.get("OptionSet")
        if option_set:
            return {"cast": cast, "option_set": option_set}
    raise ValueError(f"'{field_name}' on '{entity}' is not a picklist or multi-select picklist field")


def add_optionset_value(entity: str, field_name: str, labels: list) -> dict:
    """
    Add one or more new dropdown options to an EXISTING option set field
    (single- or multi-select picklist), without disturbing the options
    already there. Use this — not create_custom_field — when the field
    already exists and you just need new choices on it (e.g. adding a new
    business type). Skips any label that's already present. Publishes
    automatically when it adds anything.

    entity: e.g. "lead", "account"
    field_name: the logical field name, e.g. "tyr_tyrtype"
    labels: list of new option labels to add, e.g. ["HYROX", "Run Club"]
    """
    try:
        info = _get_optionset_metadata(entity, field_name)
    except ValueError as e:
        return {"error": str(e)}

    option_set = info["option_set"]
    is_global = bool(option_set.get("IsGlobal"))
    optionset_name = option_set.get("Name")
    options = option_set.get("Options", [])

    existing_labels = set()
    existing_values = set()
    for opt in options:
        lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
        existing_labels.add(lls.get("Label", "").strip().lower())
        existing_values.add(opt.get("Value"))

    next_value = (max(existing_values) + 1) if existing_values else 100000000

    added, skipped, failed = [], [], []

    for label in labels:
        if label.strip().lower() in existing_labels:
            skipped.append(label)
            continue

        value = next_value
        next_value += 1

        body = {
            "Value": value,
            "Label": {
                "@odata.type": "Microsoft.Dynamics.CRM.Label",
                "LocalizedLabels": [{
                    "@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
                    "Label": label,
                    "LanguageCode": 1033,
                }],
                "UserLocalizedLabel": {
                    "@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
                    "Label": label,
                    "LanguageCode": 1033,
                },
            },
            "SolutionUniqueName": "Default",
        }
        if is_global:
            body["OptionSetName"] = optionset_name
        else:
            body["EntityLogicalName"] = entity
            body["AttributeLogicalName"] = field_name

        try:
            crm_action("InsertOptionValue", body)
            added.append({"label": label, "value": value})
            existing_labels.add(label.strip().lower())
        except Exception as e:
            failed.append({"label": label, "error": str(e)[:300]})

    if added:
        _publish(entity)

    return {
        "entity": entity,
        "field": field_name,
        "optionset_name": optionset_name,
        "is_global": is_global,
        "added": added,
        "skipped_existing": skipped,
        "failed": failed,
    }


def add_fields_to_form(entity: str, fields: list, section_label: str = "Details") -> dict:
    """
    Add one or more fields to an entity's main form.

    entity: e.g. "opportunity"
    fields: list of field logical names to add, e.g.:
            ["ownerid", "name", "estimatedclosedate", "tyr_shipdate"]
            For subgrids use: {"type": "subgrid", "name": "Contacts", "entity": "contact", "relationship": "opportunity_customer_contacts"}
    section_label: the section heading to add fields under (default "Details")

    Fields already on the form are skipped. Publishes automatically.
    """
    try:
        form, form_id, formxml = _get_main_form(entity)
    except ValueError as e:
        return {"error": str(e)}

    if not formxml:
        return {"error": "Form has no XML to modify"}

    try:
        root = ET.fromstring(formxml)
    except ET.ParseError as e:
        return {"error": f"Could not parse form XML: {e}"}

    # Find fields already on the form
    existing_fields = set()
    for control in root.iter("control"):
        fn = control.get("datafieldname") or control.get("id", "")
        if fn:
            existing_fields.add(fn)

    # Find or create target section
    target_rows = None
    for section in root.iter("section"):
        labels = [lb.get("description", "") for lb in section.iter("label") if lb.get("description")]
        if any(section_label.lower() in lb.lower() for lb in labels):
            target_rows = section.find("rows")
            break

    # Fall back to first section if named section not found
    if target_rows is None:
        sections = list(root.iter("section"))
        if sections:
            target_rows = sections[0].find("rows")

    if target_rows is None:
        return {"error": f"Could not find a section to add fields to in the {entity} form"}

    added = []
    skipped = []

    for field in fields:
        # Handle subgrid dict
        if isinstance(field, dict) and field.get("type") == "subgrid":
            sg_name = field.get("name", "Subgrid")
            sg_entity = field.get("entity", "")
            sg_rel = field.get("relationship", "")
            control_id = f"subgrid_{sg_entity}"

            if control_id in existing_fields:
                skipped.append(sg_name)
                continue

            row_el = ET.SubElement(target_rows, "row")
            cell_el = ET.SubElement(row_el, "cell", colspan="2", rowspan="4", showlabel="true", locklevel="0")
            lbs_el = ET.SubElement(cell_el, "labels")
            ET.SubElement(lbs_el, "label", description=sg_name, languagecode="1033")
            ET.SubElement(cell_el, "control",
                id=control_id,
                classid="{E7A81278-8635-4d9e-8D4D-59480B391C5B}",
                datafieldname="",
                isrequired="false",
                rowspan="4",
                colspan="2",
            )
            added.append(sg_name)
            continue

        # Regular field
        field_name = field if isinstance(field, str) else field.get("name", "")
        if not field_name:
            continue

        if field_name in existing_fields:
            skipped.append(field_name)
            continue

        row_el = ET.SubElement(target_rows, "row")
        cell_el = ET.SubElement(row_el, "cell", showlabel="true", locklevel="0")
        lbs_el = ET.SubElement(cell_el, "labels")
        ET.SubElement(lbs_el, "label", description=field_name, languagecode="1033")
        ET.SubElement(cell_el, "control",
            id=field_name,
            classid="{4273EDBD-AC1D-40d3-9FB2-095C621B552D}",
            datafieldname=field_name,
            isrequired="false",
        )
        added.append(field_name)

    if not added:
        return {
            "message": "All specified fields are already on the form — nothing to add.",
            "skipped": skipped,
        }

    # Write back
    new_xml = ET.tostring(root, encoding="unicode")
    crm_patch("systemforms", form_id, {"formxml": new_xml})

    # Publish
    try:
        _publish(entity)
        published = True
    except Exception as e:
        published = False

    return {
        "success": True,
        "entity": entity,
        "form": form.get("name", ""),
        "fields_added": added,
        "fields_skipped_already_present": skipped,
        "published": published,
        "message": f"Added {len(added)} field(s) to the {entity} form and published.",
    }


def create_custom_field(entity: str, display_name: str, field_type: str, options: list = None) -> dict:
    """
    Create a new custom field on an entity.

    entity: e.g. "opportunity"
    display_name: human-readable label, e.g. "TYR Type"
    field_type: "text", "date", "optionset", "boolean", "number", "currency"
    options: for optionset only — list of option labels, e.g. ["D2C", "B2B", "Team Sales"]

    Returns the new field's logical name so you can add it to a form.
    """
    # Build logical name from display name
    logical_name = "tyr_" + re.sub(r"[^a-z0-9]", "", display_name.lower().replace(" ", ""))

    type_map = {
        "text":      "String",
        "date":      "DateTime",
        "optionset": "Picklist",
        "boolean":   "Boolean",
        "number":    "Integer",
        "currency":  "Money",
    }
    attr_type = type_map.get(field_type.lower(), "String")

    payload = {
        "AttributeType": attr_type,
        "AttributeTypeName": {"Value": f"{attr_type}Type"},
        "LogicalName": logical_name,
        "SchemaName": logical_name,
        "DisplayName": {
            "LocalizedLabels": [{"Label": display_name, "LanguageCode": 1033}],
            "UserLocalizedLabel": {"Label": display_name, "LanguageCode": 1033},
        },
        "RequiredLevel": {"Value": "None"},
        "@odata.type": f"Microsoft.Dynamics.CRM.{attr_type}AttributeMetadata",
    }

    if attr_type == "String":
        payload["MaxLength"] = 255
    elif attr_type == "DateTime":
        payload["Format"] = "DateOnly"
    elif attr_type == "Picklist" and options:
        opt_list = [
            {
                "Value": 100000 + i,
                "Label": {
                    "LocalizedLabels": [{"Label": opt, "LanguageCode": 1033}],
                    "UserLocalizedLabel": {"Label": opt, "LanguageCode": 1033},
                },
            }
            for i, opt in enumerate(options)
        ]
        payload["OptionSet"] = {
            "IsGlobal": False,
            "OptionSetType": "Picklist",
            "Options": opt_list,
            "@odata.type": "Microsoft.Dynamics.CRM.OptionSetMetadata",
        }

    try:
        crm_post(f"EntityDefinitions(LogicalName='{entity}')/Attributes", payload)
        _publish(entity)
        return {
            "success": True,
            "entity": entity,
            "display_name": display_name,
            "logical_name": logical_name,
            "field_type": field_type,
            "options_created": options or [],
            "message": f"Field '{display_name}' created as '{logical_name}' on {entity}. Add it to the form with add_fields_to_form.",
        }
    except Exception as e:
        return {"error": f"Could not create field: {e}", "logical_name_attempted": logical_name}
