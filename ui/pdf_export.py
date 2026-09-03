"""Full itinerary -> PDF export.

Builds a "Download PDF" of the whole formatted assistant answer (Trip
Summary, Flight Information, Hotel Suggestions, ... through Final
Recommendations, as produced by ui/components.py:style_response_sections),
for the download link rendered next to the "Trip Summary" heading in
streamlit_app.py. Mirrors headings ("## icon Title" / "### icon Title"),
bullet lists, and "| col | col |" markdown tables (e.g. the Budget
Breakdown table and any quick-look-overview table) into a styled PDF via
fpdf -- tables are rendered as labeled bullet points rather than a rigid
grid, since table cells here are often long prose that wouldn't fit
fixed-width columns. Each of the seven fixed section headings (see
ui/components.py:SECTION_ICONS) gets its own accent color pulled from the
app's own dark-theme palette (ui/styles.py), so the PDF reads as the same
product rather than a generic export.
"""

import re
from datetime import date

from fpdf import FPDF

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_BULLET_RE = re.compile(r"^[-*]\s+")
_HR_RE = re.compile(r"^-{3,}$")
_H2_RE = re.compile(r"^##\s+(.+)$")
_H3_RE = re.compile(r"^###\s+(.+)$")
_NUM_LIST_RE = re.compile(r"^\d+[.\)]\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s?(.+)$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_PLACEHOLDER_CELL_RE = re.compile(r"^[-–—]*$")
_ESCAPED_PUNCT_RE = re.compile(r"\\([*_])")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")

# Core PDF fonts (Helvetica) only cover latin-1 -- common "smart" punctuation,
# currency, and arrow/check glyphs are swapped for a plain-ascii look-alike
# first so meaning survives, and anything left outside latin-1 (emoji,
# section icons, flags, ...) is then dropped silently rather than showing up
# as a "?" or tofu box per character.
_UNICODE_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "―": "-", "‐": "-",
    "…": "...", "•": "-", "‣": "-", "◦": "-", "▪": "-",
    " ": " ", "​": "", "﻿": "",
    "→": "->", "←": "<-", "↔": "<->", "⇒": "=>",
    "★": "*", "☆": "*", "⭐": "*",
    "€": "EUR", "£": "GBP",
}

_TITLE_COLOR = (15, 21, 35)
_H2_DEFAULT_COLOR = (13, 94, 89)
_H3_COLOR = (79, 70, 170)
_BODY_COLOR = (33, 37, 41)
_MUTED_COLOR = (110, 116, 133)
_RULE_COLOR = (224, 228, 232)
_BULLET_DEFAULT_COLOR = (63, 150, 140)

# Mirrors the accent each section carries in the live app (ui/styles.py's
# --cyan/--amber/--green palette, darkened for legibility on white paper) so
# the PDF reads as the same product instead of a generic mono-color export.
_SECTION_ACCENTS = {
    "Trip Summary": (12, 110, 100),
    "Flight Information": (28, 95, 158),
    "Hotel Suggestions": (191, 120, 10),
    "Weather Information": (13, 120, 110),
    "Day-by-Day Itinerary": (79, 70, 170),
    "Estimated Budget": (196, 111, 15),
    "Final Recommendations": (30, 140, 90),
}


def _to_ascii(text: str) -> str:
    for src, dst in _UNICODE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = "".join(ch for ch in text if ord(ch) <= 0xFF)
    return _MULTISPACE_RE.sub(" ", text).strip()


def _strip_markdown(text: str) -> str:
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    return _ESCAPED_PUNCT_RE.sub(r"\1", text)


def _clean_line(line: str) -> str:
    return _to_ascii(_strip_markdown(line))


def _clean_heading(line: str) -> str:
    return _to_ascii(_strip_markdown(line).strip("* ").strip())


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_TABLE_SEP_CELL_RE.match(cell) for cell in cells if cell)


def _labeled_cells(header: list[str], cells: list[str]) -> list[str]:
    points = []
    for col_name, value in zip(header[1:], cells[1:]):
        if value and not _PLACEHOLDER_CELL_RE.match(value):
            col_name = col_name.strip()
            points.append(f"{col_name}: {value}" if col_name else value)
    return points


