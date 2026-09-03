import os
import certifi
from dotenv import load_dotenv

load_dotenv()
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# =========================
# LangSmith tracing (optional)
#
# LangChain/LangGraph auto-instrument every LLM call once these env vars are
# set -- no code changes needed elsewhere. An explicit LANGCHAIN_TRACING_V2
# (e.g. set in secrets.toml) is always respected; otherwise tracing is
# turned on automatically as soon as a LANGCHAIN_API_KEY is present, so a
# deployment with neither set behaves exactly as before (no tracing
# attempted, no auth errors).
# =========================
if not os.getenv("LANGCHAIN_TRACING_V2") and os.getenv("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ.setdefault("LANGCHAIN_PROJECT", "TripMate")

from typing import Any, TypedDict, Annotated
import operator
import re
import uuid
import asyncio
import json
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command, interrupt
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq


from mcp_client import (
    aviation_mcp_call,
    tavily_mcp_search,
    extract_destination,
    forecast_mcp_search,
    weather_mcp_search,
)


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. "
            "Add your Postgres connection string (Neon/Supabase free tier "
            "both work) to the project .env file or Streamlit secrets."
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url


GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")

# =========================
# LLM
# =========================
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY,
)

# =========================
# State
# =========================
class TravelState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str

    # Supervisor + guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    pii_flagged: bool
    pii_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # Specialist results
    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str

    # Budget + HITL state
    budget_results: str
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str

    # Output guardrail state
    output_flagged: bool
    output_redactions: int

    llm_calls: int


# =========================
# Shared helpers
# =========================
KNOWN_AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
}

AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]


def _llm_text(system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content)


