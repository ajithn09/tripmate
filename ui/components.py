"""Raw-HTML renderers for the pieces that don't fit Streamlit's native chat
DOM: the header, the boarding-pass draft-itinerary card, and the
mission-control pipeline panel. Rendered via st.markdown(html,
unsafe_allow_html=True) -- never st.components.v1.html, which would
iframe-sandbox the content away from the global stylesheet in ui/styles.py.

IMPORTANT: every line of every returned string must start at column 0 (no
leading whitespace). Streamlit's markdown renderer runs Python-Markdown
first, which treats any line indented 4+ spaces as a preformatted code
block -- that would print these HTML fragments as literal text instead of
rendering them as HTML.
"""

import html
import re
from typing import Any

from ui.pipeline import NODE_DEFS, node_detail


def _esc(value: Any) -> str:
    return html.escape(str(value)) if value is not None else ""


# Section titles the final-response prompt in backend.py asks the LLM to
# use (see the "Format the final answer beautifully" instructions). Matched
# loosely -- with/without a leading "#"/"**"/number -- and rewritten into a
# real markdown H2 with a leading icon, so the existing h2 styling in
# ui/styles.py turns each one into an icon+title section header.
SECTION_ICONS = {
    "trip summary": ("📄", "Trip Summary"),
    "flight information": ("✈️", "Flight Information"),
    "hotel suggestions": ("🏨", "Hotel Suggestions"),
    "weather information": ("⛅", "Weather Information"),
    "day-by-day itinerary": ("🗺️", "Day-by-Day Itinerary"),
    "estimated budget": ("💰", "Estimated Budget"),
    "final recommendations": ("✅", "Final Recommendations"),
}
_LEADING_DECORATION_RE = re.compile(r"^(?:\*\*|\d+[.\)]|[ \t])+")
_TRAILING_DECORATION_RE = re.compile(r"(?:\*\*|:|[ \t])+$")


def _normalize_heading_core(raw_line: str) -> str:
    """Strip a heading line down to its bare title text, tolerating any
    order/combination of markdown decoration around it -- "#" prefixes,
    numbering ("1.", "2)"), bold markers, and a trailing colon -- since the
    LLM writes these in whichever order it likes (both "**1. Trip
    Summary**" and "1. **Trip Summary**" show up in practice, and only
    matching one of those orders meant the other silently fell through
    unstyled with no section icon).
    """
    line = raw_line.strip().lstrip("#").strip()
    line = _LEADING_DECORATION_RE.sub("", line)
    line = _TRAILING_DECORATION_RE.sub("", line)
    return line.strip()


def style_response_sections(text: str) -> str:
    def _replace_line(line: str) -> str:
        entry = SECTION_ICONS.get(_normalize_heading_core(line).lower())
        if entry is None:
            return line
        icon, title = entry
        return f"## {icon} {title}"

    text = "\n".join(_replace_line(ln) for ln in text.split("\n"))
    return _style_subsections(text)


# Sub-headings the LLM sometimes writes inside a section (most often inside
# "Estimated Budget") as their own bold/standalone line -- e.g.
# "**Money-Saving Tips (Built into the itinerary)**". Matched the same
# loose way as SECTION_ICONS and rewritten into a real markdown H3 with a
# leading icon, so they read as sub-section headers instead of bold text
# lost inside a paragraph.
SUBSECTION_ICONS = {
    "quick look overview": ("🔎", "Quick-Look Overview"),
    "money saving tips": ("💡", "Money-Saving Tips"),
    "budget breakdown": ("🧾", "Budget Breakdown"),
}
_TRAILING_PAREN_RE = re.compile(r"[ \t]*\(([^)]*)\)[ \t]*$")
_BUDGET_BREAKDOWN_RE = re.compile(
    r"(?<=^### 🧾 Budget Breakdown\n)(.*?)(?=\n#{2,3}[ \t]|\Z)",
    re.MULTILINE | re.DOTALL,
)
_BUDGET_ITEM_RE = re.compile(r"^[ \t]*[-*][ \t]+\**([^:*\n]+?)\**[ \t]*[:–—-][ \t]*(.+?)[ \t]*$")
_BUDGET_TOTAL_RE = re.compile(
    r"^[ \t]*[-*]?[ \t]*\**Total(?:[ \t]+Cost)?\**[ \t]*[:–—-][ \t]*(.+?)[ \t]*$",
    re.IGNORECASE,
)


