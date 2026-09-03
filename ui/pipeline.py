"""Derives a mission-control pipeline trace from a backend result dict.

The backend (`run_travel_agent` / `resume_travel_agent`) makes a single
blocking `travel_graph.invoke(...)` call and returns the final state. There
is no true streaming of intermediate node events without re-invoking the
graph a second time (which would double LLM/MCP cost and race the Postgres
checkpointer against the same thread_id). Instead, node status is derived
post-hoc from which fields are populated in the returned result.
"""

from typing import Any

DONE = "done"
SKIPPED = "skipped"
BLOCKED = "blocked"
PENDING = "pending"
WAITING = "waiting"

# (key, label, result field that indicates completion, agent name used in
# selected_agents -- None for nodes that always run)
NODE_DEFS = [
    ("supervisor", "Supervisor", None, None),
    ("guardrail", "Guardrails", None, None),
    ("flight_agent", "Flight Agent (MCP)", "flight_results", "flight_agent"),
    ("hotel_agent", "Hotel Agent", "hotel_results", "hotel_agent"),
    ("weather_agent", "Weather Agent (MCP)", "weather_results", "weather_agent"),
    ("budget_agent", "Budget Agent", "budget_results", "budget_agent"),
    ("itinerary_agent", "Itinerary Agent", "itinerary", "itinerary_agent"),
    ("output_guardrail", "Output Guardrail", None, None),
    ("human_approval", "HITL Gate", None, None),
    ("final_agent", "Final Response", "final_response", None),
]


def derive_pipeline_status(result: dict[str, Any]) -> dict[str, str]:
    status: dict[str, str] = {"supervisor": DONE}

    guardrail_allowed = result.get("guardrail_allowed", True)
    status["guardrail"] = DONE if guardrail_allowed else BLOCKED

    if not guardrail_allowed:
        for key, _, _, _ in NODE_DEFS[2:]:
            status[key] = SKIPPED
        return status

    selected = set(result.get("selected_agents") or [])

    for key, _, field, agent_name in NODE_DEFS[2:7]:
        if agent_name and agent_name not in selected:
            status[key] = SKIPPED
        else:
            status[key] = DONE if result.get(field) else PENDING

    # output_guardrail is an unconditional edge right after itinerary_agent,
    # so by the time the draft itinerary is populated the scan has run.
    status["output_guardrail"] = status["itinerary_agent"]
    status["human_approval"] = WAITING if result.get("requires_approval") else DONE
    status["final_agent"] = DONE if result.get("final_response") else PENDING

    return status


def node_detail(key: str, result: dict[str, Any]) -> str:
    """Short one-line detail text for a node, mirroring the mockup's style."""
    if key == "supervisor":
        agents = ", ".join(result.get("selected_agents") or []) or "itinerary_agent"
        return f"Routed to: {agents}"
    if key == "guardrail":
        if result.get("pii_flagged"):
            return result.get("pii_reason") or "Blocked: personal information detected"
        if result.get("guardrail_allowed", True):
            return "Input validated · no policy flags"
        return result.get("guardrail_reason") or "Request blocked by guardrail"
    destination, duration = _trip_context(result)
    if key == "flight_agent":
        if not result.get("flight_results"):
            return ""
        if destination and duration:
            return f"Generated travel guidance for {duration} trip to {destination}"
        return "Generated travel guidance via AviationStack MCP"
    if key == "hotel_agent":
        if not result.get("hotel_results"):
            return ""
        if destination and duration:
            return f"Found best hotel recommendations for {duration} in {destination}"
        return "Found best hotel recommendations"
    if key == "weather_agent":
        if not result.get("weather_results"):
            return ""
        if destination:
            return f"Fetched current weather for major cities in {destination}"
        return "Fetched current weather via MCP"
    if key == "budget_agent":
        return "Estimated cost categories and total budget" if result.get("budget_results") else ""
    if key == "itinerary_agent":
        return "Built day-by-day itinerary for human review" if result.get("itinerary") else ""
    if key == "human_approval":
        if result.get("requires_approval"):
            return "Awaiting human approval"
        if result.get("approved") is True:
            return "You approved the draft"
        if result.get("approved") is False:
            return "You requested changes"
        return ""
    if key == "output_guardrail":
        if not result.get("itinerary"):
            return ""
        redactions = result.get("output_redactions", 0) or 0
        if redactions:
            plural = "s" if redactions != 1 else ""
            return f"Redacted {redactions} sensitive item{plural} before human review"
        return "No sensitive data found in draft itinerary"
    if key == "final_agent":
        return "Final polished response generated" if result.get("final_response") else ""
    return ""


def _trip_context(result: dict[str, Any]) -> tuple[str, str]:
    constraints = result.get("trip_constraints") or {}
    return constraints.get("destination") or "", constraints.get("duration") or ""
