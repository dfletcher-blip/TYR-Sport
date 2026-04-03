# ============================================================
# agent.py — The Brain of the CRM Agent
# ============================================================
# This is where Claude is set up and given its tools.
# You don't run this file directly — use run.py instead.
#
# What happens here:
#   1. Claude is given a personality and instructions
#   2. Claude is given its tools (the "hands" to use the CRM)
#   3. Claude is told to think carefully before acting
#   4. Every action is logged for your records
# ============================================================

import os
import json
import anthropic
from datetime import datetime
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()

# Import all the tool functions Claude can use
from tools.contacts import (
    search_contacts,
    find_contacts_missing_data,
    find_duplicate_contacts,
    update_contact,
    get_contact_details,
    get_contact_summary,
)
from tools.workflows import (
    list_workflows,
    get_workflow_details,
    check_workflow_health,
    get_recent_workflow_runs,
    activate_workflow,
    deactivate_workflow,
    search_workflows,
    get_workflows_by_entity,
    retry_failed_workflow_runs,
    clone_workflow,
)
from tools.memory import update_crm_memory, read_crm_memory, save_session_summary, get_conversation_history
from tools.views_dashboards import (
    list_views,
    create_contact_view,
    list_dashboards,
    create_dashboard,
    delete_dashboard,
    publish_all_dashboards,
    get_views_summary,
    get_dashboard_details,
    reorder_dashboard_components,
    clone_dashboard,
    set_dashboard_description,
)
from tools.bulk_updates import (
    bulk_update_contacts,
    bulk_update_leads,
    bulk_update_accounts,
    bulk_update_opportunities,
)
from tools.reports import (
    list_reports,
    get_data_quality_report,
    get_pipeline_report,
    get_lead_source_report,
    get_activity_report,
)
from tools.email import (
    send_email_to_contact,
    send_email_to_lead,
    send_bulk_email,
    get_email_history,
)
from tools.opportunities import (
    search_opportunities,
    get_opportunity_details,
    update_opportunity,
    get_opportunity_summary,
    find_stalled_opportunities,
)
from tools.accounts import (
    search_accounts,
    get_account_details,
    update_account,
    get_account_summary,
    find_accounts_missing_data,
)
from tools.leads import (
    search_leads,
    get_lead_details,
    update_lead,
    qualify_lead,
    get_lead_summary,
    find_stale_leads,
)
from tools.teams import (
    list_teams,
    get_team_details,
    search_teams,
    get_team_summary,
)
from tools.special_terms import (
    search_special_terms,
    get_special_terms_details,
    get_pending_approvals,
    get_special_terms_by_account,
    get_expiring_special_terms,
    get_special_terms_summary,
    get_str_workflows,
    update_special_terms,
)
from tools.form_customization import (
    get_entity_form,
    list_entity_fields,
    get_optionset_values,
    add_fields_to_form,
    create_custom_field,
)
from tools.activities import (
    get_tasks,
    create_task,
    complete_task,
    get_phone_calls,
    log_phone_call,
    get_appointments,
    create_appointment,
    get_notes,
    add_note,
    get_activity_timeline,
)
from tools.audit_log import (
    get_audit_history,
    get_recent_changes,
    get_deleted_records,
    check_audit_status,
)
from tools.cloud_flows import (
    list_cloud_flows,
    get_cloud_flow_details,
    get_cloud_flow_run_history,
    enable_cloud_flow,
    disable_cloud_flow,
    search_cloud_flows,
    get_cloud_flows_by_entity,
    check_cloud_flow_health,
    compare_classic_vs_cloud_flows,
)
from tools.security import (
    list_security_roles,
    get_role_details,
    search_roles,
    list_users,
    get_user_details,
    search_users,
    assign_role_to_user,
    remove_role_from_user,
    get_users_with_no_roles,
    get_admin_users,
    get_security_summary,
)


# ============================================================
# SYSTEM PROMPT — How Claude introduces itself and behaves
# ============================================================
# This is like a job description for your AI assistant.
# Claude will always follow these rules.

SYSTEM_PROMPT = """You are the CRM Operations Agent for TYR Sport.
You have direct access to the Microsoft Dynamics 365 CRM system.

YOUR ROLE:
You help manage, clean, monitor, and improve the TYR Sport CRM. You are
proactive, thorough, and always explain what you are doing in plain English.

YOUR CAPABILITIES:
1. CONTACTS — Search, find duplicates, fix missing data, update records
2. WORKFLOWS — List, monitor, check health, activate/deactivate automated processes
3. VIEWS — List existing views, create new saved views and filters
4. DASHBOARDS — List, create, reorder, clone, and update dashboards (created as personal dashboards visible in My Dashboards)
5. OPPORTUNITIES — Search deals, view pipeline, track stalled opportunities, update stages
6. ACCOUNTS — Search companies, view account details with contacts and deals, update records
7. LEADS — Search leads, qualify leads, find stale leads, update records
8. TEAMS — List teams, view team members, search by name
9. BULK UPDATES — Update many contacts, leads, accounts, or opportunities at once by filter
10. REPORTS — Data quality, pipeline, lead source, and activity reports
11. EMAIL — Send emails to contacts or leads, send bulk emails, view email history
12. SPECIAL TERMS (STR) — Search STR records, check pending approvals, find expiring agreements, view by account, manage approval workflows
13. FORM CUSTOMIZATION — Add fields to entity forms, create custom fields (including dropdowns), inspect form layouts, publish changes
14. MEMORY — Read and update persistent CRM memory to remember field names, entity names, and CRM-specific facts across sessions
15. ACTIVITIES — Create and view tasks, log phone calls, schedule appointments, add and read notes on any record, view full activity timelines
16. AUDIT LOG — See who changed what and when on any record, find recently deleted records, view all changes in the last N hours, check audit status
17. CLOUD FLOWS (Power Automate) — List, search, enable/disable, and check health of modern Power Automate flows; compare with classic workflows
18. SECURITY — List security roles, view user permissions, assign/remove roles, find users with no roles, review admin access

HOW YOU WORK:
- Always start by READING data before making any changes
- Always EXPLAIN what you found before doing anything
- For any UPDATE or CREATE action, state what you are about to do and why
- After completing a task, give a clear SUMMARY of what was done
- If something could cause problems, warn the user first
- At the start of a NEW session (first message), call get_conversation_history() to recall what was previously discussed
- When wrapping up significant work, call save_session_summary() to record what was done for next time

SAFETY RULES:
- Never delete contacts without explicit permission
- When fixing duplicates, FLAG them — do not automatically delete
- Always confirm bulk updates before executing
- If unsure, ask a clarifying question

COMMUNICATION STYLE:
- Use plain English, no jargon
- Use bullet points and clear sections
- Give counts and percentages when summarizing data
- Be concise but complete
"""


