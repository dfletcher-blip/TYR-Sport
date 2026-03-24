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
)
from tools.views_dashboards import (
    list_views,
    create_contact_view,
    list_dashboards,
    create_dashboard,
    get_views_summary,
    get_dashboard_details,
    reorder_dashboard_components,
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
4. DASHBOARDS — List existing dashboards, create new ones

HOW YOU WORK:
- Always start by READING data before making any changes
- Always EXPLAIN what you found before doing anything
- For any UPDATE or CREATE action, state what you are about to do and why
- After completing a task, give a clear SUMMARY of what was done
- If something could cause problems, warn the user first

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
    # Contact tools
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

    # Views & dashboard tools
    "list_views":                  list_views,
    "create_contact_view":         create_contact_view,
    "list_dashboards":             list_dashboards,
    "create_dashboard":            create_dashboard,
    "get_views_summary":           get_views_summary,
    "get_dashboard_details":       get_dashboard_details,
    "reorder_dashboard_components": reorder_dashboard_components,
}


# ============================================================
# TOOL DEFINITIONS — Schema Claude uses to understand its tools
# ============================================================
# Claude reads these to know what parameters each tool takes.

TOOL_DEFINITIONS = [
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
]


def run_agent(user_request: str, dry_run: bool = False) -> str:
    """
    Run the CRM agent with a plain English request.

    user_request: what you want the agent to do (plain English)
    dry_run: if True, Claude will plan actions but NOT execute writes
             Use this to preview what the agent would do before committing.

    Returns Claude's response as a string.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Add dry_run instruction if needed
    system = SYSTEM_PROMPT
    if dry_run:
        system += (
            "\n\nDRY RUN MODE: You may READ data freely, but do NOT call any tools "
            "that create, update, or delete records. Instead, describe what you WOULD do."
        )

    messages = [{"role": "user", "content": user_request}]

    # Set up logging
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_entries = []

    print("\n" + "═" * 60)
    print("  CRM Agent is working on your request...")
    print("═" * 60)

    # Agentic loop — Claude keeps working until the task is done
    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},  # Let Claude reason through complex tasks
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Check if Claude is done (no more tools to call)
        if response.stop_reason == "end_turn":
            # Extract the final text response
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break

            # Save the log
            with open(log_file, "w") as f:
                json.dump({"request": user_request, "actions": log_entries}, f, indent=2)

            return final_text

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

            # Feed the tool results back to Claude so it can continue
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason — break the loop
            break

    return "Task completed."
