import base64
import os

import streamlit as st

st.set_page_config(page_title="TripMate", page_icon="✈️", layout="wide")


def _bootstrap_env_from_secrets() -> None:
    """Bridge Streamlit secrets into os.environ before backend.py is
    imported, so backend.py/mcp_client.py can keep using plain
    os.getenv(...) unmodified (they were written for a FastAPI + .env
    deployment). Local dev can use either a .env file or
    .streamlit/secrets.toml; Streamlit Community Cloud only has secrets.
    """
    required = [
        "GROQ_API_KEY",
        "TAVILY_API_KEY",
        "OPENWEATHER_API_KEY",
        "AVIATION_STACK_API_KEY",
        "DATABASE_URL",
        # Optional -- LangSmith tracing only turns on if LANGCHAIN_API_KEY
        # is actually set (see backend.py); omitting all three is fine.
        "LANGCHAIN_API_KEY",
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_PROJECT",
    ]
    try:
        secrets = st.secrets
    except Exception:
        secrets = {}

    for key in required:
        if not os.environ.get(key):
            value = secrets.get(key) if hasattr(secrets, "get") else None
            if value:
                os.environ[key] = value


_bootstrap_env_from_secrets()

import nest_asyncio

nest_asyncio.apply()

from ui.components import (
    escape_markdown_math,
    extract_section,
    render_boarding_pass_card,
    render_header,
    render_message_time,
    render_mission_control,
    render_sidebar_brand,
    render_sidebar_callout,
    render_thread_box,
    style_response_sections,
)
from ui.pdf_export import build_full_itinerary_pdf
from ui.pipeline import derive_pipeline_status
from ui.state import (
    add_message,
    begin_new_turn_if_needed,
    init_session_state,
    is_awaiting_approval,
    start_new_trip,
    apply_result,
)
from ui.styles import inject_css

try:
    from backend import resume_travel_agent, run_travel_agent

    BACKEND_ERROR = None
except Exception as exc:  # missing/invalid API keys, unreachable Postgres, etc.
    run_travel_agent = None
    resume_travel_agent = None
    BACKEND_ERROR = str(exc)

inject_css()
init_session_state()
st.markdown(render_header(), unsafe_allow_html=True)

if BACKEND_ERROR:
    st.error(
        "TripMate could not start because required configuration is missing "
        "or unreachable.\n\n"
        f"**Details:** {BACKEND_ERROR}\n\n"
        "Add `GROQ_API_KEY`, `TAVILY_API_KEY`, `OPENWEATHER_API_KEY`, "
        "`AVIATION_STACK_API_KEY`, and `DATABASE_URL` to "
        "`.streamlit/secrets.toml` locally, or to your Streamlit Community "
        "Cloud app's Settings → Secrets."
    )
    st.stop()