# ============================================================
# TOOL REGISTRY — All tools Claude can use
# ============================================================
# This maps function names (what Claude calls) to actual code

TOOL_REGISTRY = {
    # Memory tools
    "update_crm_memory":           update_crm_memory,
    "read_crm_memory":             read_crm_memory,
    "save_session_summary":        save_session_summary,
    "get_conversation_history":    get_conversation_history,
    "search_contacts":             search_contacts,
    "find_contacts_missing_data":  find_contacts_missing_data,
    "find_duplicate_contacts":     find_duplicate_contacts,
    "update_contact":              update_contact,
    "get_contact_details":         get_contact_details,
    "get_contact_summary":         get_contact_summary,

    # Workflow tools
    "list_workflows":              list_workflows,
    "get_workflow_details":        get_workflow_details,
    "check_workflow_health":       check_workflow_health,
    "get_recent_workflow_runs":    get_recent_workflow_runs,
    "activate_workflow":           activate_workflow,
    "deactivate_workflow":         deactivate_workflow,
    "search_workflows":            search_workflows,
    "get_workflows_by_entity":     get_workflows_by_entity,
    "retry_failed_workflow_runs":  retry_failed_workflow_runs,
    "clone_workflow":              clone_workflow,

    # Views & dashboard tools
    "list_views":                  list_views,
    "create_contact_view":         create_contact_view,
    "list_dashboards":             list_dashboards,
    "create_dashboard":            create_dashboard,
    "delete_dashboard":            delete_dashboard,
    "publish_all_dashboards":      publish_all_dashboards,
    "get_views_summary":           get_views_summary,
    "get_dashboard_details":       get_dashboard_details,
    "reorder_dashboard_components": reorder_dashboard_components,

    # Opportunity tools
    "search_opportunities":        search_opportunities,
    "get_opportunity_details":     get_opportunity_details,
    "update_opportunity":          update_opportunity,
    "get_opportunity_summary":     get_opportunity_summary,
    "find_stalled_opportunities":  find_stalled_opportunities,

    # Account tools
    "search_accounts":             search_accounts,
    "get_account_details":         get_account_details,
    "update_account":              update_account,
    "get_account_summary":         get_account_summary,
    "find_accounts_missing_data":  find_accounts_missing_data,

    # Lead tools
    "search_leads":                search_leads,
    "get_lead_details":            get_lead_details,
    "update_lead":                 update_lead,
    "qualify_lead":                qualify_lead,
    "get_lead_summary":            get_lead_summary,
    "find_stale_leads":            find_stale_leads,

    # Special Terms (STR) tools
    "search_special_terms":           search_special_terms,
    "get_special_terms_details":      get_special_terms_details,
    "get_pending_approvals":          get_pending_approvals,
    "get_special_terms_by_account":   get_special_terms_by_account,
    "get_expiring_special_terms":     get_expiring_special_terms,
    "get_special_terms_summary":      get_special_terms_summary,
    "get_str_workflows":              get_str_workflows,
    "update_special_terms":           update_special_terms,

    # Form customization tools
    "get_entity_form":                get_entity_form,
    "list_entity_fields":             list_entity_fields,
    "get_optionset_values":           get_optionset_values,
    "add_fields_to_form":             add_fields_to_form,
    "create_custom_field":            create_custom_field,

    # Team tools
    "list_teams":                  list_teams,
    "get_team_details":            get_team_details,
    "search_teams":                search_teams,
    "get_team_summary":            get_team_summary,

    # Dashboard extras
    "clone_dashboard":             clone_dashboard,
    "set_dashboard_description":   set_dashboard_description,

    # Bulk update tools
    "bulk_update_contacts":        bulk_update_contacts,
    "bulk_update_leads":           bulk_update_leads,
    "bulk_update_accounts":        bulk_update_accounts,
    "bulk_update_opportunities":   bulk_update_opportunities,

    # Report tools
    "list_reports":                list_reports,
    "get_data_quality_report":     get_data_quality_report,
    "get_pipeline_report":         get_pipeline_report,
    "get_lead_source_report":      get_lead_source_report,
    "get_activity_report":         get_activity_report,

    # Email tools
    "send_email_to_contact":       send_email_to_contact,
    "send_email_to_lead":          send_email_to_lead,
    "send_bulk_email":             send_bulk_email,
    "get_email_history":           get_email_history,

    # Activities tools
    "get_tasks":                   get_tasks,
    "create_task":                 create_task,
    "complete_task":               complete_task,
    "get_phone_calls":             get_phone_calls,
    "log_phone_call":              log_phone_call,
    "get_appointments":            get_appointments,
    "create_appointment":          create_appointment,
    "get_notes":                   get_notes,
    "add_note":                    add_note,
    "get_activity_timeline":       get_activity_timeline,

    # Audit log tools
    "get_audit_history":           get_audit_history,
    "get_recent_changes":          get_recent_changes,
    "get_deleted_records":         get_deleted_records,
    "check_audit_status":          check_audit_status,

    # Cloud flow (Power Automate) tools
    "list_cloud_flows":            list_cloud_flows,
    "get_cloud_flow_details":      get_cloud_flow_details,
    "get_cloud_flow_run_history":  get_cloud_flow_run_history,
    "enable_cloud_flow":           enable_cloud_flow,
    "disable_cloud_flow":          disable_cloud_flow,
    "search_cloud_flows":          search_cloud_flows,
    "get_cloud_flows_by_entity":   get_cloud_flows_by_entity,
    "check_cloud_flow_health":     check_cloud_flow_health,
    "compare_classic_vs_cloud_flows": compare_classic_vs_cloud_flows,

    # Security tools
    "list_security_roles":         list_security_roles,
    "get_role_details":            get_role_details,
    "search_roles":                search_roles,
    "list_users":                  list_users,
    "get_user_details":            get_user_details,
    "search_users":                search_users,
    "assign_role_to_user":         assign_role_to_user,
    "remove_role_from_user":       remove_role_from_user,
    "get_users_with_no_roles":     get_users_with_no_roles,
    "get_admin_users":             get_admin_users,
    "get_security_summary":        get_security_summary,
}


