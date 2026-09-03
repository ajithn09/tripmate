"""Dark "mission control" theme, translated from tripmate-ui.html.

Injected once via a single st.markdown(..., unsafe_allow_html=True) call at
the top of streamlit_app.py. Native Streamlit widgets (chat messages,
buttons, forms, sidebar) are restyled through their data-testid/class
selectors; the boarding-pass card and mission-control panel are raw HTML
built in ui/components.py and styled through their own classes below.

NOTE: data-testid values can shift across Streamlit releases -- keep the
`streamlit` version pinned in requirements.txt so these selectors don't
silently stop matching after an upgrade.
"""

import streamlit as st

CSS_BLOCK = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root{
  --bg: #0a0f1a;
  --bg-soft: #0d1524;
  --panel: #101a2c;
  --panel-2: #0c1526;
  --line: #1c2942;
  --line-soft: #16223a;
  --text: #eaeef7;
  --text-dim: #97a3bd;
  --text-faint: #5b6780;
  --amber: #ffb020;
  --amber-dim: #7a5a1f;
  --cyan: #3fd6c8;
  --cyan-dim: #1c5a54;
  --green: #3ddc97;
  --red: #ff6b6b;
  --radius: 14px;
}

html, body, [data-testid="stAppViewContainer"], .stApp{
  background:
    radial-gradient(1200px 600px at 15% -10%, #10203a 0%, transparent 60%),
    radial-gradient(900px 500px at 110% 10%, #0d1f2a 0%, transparent 55%),
    var(--bg) !important;
  color: var(--text);
  font-family: 'Inter', sans-serif;
}

[data-testid="stHeader"]{ background: transparent; }

[data-testid="stSidebar"]{
  background: linear-gradient(180deg, var(--panel), var(--panel-2));
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] *{ color: var(--text); }

h1, h2, h3, h4, .tm-display{
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 700;
}

/* ---------- Brand header ---------- */
.tm-header{
  display:flex; align-items:center; justify-content:space-between;
  padding: 6px 4px 18px; border-bottom: 1px solid var(--line-soft);
  margin-bottom: 18px;
}
.tm-brand{ display:flex; align-items:center; gap:12px; }
.tm-brand-mark{
  width:38px; height:38px; border-radius:10px;
  background: linear-gradient(155deg,#1a2740,#0c1424);
  border:1px solid var(--line);
  display:flex; align-items:center; justify-content:center;
}
.tm-brand-name{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:19px; }
.tm-brand-tag{
  font-size:11.5px; color:var(--text-faint); font-family:'IBM Plex Mono',monospace;
  letter-spacing:0.3px; margin-top:1px;
}
.tm-live-pill{
  display:flex; align-items:center; gap:7px; font-family:'IBM Plex Mono',monospace;
  font-size:11.5px; color:var(--green); letter-spacing:0.5px;
}
.tm-live-dot{
  width:7px; height:7px; border-radius:50%; background: var(--green);
  box-shadow: 0 0 0 0 rgba(61,220,151,0.6); animation: tm-pulse 2s infinite;
  display:inline-block;
}
@keyframes tm-pulse{
  0%{ box-shadow: 0 0 0 0 rgba(61,220,151,0.45); }
  70%{ box-shadow: 0 0 0 7px rgba(61,220,151,0); }
  100%{ box-shadow: 0 0 0 0 rgba(61,220,151,0); }
}

/* ---------- Sidebar brand ---------- */
.tm-sidebar-brand{ display:flex; align-items:center; gap:10px; margin-bottom:14px; }
.tm-sidebar-mark{
  width:34px; height:34px; border-radius:9px;
  background: linear-gradient(155deg,#1a2740,#0c1424);
  border:1px solid var(--line);
  display:flex; align-items:center; justify-content:center; flex-shrink:0;
}
.tm-sidebar-name{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:17px; color:var(--text); }

.tm-badge{
  display:inline-block; font-family:'IBM Plex Mono',monospace; font-size:10.5px;
  padding:5px 10px; border-radius:999px; letter-spacing:0.3px;
  background: rgba(124,127,255,0.12); color:#9fa3ff; border:1px solid rgba(124,127,255,0.3);
  margin-bottom:12px;
}

.tm-sidebar-desc{ font-size:12.5px; color:var(--text-dim); line-height:1.5; margin-bottom:18px; }

.tm-thread-label{
  font-family:'IBM Plex Mono',monospace; font-size:10px; color:var(--text-faint);
  letter-spacing:0.6px; margin-bottom:6px;
}
.tm-thread-box{
  font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--text-dim);
  background: rgba(255,255,255,0.03); border:1px solid var(--line); border-radius:8px;
  padding:9px 11px; word-break:break-all; margin-bottom:16px;
}

[data-testid="stSidebar"] .stButton > button[kind="primary"]{
  background: linear-gradient(180deg,#7c6ff5,#5a4bd6) !important;
  color:#fff !important; border:none !important;
}

.tm-callout{
  display:flex; gap:10px; align-items:flex-start;
  background: rgba(124,127,255,0.06); border:1px solid rgba(124,127,255,0.22);
  border-radius:12px; padding:13px 14px; margin-top:16px; font-size:12px; color:var(--text-dim); line-height:1.5;
}

.stButton > button[kind="secondary"]{
  text-align:left !important; justify-content:flex-start !important;
  font-size:12.5px !important;
}
.tm-callout-icon{ font-size:16px; flex-shrink:0; margin-top:1px; }

/* ---------- Sample-query expander ---------- */
[data-testid="stExpander"]{
  border: none !important;
  background: transparent !important;
}
[data-testid="stExpander"] summary{
  border: none !important;
  background: rgba(255,255,255,0.03) !important;
  border-radius: 10px !important;
}
[data-testid="stExpander"] [data-testid="stExpanderDetails"]{
  border: none !important;
  background: transparent !important;
}

/* ---------- Chat messages ---------- */
[data-testid="stChatMessage"]{
  background: transparent !important;
  border: none !important;
}
[data-testid="stChatMessageAvatarUser"]{
  background: linear-gradient(160deg,#ff8fa8,#e0507a) !important;
  color: #fff !important;
  border: none !important;
}
[data-testid="stChatMessageAvatarAssistant"]{
  background: linear-gradient(160deg,#ffcf7a,#ffb020) !important;
  color: #241a02 !important;
  border: none !important;
}
[data-testid="stChatMessageContent"]{
  background: rgba(255,255,255,0.035);
  border: none;
  border-radius: 12px;
  padding: 12px 18px !important;
  font-size: 13.8px;
}
[data-testid="stChatMessageContent"] p{ margin-bottom: 0.4rem; }

.tm-msg-time{
  font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:var(--text-faint);
  text-align:right; white-space:nowrap; letter-spacing:0.3px; padding-top:2px;  margin-bottom: 10px;
}

/* Icon section headers inside assistant responses (Trip Summary, Flight
   Information, ...) -- see ui/components.py:style_response_sections. Flex
   so the Trip Summary heading's PDF download icon (appended to that one
   h2's text in streamlit_app.py) lands at the end of the same line.
   Streamlit gives headings their own default flex layout for its built-in
   hover-only permalink icon -- display/justify-content need !important
   here or that default silently wins and the icon sits wherever it falls
   in the text instead of at the far right. */
[data-testid="stChatMessageContent"] h2{
  display:flex !important; align-items:center !important; justify-content:space-between !important; gap:10px;
  font-size:16px; font-weight:700; margin:16px 0 10px; padding-bottom:8px;
  border-bottom:1px solid var(--line-soft);
}
[data-testid="stChatMessageContent"] h2:first-child{ margin-top:2px; }
.tm-pdf-link{
  flex-shrink:0; font-size:16px; line-height:1; text-decoration:none;
  opacity:0.85; margin-left:auto;
}
.tm-pdf-link:hover{ opacity:1; }
[data-testid="stChatMessageContent"] ul{ margin:6px 0 12px 4px; padding-left:18px; }
[data-testid="stChatMessageContent"] li{ margin-bottom:4px; color:var(--text-dim); }
[data-testid="stChatMessageContent"] li::marker{ color:var(--cyan); }
[data-testid="stChatMessageContent"] strong{ color:var(--text); }

/* Icon sub-headers inside a section (Quick-Look Overview, Money-Saving
   Tips, Budget Breakdown, ...) -- see ui/components.py:_style_subsections */
[data-testid="stChatMessageContent"] h3{
  display:flex; align-items:center; gap:7px;
  font-size:13px; font-weight:700; color:var(--cyan);
  letter-spacing:0.2px; margin:16px 0 8px;
}
[data-testid="stChatMessageContent"] h3:first-child{ margin-top:4px; }
[data-testid="stChatMessageContent"] h3 + ul{
  background: rgba(63,214,200,0.05);
  border: 1px solid var(--line-soft);
  border-radius: 10px;
  margin: 0 0 14px;
  padding: 10px 14px 10px 30px;
}
[data-testid="stChatMessageContent"] h3 + p{ color:var(--text-dim); font-size:13px; }

/* Budget Breakdown cost-category grid -- see
   ui/components.py:_style_budget_breakdown, which turns its bullet list
   into a real markdown table. */
[data-testid="stChatMessageContent"] table{
  width:100%; border-collapse:collapse;
  margin:2px 0 14px;
  border:1px solid var(--line-soft); border-radius:10px;
  overflow:hidden;
}
[data-testid="stChatMessageContent"] thead th{
  text-align:left; background: rgba(255,255,255,0.04); color:var(--text-faint);
  font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:0.5px;
  text-transform:uppercase;
  padding:8px 12px; border-bottom:1px solid var(--line-soft);
}
[data-testid="stChatMessageContent"] td{
  padding:8px 12px; border-bottom:1px solid var(--line-soft);
  color:var(--text-dim); font-size:13px;
}
[data-testid="stChatMessageContent"] tbody tr:last-child td{
  border-bottom:none;
}

/* Pinned to the bottom of the viewport while staying inside col_chat's
   width (rather than Streamlit's page-wide fixed-footer treatment, which
   only applies when chat_input is declared outside any column). */
[data-testid="stChatInput"]{
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  position: sticky;
  bottom: 1rem;
  z-index: 10;
}
[data-testid="stChatInput"] textarea{ color: var(--text) !important; }

/* ---------- Buttons ---------- */
.stButton > button{
  border-radius: 9px !important;
  font-weight: 600 !important;
  font-family: 'Inter', sans-serif !important;
  border: 1px solid var(--line) !important;
}
.stButton > button[kind="primary"]{
  background: linear-gradient(180deg,#3ddc97,#22b578) !important;
  color: #052014 !important;
  border: none !important;
}
.stButton > button[kind="secondary"]{
  background: rgba(255,255,255,0.04) !important;
  color: var(--text-dim) !important;
}

/* ---------- Text areas ---------- */
.stTextArea textarea{
  background: rgba(255,255,255,0.03) !important;
  border: 1px solid var(--line) !important;
  color: var(--text) !important;
  border-radius: 8px !important;
}

/* ---------- Boarding pass draft card ---------- */
.boarding-pass{
  background: transparent;
  margin: 6px 0 20px;
}
.bp-top{ display:flex; justify-content:space-between; align-items:flex-start; padding:0 0 12px; }
.bp-route{ display:flex; align-items:center; gap:12px; }
.bp-city{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:19px; }
.bp-city small{ display:block; font-family:'IBM Plex Mono',monospace; font-weight:500; font-size:10px; color:var(--text-faint); margin-top:2px; letter-spacing:0.5px; }
.bp-status{
  font-family:'IBM Plex Mono',monospace; font-size:10.5px; padding:3px 0;
  color: var(--amber); letter-spacing:0.4px; white-space:nowrap;
}
.bp-divider{ display:none; }
.bp-meta{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; padding:0 0 14px; }
.bp-meta .label{ display:block; font-family:'IBM Plex Mono',monospace; font-size:9.5px; color:var(--text-faint); letter-spacing:0.6px; margin-bottom:4px; }
.bp-meta .value{ display:block; font-size:13px; font-weight:600; color:var(--text); }
.bp-body{ padding: 0; font-size:13.3px; line-height:1.6; color:var(--text-dim); }
.bp-body b{ color:var(--text); }
.bp-body p{ margin:0 0 12px; }
.bp-body p:last-child{ margin-bottom:0; }
.bp-body ul{ margin:0 0 14px; padding-left:20px; }
.bp-body ul:last-child{ margin-bottom:0; }
.bp-body li{ margin-bottom:5px; }
.bp-body li::marker{ color:var(--cyan); }
.bp-day{
  font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:13.5px; color:var(--text);
  margin:16px 0 8px;
}
.bp-day:first-child{ margin-top:0; }
.bp-empty{ color:var(--text-faint); }

/* ---------- Boarding pass approve/revise action panel ---------- */
.bp-actions-title{
  font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--text-faint);
  letter-spacing:0.4px; margin-bottom:14px;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.bp-actions-title){
  background: transparent;
  border: none !important;
  padding: 4px 0 2px;
  margin: 0 0 20px;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.bp-actions-title) [data-testid="stForm"]{
  border: none !important;
  padding: 0 !important;
  background: transparent !important;
}

/* ---------- Mission control ---------- */
/* Pinned in place like the sidebar, and always the full height of the
   screen (not just as tall as its content) -- top offset clears
   Streamlit's own fixed toolbar, and content taller than that scrolls
   inside the panel instead of overflowing it. */
.mission-control{
  background: transparent;
  padding: 4px 0 2px;
  position: sticky;
  top: 3rem;
  height: calc(100vh - 3rem);
  overflow-y: auto;
  z-index: 5;
  scrollbar-width: thin;
  scrollbar-color: var(--line) transparent;
}
.mission-control::-webkit-scrollbar{ width: 8px; }
.mission-control::-webkit-scrollbar-track{ background: transparent; }
.mission-control::-webkit-scrollbar-thumb{ background: var(--line); border-radius: 4px; }
.mission-control::-webkit-scrollbar-thumb:hover{ background: var(--text-faint); }
.mc-head{
  padding: 4px 18px 14px; border-bottom: 1px solid var(--line-soft); margin-bottom: 6px;
  display:flex; align-items:flex-start; justify-content:space-between; gap:10px;
}
.mc-title{ font-family:'Space Grotesk',sans-serif; font-weight:600; font-size:14.5px; display:flex; align-items:center; gap:8px; }
.mc-blip{ width:6px; height:6px; border-radius:50%; background: var(--amber); display:inline-block; animation: tm-pulse 1.6s infinite; }
.mc-sub{ font-size:11.5px; color:var(--text-faint); font-family:'IBM Plex Mono',monospace; margin-top:3px; }

.pipeline{ padding: 10px 20px 6px; position:relative; }
.node{ position:relative; display:flex; gap:14px; padding-bottom:20px; }
.node:last-child{ padding-bottom:4px; }
.node::before{
  content:''; position:absolute; left:6px; top:20px; bottom:-6px; width:1px;
  background: repeating-linear-gradient(to bottom, var(--line) 0 4px, transparent 4px 9px);
}
.node:last-child::before{ display:none; }
.node-dot{
  width:13px; height:13px; border-radius:50%; background: var(--panel-2); border:2px solid var(--line);
  flex-shrink:0; margin-top:2px; position:relative; z-index:1;
}
.node.status-done .node-dot{ border-color: var(--green); background: var(--green); box-shadow: 0 0 0 5px rgba(61,220,151,0.13); }
.node.status-waiting .node-dot{ border-color: var(--cyan); background: var(--cyan-dim); }
.node.status-blocked .node-dot{ border-color: var(--red); background: var(--red); }
.node-body{ flex:1; min-width:0; }
.node-name{
  font-family:'IBM Plex Mono',monospace; font-size:11.5px; font-weight:600; letter-spacing:0.5px;
  color: var(--text-faint); display:flex; align-items:center; justify-content:space-between;
}
.node.status-done .node-name, .node.status-waiting .node-name, .node.status-blocked .node-name{ color: var(--text); }
.node-meta{ display:flex; align-items:center; gap:8px; flex-shrink:0; }
.node-time{ font-family:'IBM Plex Mono',monospace; font-size:9.5px; color:var(--text-faint); white-space:nowrap; }
.node-chevron{ font-size:9px; color:var(--text-faint); }
.node-status{ font-size:9.5px; padding:2px 7px; border-radius:5px; background: rgba(255,255,255,0.04); color: var(--text-faint); letter-spacing:0.4px; }
.node.status-done .node-status{ background: rgba(61,220,151,0.14); color: var(--green); }
.node.status-waiting .node-status{ background: rgba(63,214,200,0.14); color: var(--cyan); }
.node.status-blocked .node-status{ background: rgba(255,107,107,0.14); color: var(--red); }
.node.status-skipped .node-status{ background: rgba(255,255,255,0.03); color: var(--text-faint); }
.node-detail{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--text-faint); margin-top:5px; line-height:1.5; }
.node.status-done .node-detail, .node.status-waiting .node-detail{ color: var(--cyan); }
.node.status-blocked .node-detail{ color: var(--red); }

.mc-divider{ height:1px; background: var(--line-soft); margin: 6px 20px 0; }

.guardrail-box, .mcp-box{
  margin: 14px 20px; padding:13px 0; border-top:1px solid var(--line-soft);
  background: transparent;
}
.guardrail-box h4, .mcp-box h4{
  margin:0 0 9px; font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:var(--text-faint);
  letter-spacing:0.6px; font-weight:500;
}
.check-row{ display:flex; align-items:center; justify-content:space-between; font-size:12px; color:var(--text-dim); padding:6px 0; border-top:1px solid var(--line-soft); }
.check-row:first-of-type{ border-top:none; }
.check-ok{ color: var(--green); font-size:11px; font-family:'IBM Plex Mono',monospace; display:flex; align-items:center; gap:5px; }
.check-ok::before{ content:'✓'; }
.check-blocked{ color: var(--red); font-size:11px; font-family:'IBM Plex Mono',monospace; display:flex; align-items:center; gap:5px; }
.check-blocked::before{ content:'✕'; }
.mcp-row{ display:flex; align-items:center; gap:9px; font-size:12px; color:var(--text-dim); padding:4px 0; }
.mcp-row .tag{
  font-family:'IBM Plex Mono',monospace; font-size:9.5px; padding:2px 6px; border-radius:4px;
  background: rgba(63,214,200,0.1); color:var(--cyan); border:1px solid rgba(63,214,200,0.22);
}

</style>
"""


def inject_css() -> None:
    st.markdown(CSS_BLOCK, unsafe_allow_html=True)