def _normalize_subsection(raw: str) -> str:
    return re.sub(r"[-\s]+", " ", raw.strip().lower()).strip()


def _style_subsections(text: str) -> str:
    def _replace_line(line: str) -> str:
        stripped = re.sub(r"^[ \t]{0,3}[-*][ \t]+", "", line)
        core = _normalize_heading_core(stripped)
        # The optional "(...)" suffix can land either side of the closing
        # "**" -- e.g. "**Money-Saving Tips (Built into the itinerary)**"
        # or "**Money-Saving Tips**(Built into the itinerary)".
        suffix = ""
        paren_match = _TRAILING_PAREN_RE.search(core)
        if paren_match:
            suffix = f"({paren_match.group(1).strip()})"
            core = _normalize_heading_core(core[: paren_match.start()])
        entry = SUBSECTION_ICONS.get(_normalize_subsection(core))
        if entry is None:
            return line
        icon, canonical = entry
        title = f"{canonical} {suffix}" if suffix else canonical
        return f"### {icon} {title}"

    text = "\n".join(_replace_line(ln) for ln in text.split("\n"))
    return _BUDGET_BREAKDOWN_RE.sub(
        lambda m: "\n" + _style_budget_breakdown(m.group(1).strip()) + "\n", text
    )


def _style_budget_breakdown(body: str) -> str:
    """Turn a "- Category: $amount" bullet list under the Budget Breakdown
    sub-heading into a real markdown table, so the cost categories read as
    a clean grid instead of a plain list buried in a paragraph.
    """
    rows: list[tuple[str, str]] = []
    total: str | None = None
    leftover: list[str] = []

    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        total_match = _BUDGET_TOTAL_RE.match(stripped)
        if total_match:
            total = total_match.group(1).strip()
            continue
        item_match = _BUDGET_ITEM_RE.match(stripped)
        if item_match:
            rows.append((item_match.group(1).strip(), item_match.group(2).strip()))
        else:
            leftover.append(line)

    if not rows:
        return body

    table = ["| Category | Estimated Cost |", "|---|---|"]
    table.extend(f"| {label} | {amount} |" for label, amount in rows)
    if total:
        table.append(f"| **Total Cost** | **{total}** |")

    result = "\n".join(table)
    remainder = "\n".join(leftover).strip()
    if remainder:
        result += "\n\n" + remainder
    return result


def escape_markdown_math(text: str) -> str:
    """Streamlit's markdown renderer treats a bare "$...$" as inline LaTeX
    math. A long formatted answer has many dollar amounts scattered across
    it (Trip Summary, a hotel/flight table, Budget Breakdown, ...), so it's
    easy for an odd "$" count somewhere to pair two unrelated dollar signs
    together -- everything between them then renders in KaTeX's mismatched
    serif font instead of plain text (e.g. "an extra $15-20 per night"
    turning "15-20" into a stray equation). Escaping every literal "$"
    keeps it displayed as-is while turning math parsing off everywhere.
    """
    return text.replace("$", "\\$")