class _TripMatePDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_draw_color(*_RULE_COLOR)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_MUTED_COLOR)
        self.set_xy(self.l_margin, -12)
        self.cell(90, 8, "TripMate  -  AI Travel Plan")
        self.set_xy(self.w - self.r_margin - 40, -12)
        self.cell(40, 8, f"Page {self.page_no()}/{{nb}}", align="R")


def _reset_body_style(pdf: FPDF) -> None:
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*_BODY_COLOR)


def _write_h2(pdf: FPDF, text: str) -> tuple[int, int, int]:
    title = _clean_heading(text)
    color = _SECTION_ACCENTS.get(title, _H2_DEFAULT_COLOR)

    pdf.ln(6)
    if pdf.get_y() > pdf.h - pdf.b_margin - 20:
        pdf.add_page()

    bar_y = pdf.get_y() + 0.5
    pdf.set_fill_color(*color)
    pdf.rect(pdf.l_margin, bar_y, 2.2, 8, style="F")

    pdf.set_xy(pdf.l_margin + 6, bar_y - 0.5)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*color)
    pdf.cell(0, 9, title)

    y = bar_y + 10
    pdf.set_draw_color(*_RULE_COLOR)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 4)
    _reset_body_style(pdf)
    return color


def _write_h3(pdf: FPDF, text: str) -> None:
    pdf.ln(3)
    if pdf.get_y() > pdf.h - pdf.b_margin - 15:
        pdf.add_page()
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.set_text_color(*_H3_COLOR)
    pdf.multi_cell(0, 7.5, _clean_heading(text), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(pdf.get_y() + 1)
    _reset_body_style(pdf)


def _write_bullet(pdf: FPDF, text: str, indent: float = 6, color: tuple[int, int, int] | None = None) -> None:
    clean = _clean_line(text)
    if not clean:
        return
    x = pdf.l_margin + indent
    pdf.set_x(x)
    y = pdf.get_y()
    pdf.set_fill_color(*(color or _BULLET_DEFAULT_COLOR))
    pdf.ellipse(x + 0.3, y + 2.4, 1.7, 1.7, style="F")

    pdf.set_x(x + 5)
    width = pdf.w - pdf.r_margin - pdf.get_x()
    _reset_body_style(pdf)
    pdf.multi_cell(width, 6.5, clean, align="L", new_x="LMARGIN", new_y="NEXT")


def _write_paragraph(pdf: FPDF, text: str) -> None:
    clean = _clean_line(text)
    if not clean:
        return
    pdf.multi_cell(0, 6.5, clean, align="L", new_x="LMARGIN", new_y="NEXT")


def _write_note(pdf: FPDF, text: str, color: tuple[int, int, int]) -> None:
    """A '> ...' blockquote line -- the LLM's usual way of calling out a
    disclaimer (e.g. "flight prices are estimates") or a weather-based tip.
    Rendered as an indented, italicized aside with a thin accent rule on the
    left, rather than showing the literal '>' markdown marker.
    """
    clean = _clean_line(text)
    if not clean:
        return
    x = pdf.l_margin + 6
    y0 = pdf.get_y()
    pdf.set_x(x + 4)
    pdf.set_font("Helvetica", "I", 10.5)
    pdf.set_text_color(*_MUTED_COLOR)
    width = pdf.w - pdf.r_margin - pdf.get_x()
    pdf.multi_cell(width, 6, clean, align="L", new_x="LMARGIN", new_y="NEXT")
    y1 = pdf.get_y()
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.6)
    pdf.line(x, y0 + 0.5, x, y1 - 1.5)
    _reset_body_style(pdf)