# ============================================================
# TOOL DEFINITIONS — Schema Claude uses to understand its tools
# ============================================================
# Claude reads these to know what parameters each tool takes.

TOOL_DEFINITIONS = [
    {
        "name": "update_crm_memory",
        "description": "Save something you learned about this CRM to persistent memory so you remember it next session. Use this when you discover field names, entity names, user IDs, or other CRM-specific facts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Memory section (e.g. 'key_fields', 'agent_notes', 'known_views')"},
                "key":     {"type": "string", "description": "Key name within the section"},
                "value":   {"description": "Value to store (string, number, list, or object)"},
            },
            "required": ["section", "key", "value"],
        },
    },
    {
        "name": "read_crm_memory",
        "description": "Read the full persistent CRM memory to see what is already known about this CRM.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_session_summary",
        "description": "Save a summary of this conversation to persistent memory so it can be recalled next session. Call this when wrapping up or after completing significant work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary":        {"type": "string", "description": "2-4 sentence description of what was discussed and done this session"},
                "actions_taken":  {"type": "array",  "items": {"type": "string"}, "description": "List of specific changes made to the CRM"},
                "decisions_made": {"type": "array",  "items": {"type": "string"}, "description": "List of user preferences or decisions expressed (e.g. 'user prefers dashboards sorted by owner')"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "get_conversation_history",
        "description": "Read summaries of past conversation sessions to recall what was previously discussed, what changes were made, and what the user prefers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many past sessions to return (default 5)"},
            },
        },
    },
    {
        "name": "search_contacts",
        "description": "Search for contacts in the CRM by name, email, or company. Leave search_term blank to get all contacts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Name, email or company to search for"},
                "limit": {"type": "integer", "description": "Max results to return (default 50)"},
            },
        },
    },
    {
        "name": "find_contacts_missing_data",
        "description": "Find contacts that are missing important fields like email, phone, or company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": ["email", "phone", "company", "name"],
                    "description": "Which field to check for missing data",
                },
            },
            "required": ["field"],
        },
    },
    {
        "name": "find_duplicate_contacts",
        "description": "Find contacts that share the same email address (potential duplicates).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_contact",
        "description": "Update a contact's fields in the CRM. Only use this after confirming with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "The unique ID of the contact to update"},
                "updates": {"type": "object", "description": "Fields to update as key-value pairs"},
            },
            "required": ["contact_id", "updates"],
        },
    },
    {
        "name": "get_contact_details",
        "description": "Get all fields for a specific contact by their ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "The unique ID of the contact"},
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "get_contact_summary",
        "description": "Get a high-level summary of all contacts: total count, active/inactive, data quality metrics.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_workflows",
        "description": "List all workflows in the CRM. Filter by status: all, active, inactive, or draft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["all", "active", "inactive", "draft"],
                    "description": "Filter by workflow status",
                },
            },
        },
    },
    {
        "name": "get_workflow_details",
        "description": "Get detailed information about a specific workflow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "The unique ID of the workflow"},
            },
            "required": ["workflow_id"],
        },
    },
    {
        "name": "check_workflow_health",
        "description": "Check the health of all workflows. Identifies failures, stuck workflows, and inactive drafts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_workflow_runs",
        "description": "Show recent workflow execution history with success/failure status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent runs to show (default 20)"},
            },
        },
    },
    {
        "name": "activate_workflow",
        "description": "Activate a workflow that is currently inactive or in draft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "The unique ID of the workflow to activate"},
            },
            "required": ["workflow_id"],
        },
    },
    {
        "name": "deactivate_workflow",
        "description": "Deactivate a workflow that is currently active.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "The workflow ID to deactivate"},
                "reason": {"type": "string", "description": "Reason for deactivating"},
            },
            "required": ["workflow_id"],
        },
    },
    {
        "name": "search_workflows",
        "description": "Search for workflows by name or the entity they run on (contact, lead, opportunity, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Part of the workflow name to search for"},
                "entity": {"type": "string", "description": "Optional entity filter, e.g. 'contact', 'lead'"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "get_workflows_by_entity",
        "description": "List all workflows that are triggered by a specific entity type (contact, lead, account, opportunity).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name, e.g. 'contact', 'lead', 'opportunity'"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "retry_failed_workflow_runs",
        "description": "Find recently failed workflow runs and retry them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max number of failed runs to retry (default 10)"},
            },
        },
    },
    {
        "name": "clone_workflow",
        "description": "Clone an existing workflow under a new name. The clone is created as a Draft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "The GUID of the workflow to clone"},
                "new_name": {"type": "string", "description": "Name for the cloned workflow"},
            },
            "required": ["workflow_id", "new_name"],
        },
    },
    {
        "name": "list_views",
        "description": "List all saved views for a CRM entity (contact, lead, account, opportunity).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["contact", "lead", "account", "opportunity"],
                    "description": "The entity type to list views for",
                },
            },
        },
    },
    {
        "name": "create_contact_view",
        "description": "Create a new saved view for contacts with specific filter criteria.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name of the view"},
                "description": {"type": "string", "description": "Description of what this view shows"},
                "filter_criteria": {"type": "string", "description": "Plain English description of the filter (e.g. 'missing email', 'active only')"},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Column field names to display"},
            },
            "required": ["name", "description", "filter_criteria"],
        },
    },
    {
        "name": "list_dashboards",
        "description": "List all dashboards currently in the CRM.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_dashboard",
        "description": "Create a new dashboard in the CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Dashboard name"},
                "description": {"type": "string", "description": "What this dashboard shows"},
                "components": {
                    "type": "array",
                    "description": "List of components: each has type (chart/list), title, entity",
                    "items": {"type": "object"},
                },
            },
            "required": ["name", "description"],
        },
    },
    {
        "name": "delete_dashboard",
        "description": "Delete a personal dashboard by name or ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string", "description": "Dashboard name or GUID to delete"},
            },
            "required": ["name_or_id"],
        },
    },
    {
        "name": "publish_all_dashboards",
        "description": "Publish all dashboards so they become visible in the CRM. Use this if dashboards exist but are not showing up in the UI.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_views_summary",
        "description": "Get a summary of all views across contacts, leads, accounts, and opportunities.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dashboard_details",
        "description": "Fetch a specific dashboard by name or ID. Returns the full layout XML and component labels — use this to inspect a dashboard before reordering it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string", "description": "The dashboard display name (e.g. 'D2C/Crossfit') or its GUID"},
            },
            "required": ["name_or_id"],
        },
    },
    {
        "name": "reorder_dashboard_components",
        "description": "Reorder a dashboard so that specific components appear at the top. Always call get_dashboard_details first to get the dashboard ID and confirm the exact component label names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dashboard_id": {"type": "string", "description": "The GUID of the dashboard to modify"},
                "move_to_top": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of component label substrings to move to the top (case-insensitive partial match), e.g. ['Teams by owner', 'Teams by status']",
                },
            },
            "required": ["dashboard_id", "move_to_top"],
        },
    },
    # ── Opportunities ──────────────────────────────────────────
    {
        "name": "search_opportunities",
        "description": "Search for opportunities/deals. Filter by status: open, won, lost, or all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Name or account name to search for"},
                "status": {"type": "string", "enum": ["open", "won", "lost", "all"], "description": "Filter by deal status"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
    },
    {
        "name": "get_opportunity_details",
        "description": "Get all details for a specific opportunity by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"opportunity_id": {"type": "string", "description": "The opportunity GUID"}},
            "required": ["opportunity_id"],
        },
    },
    {
        "name": "update_opportunity",
        "description": "Update an opportunity's fields such as name, value, close probability, or estimated close date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "opportunity_id": {"type": "string", "description": "The opportunity GUID"},
                "updates": {"type": "object", "description": "Fields to update as key-value pairs"},
            },
            "required": ["opportunity_id", "updates"],
        },
    },
    {
        "name": "get_opportunity_summary",
        "description": "Get pipeline overview: total open/won/lost counts, pipeline value, and win rate.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_stalled_opportunities",
        "description": "Find open opportunities that haven't been updated recently.",
        "input_schema": {
            "type": "object",
            "properties": {"days_inactive": {"type": "integer", "description": "Days without activity (default 30)"}},
        },
    },
    # ── Accounts ───────────────────────────────────────────────
    {
        "name": "search_accounts",
        "description": "Search for accounts (companies) by name or city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Company name or city to search for"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
    },
    {
        "name": "get_account_details",
        "description": "Get full details for an account including its linked contacts and open opportunities.",
        "input_schema": {
            "type": "object",
            "properties": {"account_id": {"type": "string", "description": "The account GUID"}},
            "required": ["account_id"],
        },
    },
    {
        "name": "update_account",
        "description": "Update an account's fields such as phone, website, or address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The account GUID"},
                "updates": {"type": "object", "description": "Fields to update as key-value pairs"},
            },
            "required": ["account_id", "updates"],
        },
    },
    {
        "name": "get_account_summary",
        "description": "Get a summary of all accounts: total count, active/inactive, top states.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_accounts_missing_data",
        "description": "Find active accounts missing email, phone, website, or address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "enum": ["email", "phone", "website", "address"], "description": "Which field to check"},
            },
            "required": ["field"],
        },
    },
    # ── Leads ──────────────────────────────────────────────────
    {
        "name": "search_leads",
        "description": "Search for leads by name, email, or company. Filter by status: open, qualified, disqualified, or all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Name, email, or company to search for"},
                "status": {"type": "string", "enum": ["open", "qualified", "disqualified", "all"], "description": "Filter by lead status"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
    },
    {
        "name": "get_lead_details",
        "description": "Get all details for a specific lead by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"lead_id": {"type": "string", "description": "The lead GUID"}},
            "required": ["lead_id"],
        },
    },
    {
        "name": "update_lead",
        "description": "Update a lead's fields such as email, phone, company, or notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "The lead GUID"},
                "updates": {"type": "object", "description": "Fields to update as key-value pairs"},
            },
            "required": ["lead_id", "updates"],
        },
    },
    {
        "name": "qualify_lead",
        "description": "Qualify a lead — marks it as qualified and creates a contact, account, and opportunity.",
        "input_schema": {
            "type": "object",
            "properties": {"lead_id": {"type": "string", "description": "The lead GUID to qualify"}},
            "required": ["lead_id"],
        },
    },
    {
        "name": "get_lead_summary",
        "description": "Get a summary of all leads: counts by status and top lead sources.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_stale_leads",
        "description": "Find open leads that haven't been updated recently.",
        "input_schema": {
            "type": "object",
            "properties": {"days_inactive": {"type": "integer", "description": "Days without activity (default 14)"}},
        },
    },
    # ── Special Terms (STR) ────────────────────────────────────
    {
        "name": "search_special_terms",
        "description": "Search Special Terms (STR) records by title, record number, or account name. Filter by approval status: submitted, approved, rejected, draft, or all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "STR number (ST-...), title, or account name"},
                "status": {"type": "string", "enum": ["all", "submitted", "approved", "rejected", "draft"], "description": "Filter by approval status"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
    },
    {
        "name": "get_special_terms_details",
        "description": "Get full details for a specific STR record including approval status, dates, request type, and all fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "str_id": {"type": "string", "description": "The GUID of the Special Terms record"},
            },
            "required": ["str_id"],
        },
    },
    {
        "name": "get_pending_approvals",
        "description": "Find all STR records currently awaiting approval (submitted but not yet approved or rejected).",
        "input_schema": {
            "type": "object",
            "properties": {
                "approver_role": {"type": "string", "enum": ["all", "sales", "finance"], "description": "Filter by which approval level is pending"},
            },
        },
    },
    {
        "name": "get_special_terms_by_account",
        "description": "Get all STR records linked to a specific account by account name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Full or partial account name, e.g. 'South Bay Aquatic'"},
            },
            "required": ["account_name"],
        },
    },
    {
        "name": "get_expiring_special_terms",
        "description": "Find STR records expiring within a given number of days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days ahead to look (default 30)"},
            },
        },
    },
    {
        "name": "get_special_terms_summary",
        "description": "Get a high-level summary of all STR records: counts by approval status and request type.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_str_workflows",
        "description": "Find all workflows related to the Special Terms approval process — both by entity and by name keyword (approval, STR, special terms).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_special_terms",
        "description": "Update fields on a Special Terms record such as expiration date, title, or request type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "str_id": {"type": "string", "description": "The GUID of the STR record"},
                "updates": {"type": "object", "description": "Fields to update as key-value pairs"},
            },
            "required": ["str_id", "updates"],
        },
    },
    # ── Form Customization ─────────────────────────────────────
    {
        "name": "get_entity_form",
        "description": "Fetch the current main form definition for an entity and list all fields currently on it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name, e.g. 'opportunity', 'contact', 'lead'"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "list_entity_fields",
        "description": "List all available fields on an entity. Use this to find exact field logical names before adding them to a form.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name, e.g. 'opportunity'"},
                "search_term": {"type": "string", "description": "Optional filter by field name or label"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "get_optionset_values",
        "description": "Get all dropdown options for an option set field on an entity. Use this to see existing values before creating a new field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name, e.g. 'opportunity'"},
                "field_name": {"type": "string", "description": "Logical field name, e.g. 'tyr_tyrtype'"},
            },
            "required": ["entity", "field_name"],
        },
    },
    {
        "name": "add_fields_to_form",
        "description": "Add one or more fields to an entity's main form. Use get_entity_form first to see what's already there, and list_entity_fields to confirm field names. Publishes automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name, e.g. 'opportunity'"},
                "fields": {
                    "type": "array",
                    "description": "List of field logical names to add, e.g. ['ownerid','estimatedclosedate']. For subgrids use objects: {type:'subgrid', name:'Contacts', entity:'contact', relationship:'...'}",
                    "items": {},
                },
                "section_label": {"type": "string", "description": "Section heading to add fields under (default 'Details')"},
            },
            "required": ["entity", "fields"],
        },
    },
    {
        "name": "create_custom_field",
        "description": "Create a new custom field on an entity. For option sets, provide a list of dropdown options. Returns the logical name to use with add_fields_to_form.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name, e.g. 'opportunity'"},
                "display_name": {"type": "string", "description": "Human-readable label, e.g. 'TYR Type'"},
                "field_type": {"type": "string", "enum": ["text", "date", "optionset", "boolean", "number", "currency"], "description": "Field data type"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "For optionset only — list of dropdown option labels"},
            },
            "required": ["entity", "display_name", "field_type"],
        },
    },
    # ── Teams ──────────────────────────────────────────────────
    {
        "name": "list_teams",
        "description": "List all teams in the CRM. Filter by type: owner, access, or all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_type": {"type": "string", "enum": ["owner", "access", "all"], "description": "Filter by team type"},
            },
        },
    },
    {
        "name": "get_team_details",
        "description": "Get full details for a team including its members.",
        "input_schema": {
            "type": "object",
            "properties": {"team_id": {"type": "string", "description": "The team GUID"}},
            "required": ["team_id"],
        },
    },
    {
        "name": "search_teams",
        "description": "Search for teams by name.",
        "input_schema": {
            "type": "object",
            "properties": {"search_term": {"type": "string", "description": "Part of the team name to search for"}},
            "required": ["search_term"],
        },
    },
    {
        "name": "get_team_summary",
        "description": "Get a summary of all teams: counts by type and business unit.",
        "input_schema": {"type": "object", "properties": {}},
    },
    # ── Dashboard extras ───────────────────────────────────────
    {
        "name": "clone_dashboard",
        "description": "Clone an existing dashboard under a new name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_name_or_id": {"type": "string", "description": "Name or GUID of the dashboard to copy"},
                "new_name": {"type": "string", "description": "Name for the cloned dashboard"},
                "new_description": {"type": "string", "description": "Optional description for the clone"},
            },
            "required": ["source_name_or_id", "new_name"],
        },
    },
    {
        "name": "set_dashboard_description",
        "description": "Update the description of an existing dashboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string", "description": "Name or GUID of the dashboard"},
                "description": {"type": "string", "description": "New description text"},
            },
            "required": ["name_or_id", "description"],
        },
    },
    # ── Bulk updates ───────────────────────────────────────────
    {
        "name": "bulk_update_contacts",
        "description": "Update multiple contacts at once that match a filter. Use preview_only=True first to confirm which records will be affected.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_criteria": {"type": "string", "description": "OData filter to select records, e.g. 'statecode eq 0 and emailaddress1 eq null'"},
                "updates": {"type": "object", "description": "Fields to set on every matched record"},
                "preview_only": {"type": "boolean", "description": "If true, show matches without updating (default false)"},
            },
            "required": ["filter_criteria", "updates"],
        },
    },
    {
        "name": "bulk_update_leads",
        "description": "Update multiple leads at once that match a filter. Use preview_only=True first to confirm scope.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_criteria": {"type": "string", "description": "OData filter to select leads"},
                "updates": {"type": "object", "description": "Fields to set on every matched lead"},
                "preview_only": {"type": "boolean", "description": "If true, show matches without updating"},
            },
            "required": ["filter_criteria", "updates"],
        },
    },
    {
        "name": "bulk_update_accounts",
        "description": "Update multiple accounts at once that match a filter. Use preview_only=True first to confirm scope.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_criteria": {"type": "string", "description": "OData filter to select accounts"},
                "updates": {"type": "object", "description": "Fields to set on every matched account"},
                "preview_only": {"type": "boolean", "description": "If true, show matches without updating"},
            },
            "required": ["filter_criteria", "updates"],
        },
    },
    {
        "name": "bulk_update_opportunities",
        "description": "Update multiple opportunities at once that match a filter. Use preview_only=True first to confirm scope.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_criteria": {"type": "string", "description": "OData filter to select opportunities"},
                "updates": {"type": "object", "description": "Fields to set on every matched opportunity"},
                "preview_only": {"type": "boolean", "description": "If true, show matches without updating"},
            },
            "required": ["filter_criteria", "updates"],
        },
    },
    # ── Reports ────────────────────────────────────────────────
    {
        "name": "list_reports",
        "description": "List reports stored in the CRM. Filter by category: account, contact, lead, opportunity, custom, or all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["all", "account", "contact", "lead", "opportunity", "custom"], "description": "Report category filter"},
            },
        },
    },
    {
        "name": "get_data_quality_report",
        "description": "Generate a live data quality report across contacts, leads, and accounts showing missing fields and completeness percentages.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pipeline_report",
        "description": "Generate a live pipeline report: total value, weighted value, breakdown by owner and probability.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_lead_source_report",
        "description": "Report showing lead volume and conversion rates broken down by lead source.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_activity_report",
        "description": "Show recent CRM activity counts (emails, calls, tasks) for a given number of days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days back to look (default 30)"},
            },
        },
    },
    # ── Email ──────────────────────────────────────────────────
    {
        "name": "send_email_to_contact",
        "description": "Send an email to a single contact and log it as a CRM activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "The contact GUID"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["contact_id", "subject", "body"],
        },
    },
    {
        "name": "send_email_to_lead",
        "description": "Send an email to a single lead and log it as a CRM activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "The lead GUID"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["lead_id", "subject", "body"],
        },
    },
    {
        "name": "send_bulk_email",
        "description": "Send the same email to multiple contacts or leads matching a filter. Always use preview_only=True first to confirm recipients.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": ["contact", "lead"], "description": "Whether to email contacts or leads"},
                "filter_criteria": {"type": "string", "description": "OData filter to select recipients"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
                "preview_only": {"type": "boolean", "description": "If true, show recipient list without sending"},
            },
            "required": ["entity", "filter_criteria", "subject", "body"],
        },
    },
    {
        "name": "get_email_history",
        "description": "Get the email activity history for a contact or lead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "Contact GUID (provide this or lead_id)"},
                "lead_id": {"type": "string", "description": "Lead GUID (provide this or contact_id)"},
                "limit": {"type": "integer", "description": "Max emails to return (default 20)"},
            },
        },
    },

    # ── ACTIVITIES ──────────────────────────────────────────
    {
        "name": "get_tasks",
        "description": "Get tasks (to-do items) from the CRM, optionally filtered by record and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regarding_id":   {"type": "string", "description": "ID of the record to get tasks for (leave blank for all tasks)"},
                "regarding_type": {"type": "string", "description": "Type of record: contact, lead, account, opportunity"},
                "status":         {"type": "string", "description": "open, completed, or all"},
                "limit":          {"type": "integer", "description": "Max tasks to return (default 50)"},
            },
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task (to-do item) linked to a CRM record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":        {"type": "string", "description": "Short title for the task"},
                "regarding_id":   {"type": "string", "description": "ID of the record to attach this task to"},
                "regarding_type": {"type": "string", "description": "Type: contact, lead, account, opportunity"},
                "description":    {"type": "string", "description": "Longer notes about what needs to be done"},
                "due_date":       {"type": "string", "description": "Due date in YYYY-MM-DD format"},
                "priority":       {"type": "string", "description": "low, normal, or high"},
            },
            "required": ["subject", "regarding_id"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The ID of the task to complete"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_phone_calls",
        "description": "Get logged phone call records from the CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regarding_id": {"type": "string", "description": "ID of the record to get calls for (leave blank for all)"},
                "status":       {"type": "string", "description": "all, open, or completed"},
                "limit":        {"type": "integer", "description": "Max records to return (default 50)"},
            },
        },
    },
    {
        "name": "log_phone_call",
        "description": "Log a phone call against a CRM record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":        {"type": "string", "description": "What the call was about"},
                "regarding_id":   {"type": "string", "description": "ID of the contact, lead, account, or opportunity"},
                "regarding_type": {"type": "string", "description": "Type: contact, lead, account, opportunity"},
                "description":    {"type": "string", "description": "Notes from the call"},
                "direction":      {"type": "string", "description": "outbound (you called them) or inbound (they called you)"},
                "call_date":      {"type": "string", "description": "When the call happened — YYYY-MM-DDTHH:MM:SSZ"},
            },
            "required": ["subject", "regarding_id"],
        },
    },
    {
        "name": "get_appointments",
        "description": "Get appointments (meetings) from the CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regarding_id": {"type": "string", "description": "ID of the record to get appointments for"},
                "status":       {"type": "string", "description": "upcoming, completed, or all"},
                "limit":        {"type": "integer", "description": "Max records to return (default 50)"},
            },
        },
    },
    {
        "name": "create_appointment",
        "description": "Create a new appointment (meeting) in the CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":        {"type": "string", "description": "Title of the meeting"},
                "start":          {"type": "string", "description": "Start time — YYYY-MM-DDTHH:MM:SSZ"},
                "end":            {"type": "string", "description": "End time — YYYY-MM-DDTHH:MM:SSZ"},
                "regarding_id":   {"type": "string", "description": "ID of the record to link this to (optional)"},
                "regarding_type": {"type": "string", "description": "Type: contact, lead, account, opportunity"},
                "location":       {"type": "string", "description": "Where the meeting is"},
                "description":    {"type": "string", "description": "Agenda or notes"},
            },
            "required": ["subject", "start", "end"],
        },
    },
    {
        "name": "get_notes",
        "description": "Get all notes attached to a CRM record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regarding_id":   {"type": "string", "description": "ID of the record to get notes for"},
                "regarding_type": {"type": "string", "description": "Type: contact, lead, account, opportunity"},
                "limit":          {"type": "integer", "description": "Max notes to return (default 50)"},
            },
            "required": ["regarding_id"],
        },
    },
    {
        "name": "add_note",
        "description": "Add a note to a CRM record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regarding_id":   {"type": "string", "description": "ID of the record to attach the note to"},
                "regarding_type": {"type": "string", "description": "Type: contact, lead, account, opportunity"},
                "text":           {"type": "string", "description": "The body of the note"},
                "subject":        {"type": "string", "description": "Short title for the note"},
            },
            "required": ["regarding_id", "regarding_type", "text"],
        },
    },
    {
        "name": "get_activity_timeline",
        "description": "Get the full activity timeline for a CRM record — all tasks, calls, appointments, and notes in one view.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regarding_id":   {"type": "string", "description": "ID of the record"},
                "regarding_type": {"type": "string", "description": "Type: contact, lead, account, opportunity"},
                "limit":          {"type": "integer", "description": "Max items per activity type (default 30)"},
            },
            "required": ["regarding_id"],
        },
    },

    # ── AUDIT LOG ────────────────────────────────────────────
    {
        "name": "get_audit_history",
        "description": "Get the full change history for a specific CRM record — who changed what and when.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id":   {"type": "string", "description": "The ID of the record to inspect"},
                "record_type": {"type": "string", "description": "Type: contact, lead, account, opportunity, workflow"},
                "limit":       {"type": "integer", "description": "Max audit entries to return (default 50)"},
            },
            "required": ["record_id"],
        },
    },
    {
        "name": "get_recent_changes",
        "description": "Get all recent changes across a record type in the last N hours — useful for daily audits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "description": "contact, lead, account, or opportunity"},
                "hours":       {"type": "integer", "description": "How far back to look (default 24)"},
                "limit":       {"type": "integer", "description": "Max records to return (default 100)"},
            },
        },
    },
    {
        "name": "get_deleted_records",
        "description": "Find recently deleted records of a given type — useful for recovering accidentally deleted data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "description": "contact, lead, account, or opportunity"},
                "limit":       {"type": "integer", "description": "Max records to return (default 50)"},
            },
        },
    },
    {
        "name": "check_audit_status",
        "description": "Check whether auditing is enabled in this Dynamics 365 org.",
        "input_schema": {"type": "object", "properties": {}},
    },

    # ── CLOUD FLOWS ──────────────────────────────────────────
    {
        "name": "list_cloud_flows",
        "description": "List all Power Automate cloud flows connected to this CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "all, active, or inactive"},
            },
        },
    },
    {
        "name": "get_cloud_flow_details",
        "description": "Get detailed information about a specific cloud flow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "string", "description": "The ID of the cloud flow"},
            },
            "required": ["flow_id"],
        },
    },
    {
        "name": "get_cloud_flow_run_history",
        "description": "Get the recent run history for a cloud flow — shows success/failure and timing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "string", "description": "The ID of the cloud flow"},
                "limit":   {"type": "integer", "description": "Max run records to return (default 20)"},
            },
            "required": ["flow_id"],
        },
    },
    {
        "name": "enable_cloud_flow",
        "description": "Enable (turn on) a Power Automate cloud flow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "string", "description": "The ID of the cloud flow to enable"},
            },
            "required": ["flow_id"],
        },
    },
    {
        "name": "disable_cloud_flow",
        "description": "Disable (turn off) a Power Automate cloud flow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "string", "description": "The ID of the cloud flow to disable"},
            },
            "required": ["flow_id"],
        },
    },
    {
        "name": "search_cloud_flows",
        "description": "Search for cloud flows by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Part of the flow name to search for"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "get_cloud_flows_by_entity",
        "description": "Get all cloud flows that trigger on a specific entity type (e.g. contact, lead).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "The entity name — e.g. contact, lead, account, opportunity"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "check_cloud_flow_health",
        "description": "Run a health check across all cloud flows — finds inactive flows and recent failures.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compare_classic_vs_cloud_flows",
        "description": "Compare the count of classic CRM workflows vs modern Power Automate cloud flows.",
        "input_schema": {"type": "object", "properties": {}},
    },

    # ── SECURITY ─────────────────────────────────────────────
    {
        "name": "list_security_roles",
        "description": "List all security roles defined in this Dynamics 365 org.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max roles to return (default 100)"},
            },
        },
    },
    {
        "name": "get_role_details",
        "description": "Get details about a security role including which users have it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role_id": {"type": "string", "description": "The ID of the security role"},
            },
            "required": ["role_id"],
        },
    },
    {
        "name": "search_roles",
        "description": "Search for security roles by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Part of the role name to search for"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "list_users",
        "description": "List users in the Dynamics 365 org.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "active, disabled, or all"},
                "limit":  {"type": "integer", "description": "Max users to return (default 100)"},
            },
        },
    },
    {
        "name": "get_user_details",
        "description": "Get full details for a user including their assigned security roles.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The systemuserid of the user"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "search_users",
        "description": "Search for users by name or email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Part of the name or email to search for"},
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "assign_role_to_user",
        "description": "Assign a security role to a user. WARNING: This changes what the user can access.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The ID of the user"},
                "role_id": {"type": "string", "description": "The ID of the security role to assign"},
            },
            "required": ["user_id", "role_id"],
        },
    },
    {
        "name": "remove_role_from_user",
        "description": "Remove a security role from a user. WARNING: This reduces what the user can do.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The ID of the user"},
                "role_id": {"type": "string", "description": "The ID of the security role to remove"},
            },
            "required": ["user_id", "role_id"],
        },
    },
    {
        "name": "get_users_with_no_roles",
        "description": "Find active users who have no security roles assigned — these users can't do anything in the CRM.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_admin_users",
        "description": "Find all users with System Administrator access — the highest privilege in Dynamics 365.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_security_summary",
        "description": "Get a high-level security overview — total users, admins, disabled accounts, and role coverage.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def run_agent(user_request: str, dry_run: bool = False,
              session_messages: list = None) -> tuple:
    """
    Run the CRM agent with a plain English request.

    user_request:     what you want the agent to do (plain English)
    dry_run:          if True, Claude will plan actions but NOT execute writes
    session_messages: the conversation history from earlier in this session.
                      Pass the list returned by a previous call to maintain
                      multi-turn memory within a session.

    Returns (response_text, updated_session_messages) so the caller can
    pass the messages back on the next turn.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Load persistent CRM memory if available
    memory_context = ""
    memory_path = os.path.join(os.path.dirname(__file__), "crm_memory.json")
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r") as f:
                memory = json.load(f)
            memory_context = f"\n\nCRM MEMORY (persistent knowledge about this specific CRM):\n{json.dumps(memory, indent=2)}"
        except Exception:
            pass

    # Add dry_run instruction if needed
    system = SYSTEM_PROMPT + memory_context
    if dry_run:
        system += (
            "\n\nDRY RUN MODE: You may READ data freely, but do NOT call any tools "
            "that create, update, or delete records. Instead, describe what you WOULD do."
        )

    # Build message list — continue from prior turns if provided.
    # Keep only the last 10 messages, but always trim to a clean boundary:
    # never start the history mid-turn with a tool_result block, since the
    # API requires every tool_result to have a matching tool_use before it.
    prior = list(session_messages) if session_messages else []
    if len(prior) > 10:
        prior = prior[-10:]
        # Walk forward until we find a plain user text message (not tool results)
        # so we never start the context with orphaned tool_result blocks.
        for i, msg in enumerate(prior):
            content = msg.get("content", "")
            is_tool_result = (
                isinstance(content, list)
                and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
            )
            if msg.get("role") == "user" and not is_tool_result:
                prior = prior[i:]
                break
        else:
            prior = []  # no clean starting point — start fresh
    messages = prior + [{"role": "user", "content": user_request}]

    # Set up logging
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_entries = []

    print("\n" + "═" * 60)
    print("  CRM Agent is working on your request...")
    print("═" * 60)

    # Agentic loop — Claude keeps working until the task is done
    while True:
        # Retry up to 3 times on rate limit errors, waiting between each attempt
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=system,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )
                break  # success — exit retry loop
            except anthropic.RateLimitError:
                if attempt < 2:
                    import time
                    wait = 60 * (attempt + 1)  # 60s, then 120s
                    print(f"\n  ⏳ Rate limit reached — waiting {wait}s (press Ctrl+C to cancel)...")
                    try:
                        for _ in range(wait):
                            time.sleep(1)
                    except KeyboardInterrupt:
                        print("\n  Cancelled.")
                        return "Request cancelled.", messages
                else:
                    raise

        # Check if Claude is done (no more tools to call)
        if response.stop_reason == "end_turn":
            # Extract the final text response
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break

            # Append Claude's response so the next turn has full context
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": final_text}
            ]})

            # Save the log
            with open(log_file, "w") as f:
                json.dump({"request": user_request, "actions": log_entries}, f, indent=2)

            return final_text, messages

        # Claude wants to use a tool — execute it
        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    print(f"\n  → {tool_name}({', '.join(f'{k}={repr(v)}' for k, v in tool_input.items())})")

                    # Execute the tool
                    try:
                        tool_fn = TOOL_REGISTRY.get(tool_name)
                        if not tool_fn:
                            result = {"error": f"Tool '{tool_name}' not found"}
                        else:
                            result = tool_fn(**tool_input)

                        # Log the action
                        log_entries.append({
                            "timestamp": datetime.now().isoformat(),
                            "tool": tool_name,
                            "input": tool_input,
                            "result_summary": str(result)[:200],
                        })

                    except Exception as e:
                        result = {"error": str(e)}
                        print(f"     ⚠ Error: {e}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            # Brief pause between tool call rounds to avoid rate limits
            import time
            try:
                time.sleep(3)
            except KeyboardInterrupt:
                print("\n  Cancelled.")
                return "Request cancelled.", messages

            # Feed the tool results back to Claude so it can continue
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason — break the loop
            break

    return "Task completed.", messages