def _json_from_llm(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object returned by the model."""
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start : end + 1])


def _empty_constraints() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "climate": "",
        "special_preferences": [],
    }


# =========================
# PII detection/redaction (input + output guardrails)
#
# Regex-only and deterministic on purpose: no LLM call is needed to catch
# card numbers, SSNs, emails, phone numbers, and PAN numbers, so this check
# runs before any paid LLM/MCP work and can't be talked around by prompt
# phrasing the way an LLM-judged guardrail could.
# =========================
_CARD_CANDIDATE_RE = re.compile(r"(?:\d[ -]?){13,19}")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(
    # US-style 3-3-4 with separators, optionally country-coded.
    r"(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"
    # Country-coded 10-digit, split 5-5 or unsplit: "+91 98765 43210",
    # "+91-9876543210".
    r"|\+\d{1,3}[-.\s]?\d{5}[-.\s]?\d{5}\b"
    r"|\+\d{1,3}[-.\s]?\d{10}\b"
    # Bare Indian mobile: exactly 10 digits starting 6-9. Narrow enough to
    # skip budgets, years, and flight/confirmation codes.
    r"|\b[6-9]\d{9}\b"
)
# India's PAN (Permanent Account Number) tax ID: 5 letters, 4 digits, 1
# letter (e.g. ABCDE1234F).
_PAN_RE = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _find_credit_cards(text: str) -> list[str]:
    """Candidate 13-19 digit runs that also pass a Luhn checksum -- keeps
    ordinary long numbers (flight numbers, confirmation codes) from being
    misflagged as card numbers."""
    matches = []
    for candidate in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", candidate.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            matches.append(candidate.group())
    return matches


def _detect_pii(text: str) -> list[str]:
    """Human-readable labels for the categories of PII found, empty if none."""
    found = []
    if _find_credit_cards(text):
        found.append("a credit card number")
    if _SSN_RE.search(text):
        found.append("a Social Security number")
    if _EMAIL_RE.search(text):
        found.append("an email address")
    if _PHONE_RE.search(text):
        found.append("a phone number")
    if _PAN_RE.search(text):
        found.append("a PAN number")
    return found


def _redact_pii(text: str) -> tuple[str, int]:
    """Replace detected PII with redaction tags, returning (text, count)."""
    count = 0

    def _redact_card(match: "re.Match[str]") -> str:
        nonlocal count
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            count += 1
            return "[REDACTED CARD NUMBER]"
        return match.group()

    text = _CARD_CANDIDATE_RE.sub(_redact_card, text)
    count += len(_SSN_RE.findall(text))
    text = _SSN_RE.sub("[REDACTED SSN]", text)
    count += len(_EMAIL_RE.findall(text))
    text = _EMAIL_RE.sub("[REDACTED EMAIL]", text)
    count += len(_PHONE_RE.findall(text))
    text = _PHONE_RE.sub("[REDACTED PHONE]", text)
    count += len(_PAN_RE.findall(text))
    text = _PAN_RE.sub("[REDACTED PAN]", text)
    return text, count


# =========================
# Supervisor Agent + Input Guardrail
# =========================
def supervisor_agent(state: TravelState):
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)

    # PII guardrail runs first: it's a free regex check, so it blocks before
    # any paid LLM call, and it can't be argued around by prompt phrasing
    # the way the LLM-judged travel-relevance guardrail below can.
    pii_found = _detect_pii(query)
    if pii_found:
        reason = (
            "Your message appears to contain "
            + " and ".join(pii_found)
            + ". Please remove sensitive personal details and resend your request."
        )
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "pii_flagged": True,
            "pii_reason": reason,
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"PII guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    guardrail_prompt = f"""
Determine whether the following request belongs to travel planning or travel
information. Valid requests can include destinations, flights, hotels, weather,
budgets, visas, transportation, sightseeing, food, packing, or itineraries.

Block clearly unrelated requests and requests asking for harmful or illegal
instructions. Do not block a valid travel request merely because some details
are missing.

Return strict JSON only:
{{
  "allowed": true,
  "reason": ""
}}

User request:
{query}
"""

    # Fail open on parser/model errors so a temporary JSON-format issue does not
    # break the travel-planning behavior.
    try:
        guardrail_raw = _llm_text(
            "You are the input guardrail for a travel-planning application. "
            "Return strict JSON only.",
            guardrail_prompt,
        )
        guardrail_result = _json_from_llm(guardrail_raw)
        allowed = bool(guardrail_result.get("allowed", True))
        guardrail_reason = str(guardrail_result.get("reason", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Guardrail fallback used: {exc}")
        allowed = True
        guardrail_reason = "Guardrail validation fallback allowed the request."

    if not allowed:
        reason = guardrail_reason or (
            "TripMate can only help with travel-planning requests. "
            "Please ask about a destination, flight, hotel, weather, budget, "
            "or itinerary."
        )
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    supervisor_prompt = f"""
You are the supervisor of a multi-agent travel-planning system.
Choose the specialist agents needed to ground the itinerary in real,
live data. Each agent's job is to VERIFY and ENRICH whatever the user
already told you with live data, not just answer if the topic was
mentioned. Do not skip an agent merely because the user already stated a
month, date, or budget figure -- that is exactly when the agent is most
useful, since it checks that stated info against real conditions.

Available agents:
- flight_agent: flights, airports, airlines, routes, airfare, or booking advice
- hotel_agent: hotels, accommodation, neighborhoods, or places to stay
- weather_agent: include for almost any request naming a destination and a
  travel window (even an approximate month/season) -- it fetches the real
  forecast/climate so the itinerary and packing advice are grounded in
  actual conditions, not assumptions. Only skip it if the request has no
  identifiable destination or timeframe at all.
- budget_agent: include for almost any full itinerary request, especially
  when the user gives a budget figure or range -- it checks that stated
  budget against real flight/hotel cost estimates instead of taking it at
  face value. Only skip it for a narrow single-fact question with no
  itinerary/planning intent (e.g. "what's the weather in Rome tomorrow").
- itinerary_agent: creates the integrated travel plan and must always be included

Return strict JSON only using this schema:
{{
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}

User request:
{query}
"""

    try:
        supervisor_raw = _llm_text(
            "You route work to travel specialist agents. Return strict JSON only.",
            supervisor_prompt,
        )
        parsed = _json_from_llm(supervisor_raw)
        requested_agents = parsed.get("selected_agents", [])
        selected_agents = [
            name for name in AGENT_ORDER
            if name in requested_agents and name in KNOWN_AGENTS
        ]

        # The itinerary agent integrates whichever specialist results were selected.
        if "itinerary_agent" not in selected_agents:
            selected_agents.append("itinerary_agent")

        constraints = _empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", {})
        if isinstance(parsed_constraints, dict):
            constraints.update(parsed_constraints)

        reasoning = str(parsed.get("reasoning", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Supervisor fallback used: {exc}")
        # Full workflow is the safe fallback if routing parsing fails.
        selected_agents = AGENT_ORDER.copy()
        constraints = _empty_constraints()
        reasoning = (
            "Supervisor parsing failed, so the full travel workflow "
            "was selected as a safe fallback."
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": llm_calls,
    }


# =========================
# Guardrail blocked response
# =========================
def guardrail_blocked_agent(state: TravelState):
    reason = state.get("final_response") or state.get("guardrail_reason") or (
        "This request was blocked by the travel input guardrail."
    )
    return {
        "final_response": reason,
        "messages": [AIMessage(content=reason)],
    }


# =========================
# Flight Agent - AviationStack MCP, LLM-only fallback if unreachable
# =========================
FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

Generate:
1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

If airport/airline data above is empty, rely on general travel knowledge and
clearly note that prices and airlines are estimates, not live data.
Return concise travel guidance.
"""


def flight_agent(state: TravelState):
    query = state["user_query"]
    airports: object = ""
    airlines: object = ""

    try:
        airports = asyncio.run(aviation_mcp_call("list_airports"))
        airlines = asyncio.run(aviation_mcp_call("list_airlines"))
    except Exception as exc:
        print(
            f"FLIGHT AGENT MCP ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    try:
        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=str(airports)[:3000],
            airline_data=str(airlines)[:3000],
        )

        response = llm.invoke(
            [
                SystemMessage(content="You are an expert travel flight planner."),
                HumanMessage(content=prompt),
            ]
        )
        flight_data = response.content
    except Exception as exc:
        flight_data = f"Flight information unavailable: {exc}"

    return {
        "flight_results": flight_data,
        "messages": [AIMessage(content="Flight recommendations generated")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# =========================
# Hotel Agent - Tavily MCP search
# =========================
def hotel_agent(state: TravelState):
    query = (
        f"Best hotels for "
        f"{state['user_query']}"
    )

    try:
        hotel_results = asyncio.run(
            tavily_mcp_search(query)
        )

    except Exception as exc:
        print(
            f"HOTEL AGENT MCP ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        hotel_results = (
            "Live hotel search is temporarily unavailable. "
            "Provide general accommodation and neighborhood "
            "guidance based on the destination and clearly "
            "label it as non-live advice."
        )

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(
                content="Hotel information processed."
            )
        ],
        "llm_calls": (
            state.get("llm_calls", 0) + 1
        ),
    }


_CONDITION_RE = re.compile(r"['\"]condition['\"]\s*:\s*['\"]([^'\"]+)['\"]")
_TEMP_C_RE = re.compile(r"['\"]temperature_c['\"]\s*:\s*([\d.]+)")


def _climate_summary(weather_data: Any) -> str:
    """Short 'condition, temp' string pulled from the MCP weather payload
    (a dict or its string/JSON serialization -- the key names are the same
    either way), for display in the approval card's CLIMATE field."""
    text = str(weather_data)
    condition_match = _CONDITION_RE.search(text)
    temp_match = _TEMP_C_RE.search(text)
    if condition_match and temp_match:
        return f"{condition_match.group(1).title()}, {temp_match.group(1)}°C"
    if condition_match:
        return condition_match.group(1).title()
    if temp_match:
        return f"{temp_match.group(1)}°C"
    return ""


# =========================
# Weather Agent - OpenWeather MCP
# =========================
def weather_agent(state: TravelState):
    city = extract_destination(
        state["user_query"]
    )

    climate = ""
    try:
        weather_data = asyncio.run(
            weather_mcp_search(city)
        )

        forecast_data = asyncio.run(
            forecast_mcp_search(city)
        )

        weather_results = f"""
Current Weather:
{weather_data}

Forecast:
{forecast_data}
"""
        climate = _climate_summary(weather_data)

    except Exception as exc:
        print(
            f"WEATHER AGENT MCP ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        weather_results = (
            f"Live weather information for {city} "
            "is temporarily unavailable. Give general "
            "seasonal guidance and advise the traveler "
            "to verify the forecast before departure."
        )

    update: dict[str, Any] = {
        "weather_results": weather_results,
        "messages": [
            AIMessage(
                content="Weather information processed."
            )
        ],
    }

    if climate:
        constraints = dict(state.get("trip_constraints") or {})
        constraints["climate"] = climate
        update["trip_constraints"] = constraints

    return update


# =========================
# Budget Agent
# =========================
def budget_agent(state: TravelState):
    prompt = f"""
Analyze whether this trip is realistic for the user's budget.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', '')}

Hotel Results:
{state.get('hotel_results', '')}

Weather Results:
{state.get('weather_results', '')}

Return:
1. Estimated cost categories
2. Budget risk areas
3. Money-saving suggestions
4. Overall feasibility

If exact live prices are unavailable, clearly label estimates as approximate.

Finish your response with exactly one line in this format, with nothing
after it, giving a short overall total-trip budget estimate (e.g.
"$1,200 - $1,800"):
ESTIMATED_TOTAL_BUDGET: <estimate>
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are a practical travel budget analyst."),
            HumanMessage(content=prompt),
        ]
    )

    update: dict[str, Any] = {
        "budget_results": response.content,
        "messages": [AIMessage(content="Budget assessment generated.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }

    # Backfill trip_constraints.budget from the agent's own estimate when the
    # user never stated a figure up front -- otherwise the approval card's
    # BUDGET field stays blank even after a real number has been computed.
    constraints = dict(state.get("trip_constraints") or {})
    if not constraints.get("budget"):
        match = re.search(r"ESTIMATED_TOTAL_BUDGET:\s*(.+)", str(response.content))
        if match:
            constraints["budget"] = match.group(1).strip()
            update["trip_constraints"] = constraints

    return update


# =========================
# Itinerary Agent
# =========================
def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', '')}

Hotel Results:
{state.get('hotel_results', '')}

Weather Results:
{state.get('weather_results', '')}

Budget Results:
{state.get('budget_results', '')}

Make the itinerary practical, budget-aware, and easy to follow.
Create a clear draft that is ready for human review.

Include a "Budget Breakdown" section listing the major cost categories
(flights, hotels, food, activities, etc.), and end that section with a line
in exactly this format, with nothing after it, giving the all-in total for
the whole trip:
Total Cost: <amount>
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are an expert travel planner."),
            HumanMessage(content=prompt),
        ]
    )

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create the "
        "final polished plan, or provide feedback for revision."
    )

    update: dict[str, Any] = {
        "itinerary": response.content,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }

    # Mirror the draft's own "Budget Breakdown -> Total Cost" line into the
    # approval card's top-level BUDGET field, so the summary always matches
    # the number the human is actually looking at in the body below it.
    match = re.search(r"Total Cost:\s*(.+)", str(response.content))
    if match:
        constraints = dict(state.get("trip_constraints") or {})
        constraints["budget"] = match.group(1).strip()
        update["trip_constraints"] = constraints

    return update


# =========================
# Human-in-the-Loop approval
# =========================
def human_approval_agent(state: TravelState):
    # Do not wrap interrupt() in try/except. LangGraph uses it to pause execution.
    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )

    approved = bool(review.get("approved", False))
    human_feedback = str(review.get("feedback", "")).strip()

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [AIMessage(content="Human approval step completed.")],
    }


# =========================
# Final Response Agent
# =========================
def final_agent(state: TravelState):
    if state.get("approved", False):
        review_instruction = (
            "The user approved the draft. Preserve its decisions while polishing it."
        )
    else:
        review_instruction = f"""
The user requested a revision. Apply this feedback carefully:
{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}
"""

    # The draft itinerary already synthesizes the flight/hotel/weather/budget
    # results (itinerary_agent's own prompt includes all four), so they are
    # deliberately left out here rather than duplicated -- re-sending them on
    # top of the draft was blowing this request past Groq's per-minute token
    # limit on every approve/revise.
    final_prompt = f"""
Generate the final travel response for the user.

Human Review:
{review_instruction}

User Request:
{state['user_query']}

Supervisor Constraints:
{state.get('trip_constraints', {})}

Draft Itinerary (already incorporates flights, hotels, weather, and budget):
{state.get('itinerary', '')}

Format the final answer beautifully using these sections:
1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Important:
- Be clear and practical.
- Mention that flight prices/airlines are estimates, not live data, in this deployment.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
- Incorporate the human feedback when revision was requested.
"""

    response = llm.invoke(
        [
            SystemMessage(
                content="You are a professional AI travel booking assistant."
            ),
            HumanMessage(content=final_prompt),
        ]
    )

    return {
        "final_response": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# =========================
# Output Guardrail
#
# Runs right after itinerary_agent, before the draft ever reaches the human
# approval gate. Regex-based like the PII input check: it scans the draft
# itinerary for anything that looks like a card number, SSN, email, phone
# number, or PAN number -- guarding against the LLM echoing back sensitive details
# the user pasted earlier in the conversation -- and redacts it before a
# human ever sees or approves it.
# =========================
def output_guardrail_agent(state: TravelState):
    text = state.get("itinerary", "") or ""
    redacted_text, redaction_count = _redact_pii(text)

    return {
        "itinerary": redacted_text,
        "output_flagged": redaction_count > 0,
        "output_redactions": redaction_count,
        "messages": [AIMessage(content="Output safety scan complete.")],
    }


# =========================
# Dynamic Supervisor Routing
# =========================
ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent",
}


def _selected_agents(state: TravelState) -> list[str]:
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent in selected]


def route_from_supervisor(state: TravelState) -> str:
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"

    selected = _selected_agents(state)
    return selected[0] if selected else "itinerary_agent"


def route_after_agent(current_agent: str):
    def route(state: TravelState) -> str:
        selected = _selected_agents(state)
        current_index = AGENT_ORDER.index(current_agent)

        for next_agent in AGENT_ORDER[current_index + 1 :]:
            if next_agent in selected:
                return next_agent

        return "itinerary_agent"

    return route


# =========================
# Build Graph
# =========================
graph = StateGraph(TravelState)

graph.add_node("supervisor", supervisor_agent)
graph.add_node("guardrail_blocked", guardrail_blocked_agent)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("budget_agent", budget_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("human_approval", human_approval_agent)
graph.add_node("final_agent", final_agent)
graph.add_node("output_guardrail", output_guardrail_agent)

graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route_from_supervisor, ROUTE_MAP)

graph.add_conditional_edges(
    "flight_agent", route_after_agent("flight_agent"), ROUTE_MAP
)
graph.add_conditional_edges(
    "hotel_agent", route_after_agent("hotel_agent"), ROUTE_MAP
)
graph.add_conditional_edges(
    "weather_agent", route_after_agent("weather_agent"), ROUTE_MAP
)
graph.add_conditional_edges(
    "budget_agent", route_after_agent("budget_agent"), ROUTE_MAP
)

graph.add_edge("itinerary_agent", "output_guardrail")
graph.add_edge("output_guardrail", "human_approval")
graph.add_edge("human_approval", "final_agent")
graph.add_edge("final_agent", END)
graph.add_edge("guardrail_blocked", END)

# =========================
# PostgreSQL Checkpointer, backed by a connection pool
#
# Streamlit Community Cloud can serve multiple browser sessions against the
# same running process, each in its own thread, sharing this module-level
# singleton. A single psycopg.Connection is not safe for concurrent use, so
# a ConnectionPool is used instead of a bare connection.
# =========================
DATABASE_URL = get_database_url()

_connection_kwargs = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}

_pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=10,
    kwargs=_connection_kwargs,
    open=True,
)

checkpointer = PostgresSaver(_pool)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)


# =========================
# Streamlit-facing helpers
# =========================
def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None

    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value": payload}


def _serialize_result(
    result: dict[str, Any],
    thread_id: str,
) -> dict[str, Any]:
    messages = result.get("messages", [])
    last_message = messages[-1].content if messages else ""
    answer = result.get("final_response") or last_message
    interrupt_payload = _interrupt_payload(result)

    if interrupt_payload:
        answer = interrupt_payload.get("draft_itinerary") or result.get(
            "itinerary", ""
        )

    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "itinerary": (
            interrupt_payload.get("draft_itinerary", "")
            if interrupt_payload
            else result.get("itinerary", "")
        ),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "pii_flagged": result.get("pii_flagged", False),
        "pii_reason": result.get("pii_reason", ""),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback", ""),
        "final_response": result.get("final_response", ""),
        "output_flagged": result.get("output_flagged", False),
        "output_redactions": result.get("output_redactions", 0),
        "llm_calls": result.get("llm_calls", 0),
    }


def run_travel_agent(user_input: str, thread_id: str | None = None):
    """Start a new travel-planning run and pause at human approval."""
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {"configurable": {"thread_id": thread_id}}

    result = travel_graph.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
            "user_query": user_input,
            "guardrail_allowed": True,
            "guardrail_reason": "",
            "pii_flagged": False,
            "pii_reason": "",
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": "",
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "budget_results": "",
            "itinerary": "",
            "approval_request": "",
            "approved": False,
            "human_feedback": "",
            "final_response": "",
            "output_flagged": False,
            "output_redactions": 0,
            "llm_calls": 0,
        },
        config=config,
    )

    return _serialize_result(result, thread_id)


def resume_travel_agent(
    thread_id: str,
    approved: bool,
    feedback: str = "",
):
    """Resume the paused LangGraph thread after human review."""
    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        Command(
            resume={
                "approved": approved,
                "feedback": feedback.strip(),
            }
        ),
        config=config,
    )

    return _serialize_result(result, thread_id)