def _call_backend(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:  # includes psycopg.OperationalError on a dropped idle connection
        return None, exc


with st.sidebar:
    st.markdown(render_sidebar_brand(), unsafe_allow_html=True)
    if st.session_state["thread_id"]:
        st.markdown(render_thread_box(st.session_state["thread_id"]), unsafe_allow_html=True)
    if st.button("+ Start new trip", use_container_width=True, type="primary"):
        start_new_trip()
        st.rerun()
    st.markdown(
        render_sidebar_callout(
            "Every draft is routed through guardrails and needs your approval "
            "before anything is finalized."
        ),
        unsafe_allow_html=True,
    )

SAMPLE_PROMPTS = {
    "✅ Valid": [
        "Plan a 5-day trip to Australia with a $2000 budget",
        "Suggest a 3-day itinerary for Tokyo in spring",
    ],
    "🚫 Off-topic (blocked)": [
        "Write a Python script to reverse a linked list",
        "Explain how photosynthesis works",
    ],
    "🔒 Contains PII (blocked)": [
        "Book my flight to Paris, my card number is 4111 1111 1111 1111",
        "Plan my trip and email me at sample@example.com with details",
    ],
}

col_chat, col_mission = st.columns([1.55, 1], gap="medium")

st.session_state.setdefault("samples_reset_counter", 0)

with col_chat:
    # st.expander's `expanded` arg only sets its *initial* state -- Streamlit
    # ignores it on later reruns, so a plain flag can't force it closed once
    # opened. Appending zero-width spaces (invisible) to the label changes
    # the expander's identity only when we bump the counter, forcing a fresh
    # (collapsed) mount on demand while leaving it alone on every other rerun.
    samples_label = "🧪 Try it out — sample query" + "​" * st.session_state["samples_reset_counter"]
    with st.expander(samples_label, expanded=False):
        st.caption("Click a prompt to see how TripMate's guardrails handle it.")
        for group_label, prompts in SAMPLE_PROMPTS.items():
            st.markdown(f"**{group_label}**")
            for i, sample_text in enumerate(prompts):
                if st.button(
                    sample_text,
                    key=f"sample_{group_label}_{i}",
                    use_container_width=True,
                    disabled=is_awaiting_approval(),
                ):
                    st.session_state["sample_prompt"] = sample_text
                    st.session_state["samples_reset_counter"] += 1
                    st.rerun()

    for msg_idx, msg in enumerate(st.session_state["messages"]):
        avatar = "🧑" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):
            content = msg["content"]
            is_final_plan = False
            if msg["role"] == "assistant":
                is_final_plan = extract_section(content, "Trip Summary") is not None
                content = style_response_sections(content)

            if is_final_plan:
                last_result = st.session_state.get("last_result") or {}
                destination = (last_result.get("trip_constraints") or {}).get("destination", "")
                pdf_bytes = build_full_itinerary_pdf(destination, content)
                pdf_b64 = base64.b64encode(pdf_bytes).decode()
                download_icon = (
                    '<a class="tm-pdf-link" '
                    f'href="data:application/pdf;base64,{pdf_b64}" '
                    'download="tripmate_travel_plan.pdf" title="Download PDF">📥</a>'
                )
                # style_response_sections() always renders this heading as
                # exactly "## 📄 Trip Summary" (SECTION_ICONS is a fixed
                # icon+title pair), so the icon can be appended to that same
                # line -- the h2's flex layout (ui/styles.py) then pushes it
                # to the end of the heading row.
                content = content.replace(
                    "## 📄 Trip Summary", f"## 📄 Trip Summary {download_icon}", 1
                )

            st.markdown(escape_markdown_math(content), unsafe_allow_html=is_final_plan)
            st.markdown(render_message_time(msg.get("time", "")), unsafe_allow_html=True)

    if is_awaiting_approval() and st.session_state["pending_draft"]:
        draft = st.session_state["pending_draft"]
        st.markdown(render_boarding_pass_card(draft), unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown(
                '<div class="bp-actions-title">Review the draft above, then choose an action</div>',
                unsafe_allow_html=True,
            )

            feedback = st.text_area(
                "Request changes",
                placeholder="e.g. swap the museum day for a beach day…",
                label_visibility="collapsed",
                height=80,
                key="revision_feedback",
            )

            col_approve, col_revise = st.columns(2, gap="medium")

            with col_approve:
                if st.button("✓ Approve plan", type="primary", use_container_width=True):
                    with st.spinner("Finalizing your itinerary..."):
                        result, error = _call_backend(
                            resume_travel_agent,
                            st.session_state["thread_id"],
                            True,
                            "",
                        )
                    if error:
                        st.error(f"Could not finalize the plan: {error}")
                    else:
                        apply_result(result, derive_pipeline_status(result))
                        st.rerun()

            with col_revise:
                if st.button("Request changes", use_container_width=True):
                    if not feedback.strip():
                        st.warning("Add a note about what you'd like changed.")
                    else:
                        add_message("user", feedback.strip())
                        with st.spinner("Reworking your itinerary..."):
                            result, error = _call_backend(
                                resume_travel_agent,
                                st.session_state["thread_id"],
                                False,
                                feedback.strip(),
                            )
                        if error:
                            st.error(f"Could not apply your feedback: {error}")
                        else:
                            st.session_state["revision_feedback"] = ""
                            apply_result(result, derive_pipeline_status(result))
                            st.rerun()

    # Declared inside col_chat (the middle/chat section) rather than at
    # root level, so it renders as part of that column instead of a
    # page-wide fixed bottom bar.
    prompt = st.chat_input(
        "Ask TripMate to plan a trip…",
        disabled=is_awaiting_approval(),
    )
    sample_prompt = st.session_state.pop("sample_prompt", None)
    if sample_prompt and not prompt:
        prompt = sample_prompt
    if prompt:
        add_message("user", prompt)
        thread_id = begin_new_turn_if_needed()

        with st.status("Running multi-agent trip planning…", expanded=True) as status:
            result, error = _call_backend(run_travel_agent, prompt, thread_id)
            if error:
                status.update(label="Something went wrong", state="error")
            else:
                pipeline_status = derive_pipeline_status(result)
                st.session_state["pipeline_status"] = pipeline_status
                status.update(label="Pipeline complete", state="complete")
            if error:
                st.error(f"TripMate hit an error: {error}")
            else:
                apply_result(result, pipeline_status)
                st.rerun()

with col_mission:
    st.markdown(
        render_mission_control(
            st.session_state["pipeline_status"],
            st.session_state["last_result"],
            st.session_state["pipeline_timestamp"],
        ),
        unsafe_allow_html=True,
    )