_H2_RE = re.compile(r"^##[ \t]+\S+[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def extract_section(text: str, title: str) -> str | None:
    """Pull the body of one "## icon Title" section (as produced by
    style_response_sections) out of a formatted assistant answer -- used to
    grab just the Trip Summary text for the PDF download button. Returns
    None if that section isn't present in the message.
    """
    normalized = style_response_sections(text)
    matches = list(_H2_RE.finditer(normalized))
    for i, match in enumerate(matches):
        if match.group(1).strip().lower() == title.lower():
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
            body = normalized[start:end].strip()
            return body or None
    return None


def render_message_time(time_str: str) -> str:
    return f'<div class="tm-msg-time">{_esc(time_str)}</div>'


def render_header() -> str:
    return (
        '<div class="tm-header">'
        '<div class="tm-brand">'
        '<div class="tm-brand-mark">'
        '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" style="transform:rotate(45deg)">'
        '<path d="M2 12L21 4L14 12L21 20L2 12Z" stroke="#ffb020" stroke-width="1.6" stroke-linejoin="round"/>'
        '</svg>'
        '</div>'
        '<div>'
        '<div class="tm-brand-name">TripMate</div>'
        '<div class="tm-brand-tag">SUPERVISOR &middot; GUARDRAILS &middot; MCP &middot; HUMAN-IN-THE-LOOP</div>'
        '</div>'
        '</div>'
        '<div class="tm-live-pill"><span class="tm-live-dot"></span>AGENTS ONLINE</div>'
        '</div>'
    )


def render_sidebar_brand() -> str:
    return (
        '<div class="tm-sidebar-brand">'
        '<div class="tm-sidebar-mark">'
        '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" style="transform:rotate(45deg)">'
        '<path d="M2 12L21 4L14 12L21 20L2 12Z" stroke="#ffb020" stroke-width="1.6" stroke-linejoin="round"/>'
        '</svg>'
        '</div>'
        '<div class="tm-sidebar-name">TripMate</div>'
        '</div>'
        '<div class="tm-badge">SUPERVISED MULTI-AGENT SYSTEM</div>'
        '<div class="tm-sidebar-desc">Multi-agent travel planner &mdash; LangGraph + MCP</div>'
    )


def render_thread_box(thread_id: str) -> str:
    return (
        '<div class="tm-thread-label">THREAD</div>'
        f'<div class="tm-thread-box">{_esc(thread_id)}</div>'
    )


def render_sidebar_callout(text: str) -> str:
    return (
        '<div class="tm-callout">'
        '<span class="tm-callout-icon">&#9968;</span>'
        f'<span>{_esc(text)}</span>'
        '</div>'
    )


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_BULLET_RE = re.compile(r"^[-*]\s+")
_DAY_HEADING_RE = re.compile(r"^day\s*\d+\b", re.IGNORECASE)
_NUM_HEADING_RE = re.compile(r"^\d+[.\)]\s+(.+)$")
_HR_RE = re.compile(r"^-{3,}$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_PLACEHOLDER_CELL_RE = re.compile(r"^[-–—]*$")


_ESCAPED_PUNCT_RE = re.compile(r"\\([*_])")


def _inline_format(line: str) -> str:
    text = _BOLD_RE.sub(r"<b>\1</b>", _esc(line))
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    # A markdown-escaped "\*" (a literal asterisk the LLM didn't mean as an
    # italic marker, e.g. a footnote line) survives both regexes above --
    # unescape it now that no further markdown parsing will run on it.
    return _ESCAPED_PUNCT_RE.sub(r"\1", text)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_TABLE_SEP_CELL_RE.match(cell) for cell in cells if cell)


def _labeled_cells(header: list[str], cells: list[str]) -> list[str]:
    """Every non-first cell in a row, paired with its column header and
    rendered as its own "Header: value" point -- placeholder cells (a bare
    "-"/"--", or empty) are dropped rather than shown as an empty point.
    """
    points = []
    for col_name, value in zip(header[1:], cells[1:]):
        if value and not _PLACEHOLDER_CELL_RE.match(value):
            col_name = col_name.strip()
            points.append(f"{col_name}: {value}" if col_name else value)
    return points


def _format_itinerary_body(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return '<p class="bp-empty">No draft details yet.</p>'

    parts: list[str] = []
    para_buf: list[str] = []
    bullet_buf: list[str] = []
    table_buf: list[list[str]] = []

    def flush_para() -> None:
        if para_buf:
            parts.append(f'<p>{" ".join(_inline_format(ln) for ln in para_buf)}</p>')
            para_buf.clear()

    def flush_bullets() -> None:
        if bullet_buf:
            items = "".join(f"<li>{_inline_format(_BULLET_RE.sub('', ln))}</li>" for ln in bullet_buf)
            parts.append(f"<ul>{items}</ul>")
            bullet_buf.clear()

    def flush_table() -> None:
        # A markdown table (e.g. the LLM's "Item | Details" quick-look
        # overview, or a "Day | Highlights | Cost" day-by-day grid) doesn't
        # read as prose, so it's turned into the same heading+bullet-point
        # look as everything else here rather than dumped into a squished
        # paragraph of literal "|" characters.
        if not table_buf:
            return
        rows = table_buf
        if len(rows) >= 2 and _is_table_separator(rows[1]):
            rows = [rows[0]] + rows[2:]
        header, data_rows = rows[0], rows[1:]

        if len(header) <= 2:
            # Simple "Item | Details" table -- one bullet per row. A row
            # label that's just a bare index number (e.g. a "Day" column
            # with no other header to give it meaning) carries nothing on
            # its own, so it's dropped rather than shown as a floating digit.
            items = []
            for cells in data_rows:
                if not any(cells):
                    continue
                label = cells[0].strip()
                detail = cells[1].strip() if len(cells) > 1 else ""
                if _PLACEHOLDER_CELL_RE.match(detail):
                    detail = ""
                if label.isdigit():
                    if not detail:
                        continue
                    items.append(f"<li>{_inline_format(detail)}</li>")
                else:
                    body = f"<b>{_inline_format(label)}</b>" + (f" &ndash; {_inline_format(detail)}" if detail else "")
                    items.append(f"<li>{body}</li>")
            if items:
                parts.append(f"<ul>{''.join(items)}</ul>")
        else:
            # Three-or-more-column table (e.g. Day / Highlights / Cost) --
            # each row becomes its own heading with one bullet per column,
            # instead of one line with every column mashed together.
            for cells in data_rows:
                if not any(cells):
                    continue
                label = cells[0].strip()
                heading = f"Day {label}" if label.isdigit() else label
                points = _labeled_cells(header, cells)
                parts.append(f'<div class="bp-day">{_inline_format(heading)}</div>')
                if points:
                    parts.append("<ul>" + "".join(f"<li>{_inline_format(p)}</li>" for p in points) + "</ul>")
        table_buf.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_para()
            flush_bullets()
            flush_table()
            continue
        if _HR_RE.match(line):
            flush_para()
            flush_bullets()
            flush_table()
            continue
        table_match = _TABLE_ROW_RE.match(line)
        if table_match:
            flush_para()
            flush_bullets()
            table_buf.append(_split_table_row(line))
            continue
        flush_table()
        if _BULLET_RE.match(line):
            flush_para()
            bullet_buf.append(line)
            continue
        heading = line.lstrip("#").strip().strip("*").strip()
        num_match = _NUM_HEADING_RE.match(heading) if heading else None
        if num_match:
            heading = num_match.group(1).strip().strip("*").strip()
        is_heading = (
            line.startswith("#")
            or (len(heading) < 60 and _DAY_HEADING_RE.match(heading))
            or (line.startswith("**") and line.endswith("**") and len(heading) < 60)
            or (num_match is not None and len(heading) < 60)
        )
        if is_heading:
            flush_para()
            flush_bullets()
            parts.append(f'<div class="bp-day">{_inline_format(heading)}</div>')
            continue
        flush_bullets()
        para_buf.append(line)

    flush_para()
    flush_bullets()
    flush_table()
    return "".join(parts) or '<p class="bp-empty">No draft details yet.</p>'


def render_boarding_pass_card(draft: dict[str, Any]) -> str:
    constraints = draft.get("trip_constraints") or {}
    destination = constraints.get("destination") or "Your trip"
    duration = constraints.get("duration") or "—"
    budget = constraints.get("budget") or "Not specified"
    climate = constraints.get("climate") or "Not specified"
    itinerary_text = draft.get("itinerary") or draft.get("answer") or ""

    return (
        '<div class="boarding-pass">'
        '<div class="bp-top">'
        '<div class="bp-route">'
        f'<div class="bp-city">{_esc(destination)}<small>DRAFT ITINERARY</small></div>'
        '</div>'
        '<div class="bp-status">AWAITING APPROVAL</div>'
        '</div>'
        '<div class="bp-divider"></div>'
        '<div class="bp-meta">'
        f'<div><span class="label">DURATION</span><span class="value">{_esc(duration)}</span></div>'
        f'<div><span class="label">BUDGET</span><span class="value">{_esc(budget)}</span></div>'
        f'<div><span class="label">CLIMATE</span><span class="value">{_esc(climate)}</span></div>'
        '</div>'
        f'<div class="bp-body">{_format_itinerary_body(itinerary_text)}</div>'
        '</div>'
    )


def render_mission_control(
    pipeline_status: dict[str, str],
    result: dict[str, Any] | None,
    timestamp: str | None = None,
) -> str:
    has_run = result is not None
    result = result or {}

    status_labels = {
        "done": "DONE",
        "waiting": "WAITING",
        "blocked": "BLOCKED",
        "skipped": "SKIPPED",
        "pending": "PENDING",
    }
    # Nodes still pending/skipped haven't actually resolved, so they don't
    # get a timestamp -- only ones the backend has reported on.
    timed_statuses = {"done", "waiting", "blocked"}

    nodes_html = []
    for key, label, _field, _agent_name in NODE_DEFS:
        status = pipeline_status.get(key, "pending")
        detail = node_detail(key, result)
        status_label = status_labels.get(status, status.upper())
        node_time = _esc(timestamp) if timestamp and status in timed_statuses else ""

        nodes_html.append(
            f'<div class="node status-{status}">'
            '<div class="node-dot"></div>'
            '<div class="node-body">'
            '<div class="node-name">'
            f'<span class="node-label">{_esc(label)}</span>'
            '<span class="node-meta">'
            + (f'<span class="node-time">{node_time}</span>' if node_time else "")
            + f'<span class="node-status">{status_label}</span>'
            '<span class="node-chevron">&#9662;</span>'
            '</span>'
            '</div>'
            f'<div class="node-detail">{_esc(detail)}</div>'
            '</div>'
            '</div>'
        )

    def _check_row(label: str, value_html: str) -> str:
        return f'<div class="check-row"><span>{label}</span>{value_html}</div>'

    pending_badge = '<span class="node-status">PENDING</span>'
    skipped_badge = '<span class="node-status">SKIPPED</span>'
    clear_badge = '<span class="check-ok">clear</span>'

    pii_flagged = result.get("pii_flagged", False)
    guardrail_allowed = result.get("guardrail_allowed", True)
    output_flagged = result.get("output_flagged", False)
    output_redactions = result.get("output_redactions", 0) or 0
    has_itinerary = bool(result.get("itinerary"))

    if not has_run:
        pii_badge, relevance_badge, output_badge = pending_badge, pending_badge, pending_badge
    elif pii_flagged:
        # PII check runs first and short-circuits the rest of supervisor_agent,
        # so neither the relevance check nor output_guardrail ever executed.
        reason = _esc(result.get("pii_reason") or "Blocked")
        pii_badge = f'<span class="check-blocked">{reason}</span>'
        relevance_badge = skipped_badge
        output_badge = skipped_badge
    elif not guardrail_allowed:
        reason = _esc(result.get("guardrail_reason") or "Blocked")
        pii_badge = clear_badge
        relevance_badge = f'<span class="check-blocked">{reason}</span>'
        output_badge = skipped_badge
    else:
        pii_badge = clear_badge
        relevance_badge = clear_badge
        if not has_itinerary:
            output_badge = pending_badge
        elif output_flagged:
            plural = "s" if output_redactions != 1 else ""
            output_badge = f'<span class="check-blocked">redacted {output_redactions} item{plural}</span>'
        else:
            output_badge = clear_badge

    guardrail_row = (
        _check_row("PII scan", pii_badge)
        + _check_row("Travel-relevance &amp; policy scan", relevance_badge)
        + _check_row("Output safety scan", output_badge)
    )

    return (
        '<div class="mission-control">'
        '<div class="mc-head">'
        '<div>'
        '<div class="mc-title"><span class="mc-blip"></span>Mission Control</div>'
        '<div class="mc-sub">live agent orchestration trace</div>'
        '</div>'
        '</div>'
        f'<div class="pipeline">{"".join(nodes_html)}</div>'
        '<div class="mc-divider"></div>'
        '<div class="guardrail-box">'
        '<h4>GUARDRAIL CHECKS</h4>'
        f'{guardrail_row}'
        '</div>'
        '<div class="mcp-box">'
        '<h4>CONNECTED MCP SERVERS</h4>'
        '<div class="mcp-row"><span class="tag">&#9679;</span> tavily-search '
        '<span style="margin-left:auto;color:var(--text-faint);font-family:\'IBM Plex Mono\',monospace;font-size:10.5px;">http</span></div>'
        '<div class="mcp-row"><span class="tag">&#9679;</span> aviationstack-mcp '
        '<span style="margin-left:auto;color:var(--text-faint);font-family:\'IBM Plex Mono\',monospace;font-size:10.5px;">stdio</span></div>'
        '<div class="mcp-row"><span class="tag">&#9679;</span> weather-server '
        '<span style="margin-left:auto;color:var(--text-faint);font-family:\'IBM Plex Mono\',monospace;font-size:10.5px;">stdio</span></div>'
        '</div>'
        '</div>'
    )