def _write_table(pdf: FPDF, rows: list[list[str]], accent: tuple[int, int, int]) -> None:
    if len(rows) >= 2 and _is_table_separator(rows[1]):
        rows = [rows[0]] + rows[2:]
    header, data_rows = rows[0], rows[1:]

    if len(header) <= 2:
        # Simple "Item | Details" table -- one bullet per row. A row label
        # that's just a bare index number carries nothing on its own, so
        # it's dropped rather than shown as a floating digit.
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
                _write_bullet(pdf, detail, color=accent)
            else:
                _write_bullet(pdf, f"{label}: {detail}" if detail else label, color=accent)
    else:
        # Three-or-more-column table (e.g. Day / Highlights / Cost) -- each
        # row gets its own shaded sub-heading band, with one bullet per
        # column instead of every column mashed onto one row.
        for cells in data_rows:
            if not any(cells):
                continue
            label = cells[0].strip()
            heading = f"Day {label}" if label.isdigit() else label

            pdf.ln(3)
            if pdf.get_y() > pdf.h - pdf.b_margin - 18:
                pdf.add_page()
            band_y = pdf.get_y()
            tint = tuple(min(255, c + 205) for c in accent)
            pdf.set_fill_color(*tint)
            pdf.rect(pdf.l_margin, band_y, pdf.w - pdf.l_margin - pdf.r_margin, 8.5, style="F")
            pdf.set_xy(pdf.l_margin + 3, band_y + 0.7)
            pdf.set_font("Helvetica", "B", 11.5)
            pdf.set_text_color(*accent)
            pdf.cell(0, 7, _clean_heading(heading))
            pdf.set_y(band_y + 11)
            _reset_body_style(pdf)

            for point in _labeled_cells(header, cells):
                _write_bullet(pdf, point, indent=8, color=accent)

    pdf.ln(1)


def build_full_itinerary_pdf(destination: str, full_text: str) -> bytes:
    pdf = _TripMatePDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*_TITLE_COLOR)
    pdf.cell(0, 11, "TripMate", new_x="LMARGIN", new_y="NEXT")

    pdf.set_fill_color(*_H2_DEFAULT_COLOR)
    pdf.rect(pdf.get_x(), pdf.get_y(), 26, 1.3, style="F")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 12.5)
    pdf.set_text_color(*_MUTED_COLOR)
    subtitle = "AI Travel Plan" + (f"  -  {_clean_line(destination)}" if destination else "")
    pdf.cell(0, 7, subtitle)

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_xy(pdf.l_margin, pdf.get_y())
    pdf.cell(pdf.w - pdf.l_margin - pdf.r_margin, 7, date.today().strftime("Generated %B %d, %Y"), align="R")
    pdf.ln(9)

    pdf.set_draw_color(*_RULE_COLOR)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 6)

    _reset_body_style(pdf)

    table_buf: list[list[str]] = []
    current_accent = _H2_DEFAULT_COLOR

    def flush_table() -> None:
        if table_buf:
            _write_table(pdf, list(table_buf), current_accent)
            table_buf.clear()

    for raw_line in full_text.split("\n"):
        stripped_left = raw_line.lstrip(" ")
        indent_level = min((len(raw_line) - len(stripped_left)) // 2, 3)
        line = stripped_left.strip()

        if not line or _HR_RE.match(line):
            flush_table()
            pdf.ln(2)
            continue

        table_match = _TABLE_ROW_RE.match(line)
        if table_match:
            table_buf.append(_split_table_row(line))
            continue
        flush_table()

        h2_match = _H2_RE.match(line)
        h3_match = _H3_RE.match(line)
        quote_match = _QUOTE_RE.match(line)
        is_bold_heading = line.startswith("**") and line.endswith("**") and len(line) < 62

        if h2_match:
            current_accent = _write_h2(pdf, h2_match.group(1))
        elif h3_match:
            _write_h3(pdf, h3_match.group(1))
        elif is_bold_heading:
            _write_h3(pdf, line)
        elif quote_match:
            _write_note(pdf, quote_match.group(1), current_accent)
        elif _BULLET_RE.match(line):
            _write_bullet(
                pdf, _BULLET_RE.sub("", line), indent=6 + indent_level * 5, color=current_accent
            )
        elif _NUM_LIST_RE.match(line):
            # A genuine ordered list item (e.g. numbered packing/booking
            # tips) -- kept as a bullet with its number intact rather than
            # promoted to a heading, since every real section/sub-section
            # title is already normalized to "#"/"##" upstream in
            # ui/components.py before this text ever reaches the PDF.
            _write_bullet(pdf, line, indent=6 + indent_level * 5, color=current_accent)
        else:
            _write_paragraph(pdf, line)

    flush_table()
    return bytes(pdf.output())
