"""Session state machine for the TripMate Streamlit app.

Streamlit reruns the whole script on every widget interaction, so anything
that must survive across reruns lives in ``st.session_state``. The flow is
modeled as an explicit ``turn_phase`` state machine rather than ad-hoc flags:

    idle / complete --(chat_input submit)--> awaiting_approval --(approve or
    request-changes)--> complete

Because the Approve / Request-changes widgets are only rendered while
``turn_phase == "awaiting_approval"``, and the click handlers flip the phase
to ``"complete"`` before the rerun, there is no code path that can resume an
already-consumed LangGraph interrupt twice.
"""

import uuid
from datetime import datetime

import streamlit as st

PHASE_IDLE = "idle"
PHASE_AWAITING_APPROVAL = "awaiting_approval"
PHASE_COMPLETE = "complete"


def init_session_state() -> None:
    defaults = {
        "thread_id": None,
        "turn_phase": PHASE_IDLE,
        "messages": [],
        "pending_draft": None,
        "pipeline_status": {},
        "pipeline_timestamp": None,
        "last_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def start_new_trip() -> None:
    st.session_state["thread_id"] = None
    st.session_state["turn_phase"] = PHASE_IDLE
    st.session_state["messages"] = []
    st.session_state["pending_draft"] = None
    st.session_state["pipeline_status"] = {}
    st.session_state["pipeline_timestamp"] = None
    st.session_state["last_result"] = None


def ensure_thread_id() -> str:
    if st.session_state["thread_id"] is None:
        st.session_state["thread_id"] = f"user_{uuid.uuid4().hex}"
    return st.session_state["thread_id"]


def begin_new_turn_if_needed() -> str:
    """Return the thread_id to use for a new user message.

    A LangGraph interrupt can only be resumed once, so a thread that has
    already reached END (turn_phase == complete) cannot accept another
    message -- start a fresh thread instead of reusing the finished one.
    """
    if st.session_state["turn_phase"] == PHASE_COMPLETE:
        st.session_state["thread_id"] = None
        st.session_state["turn_phase"] = PHASE_IDLE
    return ensure_thread_id()


def add_message(role: str, content: str) -> None:
    st.session_state["messages"].append(
        {"role": role, "content": content, "time": datetime.now().strftime("%I:%M %p")}
    )


def apply_result(result: dict, pipeline_status: dict) -> None:
    """Update session state from a run_travel_agent/resume_travel_agent result."""
    st.session_state["last_result"] = result
    st.session_state["pipeline_status"] = pipeline_status
    st.session_state["pipeline_timestamp"] = datetime.now().strftime("%I:%M:%S %p")

    if result.get("requires_approval"):
        st.session_state["turn_phase"] = PHASE_AWAITING_APPROVAL
        st.session_state["pending_draft"] = result
        add_message("assistant", result.get("approval_request") or result.get("answer", ""))
    else:
        st.session_state["turn_phase"] = PHASE_COMPLETE
        st.session_state["pending_draft"] = None
        final_text = result.get("final_response") or result.get("answer", "")
        add_message("assistant", final_text)


def is_awaiting_approval() -> bool:
    return st.session_state["turn_phase"] == PHASE_AWAITING_APPROVAL
