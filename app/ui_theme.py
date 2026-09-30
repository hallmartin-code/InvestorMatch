"""TEN Capital Network web UI styling: the dark navy / coral–amber–teal design.

Colors, type and component shapes follow the approved deck-analyzer mock-up. Brand accents are
used for chrome only (cards, buttons, eyebrows); data colors come from the validated dark chart
palette in ``app/ui_charts.py``. The PDF keeps its light print theme.
"""

from __future__ import annotations

import base64
from html import escape

import streamlit as st

NAVY_950 = "#0B1526"
NAVY_900 = "#101E33"
NAVY_800 = "#16283F"
NAVY_700 = "#1E354F"
CORAL = "#EE5A4E"
CORAL_SOFT = "#F0776C"
AMBER = "#F3A22A"
TEAL = "#35BEBB"
INK_100 = "#F3F6FA"
INK_300 = "#C4D0E0"
INK_500 = "#7E90A8"
INK_600 = "#5C6E86"

def _brand_mark() -> str:
    """The TEN Capital icon (app/static/favicon.png), inlined because st.html cannot load files."""
    from io import BytesIO

    from PIL import Image

    from app.config import FAVICON_PATH

    try:
        with Image.open(FAVICON_PATH) as icon:
            buffer = BytesIO()
            icon.convert("RGBA").resize((96, 96), Image.LANCZOS).save(buffer, format="PNG", optimize=True)
        data = base64.b64encode(buffer.getvalue()).decode()
        return f'<img class="tc-mark" alt="" src="data:image/png;base64,{data}">'
    except OSError:
        return ""


BRAND_MARK = _brand_mark()

CSS = f"""
<style>
:root {{
  --navy-950:{NAVY_950}; --navy-900:{NAVY_900}; --navy-800:{NAVY_800}; --navy-700:{NAVY_700};
  --coral:{CORAL}; --coral-soft:{CORAL_SOFT}; --amber:{AMBER}; --teal:{TEAL};
  --ink-100:{INK_100}; --ink-300:{INK_300}; --ink-500:{INK_500}; --ink-600:{INK_600};
}}
/* ambient tri-color glow, echoing the logo's three figures */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(480px 380px at 14% 8%, rgba(238,90,78,0.14), transparent 60%),
    radial-gradient(480px 380px at 86% 6%, rgba(243,162,42,0.11), transparent 60%),
    radial-gradient(560px 420px at 50% 100%, rgba(53,190,187,0.12), transparent 60%),
    var(--navy-950);
  background-attachment: fixed;
}}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}

/* brand lockup */
.tc-brand {{ display:flex; align-items:center; gap:12px; margin: 0 0 18px 2px; }}
.tc-mark {{ width:34px; height:34px; flex-shrink:0; }}
.tc-word {{ font-family:'Sora',sans-serif; font-weight:800; font-size:15px; letter-spacing:.04em;
  line-height:1.15; color:var(--ink-100); text-transform:uppercase; }}
.tc-word span {{ display:block; font-weight:600; font-size:10px; letter-spacing:.22em; color:var(--ink-500);
  margin-top:2px; }}
.tc-brand .tc-app {{ margin-left:auto; font-family:'JetBrains Mono',monospace; font-size:11px;
  letter-spacing:.14em; text-transform:uppercase; color:var(--ink-500); }}

/* step tracker */
.tc-steps {{ display:flex; gap:6px; margin: 0 0 18px; flex-wrap:wrap; }}
.tc-step {{ flex:1 1 140px; display:flex; align-items:center; gap:8px; padding:8px 12px; border-radius:10px;
  border:1px solid var(--navy-700); background:rgba(255,255,255,0.015); color:var(--ink-500);
  font-size:12.5px; font-weight:500; white-space:nowrap; }}
.tc-step b {{ font-family:'JetBrains Mono',monospace; font-weight:500; font-size:11px; width:20px; height:20px;
  border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
  border:1px solid var(--navy-700); color:var(--ink-500); }}
.tc-step.done {{ color:var(--ink-300); }}
.tc-step.done b {{ background:rgba(53,190,187,.16); border-color:var(--teal); color:var(--teal); }}
.tc-step.current {{ color:var(--ink-100); border-color:transparent;
  background:linear-gradient(var(--navy-800),var(--navy-800)) padding-box,
             linear-gradient(90deg,var(--coral),var(--amber),var(--teal)) border-box; }}
.tc-step.current b {{ background:linear-gradient(135deg,var(--coral),var(--amber)); border:none; color:#17130E; }}

/* hero card (a keyed st.container) */
[class*="st-key-tc-hero"] {{
  background: linear-gradient(180deg, var(--navy-900) 0%, var(--navy-800) 100%);
  border: 1px solid var(--navy-700); border-radius: 20px; padding: 30px 34px 24px !important;
  box-shadow: 0 30px 60px -20px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.03);
  position: relative; overflow: hidden; margin-bottom: 18px;
}}
[class*="st-key-tc-hero"]::after {{ content:""; position:absolute; top:-2px; left:34px; right:34px; height:2px;
  background:linear-gradient(90deg,var(--coral),var(--amber),var(--teal)); border-radius:2px; }}
.tc-eyebrow {{ display:flex; align-items:center; gap:8px; font-family:'JetBrains Mono',monospace;
  font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--teal); margin-bottom:10px; }}
.tc-eyebrow::before {{ content:""; width:6px; height:6px; border-radius:50%; background:var(--teal);
  box-shadow:0 0 0 3px rgba(53,190,187,.18); }}
.tc-title {{ font-family:'Sora',sans-serif; font-size:28px; font-weight:700; line-height:1.25; margin:0 0 8px;
  letter-spacing:-.01em; color:var(--ink-100); }}
.tc-title .arrow {{ color:var(--ink-500); font-weight:400; margin:0 4px; }}
.tc-title .to {{ background:linear-gradient(90deg,var(--coral-soft),var(--amber)); -webkit-background-clip:text;
  background-clip:text; color:transparent; }}
.tc-lede {{ color:var(--ink-300); font-size:15px; line-height:1.6; margin:0 0 6px; max-width:74ch; }}

/* generic panels: bordered st.container */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  border-color: var(--navy-700);
}}
[data-testid="stExpander"] details {{ background: rgba(255,255,255,0.015); border-color: var(--navy-700); }}

/* dropzone */
[data-testid="stFileUploaderDropzone"] {{
  border: 1.5px dashed var(--navy-700) !important; border-radius: 14px !important;
  background: rgba(255,255,255,0.015) !important; padding: 26px 22px !important;
  transition: border-color .18s ease, background .18s ease;
}}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: var(--teal) !important;
  background: rgba(53,190,187,0.05) !important; }}
[data-testid="stFileUploaderDropzoneInstructions"] svg {{ color: var(--amber); }}

/* CTA: primary buttons, including downloads */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  border: none !important; color: #17130E !important; font-family:'Sora',sans-serif; font-weight:700;
  background: linear-gradient(90deg, var(--coral) 0%, var(--coral-soft) 45%, var(--amber) 100%) !important;
  box-shadow: 0 10px 24px -10px rgba(238,90,78,.45); transition: filter .15s ease, transform .15s ease;
}}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  filter: brightness(1.06); transform: translateY(-1px); }}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {{ color:#17130E !important; }}
.st-key-tc-cta button {{ width: 100%; padding: 14px 20px; font-size: 15px; }}

/* metrics as tiles */
[data-testid="stMetric"] {{ background: rgba(255,255,255,0.02); border: 1px solid var(--navy-700);
  border-radius: 14px; padding: 12px 14px; }}
[data-testid="stMetricLabel"] p {{ font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--ink-500); }}
[data-testid="stMetricValue"] {{ font-family:'Sora',sans-serif; font-weight:700; }}

/* multiselect chips: quiet navy with teal text instead of solid coral */
[data-testid="stMultiSelectTagsContainer"] span[data-tag] {{ background: rgba(53,190,187,0.12) !important;
  border: 1px solid rgba(53,190,187,0.38); color: var(--ink-100) !important; }}
[data-testid="stMultiSelectTagsContainer"] span[data-tag] span {{ color: var(--ink-100) !important; }}
[data-testid="stMultiSelectTagsContainer"] span[data-tag] button {{ color: var(--teal) !important; }}

/* tabs */
[data-baseweb="tab-highlight"] {{ background: linear-gradient(90deg,var(--coral),var(--amber)); }}

/* disclosure and footer */
.tc-disclosure {{ margin-top:18px; padding-top:14px; border-top:1px solid var(--navy-700); font-size:12px;
  line-height:1.6; color:var(--ink-500); }}
.tc-disclosure code {{ font-family:'JetBrains Mono',monospace; background:var(--navy-950);
  border:1px solid var(--navy-700); color:var(--ink-300); padding:2px 6px; border-radius:5px; font-size:11.5px; }}
.tc-footer {{ text-align:center; margin: 34px 0 6px; font-family:'JetBrains Mono',monospace; font-size:11px;
  letter-spacing:.08em; color:var(--ink-600); text-transform:uppercase; }}

/* sidebar */
[data-testid="stSidebar"] .tc-brand {{ margin-bottom: 8px; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color: var(--ink-500); }}

/* ---- mockup alignment: focused input card, dropzones, full-width CTA, clickable step nav ---- */
.st-key-tc-hero-narrow {{ max-width: 780px; margin-left:auto !important; margin-right:auto !important;
  padding: 40px 44px 34px !important; }}
.st-key-tc-hero-narrow .tc-lede {{ margin-bottom: 18px; }}
[class*="st-key-tc-hero"] .tc-lede {{ max-width: 64ch; }}

/* dropzones: centered, icon tile, mono format line (as in the mockup) */
[data-testid="stFileUploaderDropzone"] {{ flex-direction: column; justify-content:center; align-items:center;
  text-align:center;
  gap: 12px; padding: 28px 22px !important; cursor: pointer; }}
[data-testid="stFileUploaderDropzone"]::before {{ content:""; width:38px; height:38px; border-radius:10px;
  flex-shrink:0; margin: 0 auto; align-self:center;
  border:1px solid var(--navy-700);
  background: url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23F3F6FA' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14 3v4a1 1 0 0 0 1 1h4'/%3E%3Cpath d='M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z'/%3E%3C/svg%3E") center/18px no-repeat,
    linear-gradient(135deg, rgba(238,90,78,.16), rgba(243,162,42,.16)); }}
[data-testid="stFileUploaderDropzoneInstructions"] {{ font-family:'JetBrains Mono',monospace; font-size:11.5px;
  color: var(--ink-500); letter-spacing:.01em; }}
[data-testid="stFileUploaderDropzoneInstructions"] svg {{ display:none; }}
.st-key-deck_upload [data-testid="stFileUploaderDropzone"] {{ padding: 40px 24px !important; }}
/* once files are chosen, show the file chips left-aligned without the decorative icon */
[data-testid="stFileUploaderDropzone"]:has([data-testid="stFileChips"]) {{ align-items: stretch; text-align:left;
  padding: 16px 18px !important; }}
[data-testid="stFileUploaderDropzone"]:has([data-testid="stFileChips"])::before {{ display:none; }}
[data-testid="stFileUploader"] label p {{ font-family:'Sora',sans-serif; font-weight:600; font-size:14px;
  color: var(--ink-100); }}

/* full-width call to action (st.button(width="stretch") inside .st-key-tc-cta) */
.st-key-tc-cta button {{ padding: 15px 20px !important; font-size: 15px !important; border-radius: 12px !important; }}

/* clickable step navigation (replaces the static tracker and the sidebar radio) */
.st-key-tc-nav {{ margin-bottom: 14px; }}
.st-key-tc-nav [data-testid="stHorizontalBlock"] {{ gap: 6px; }}
[class*="st-key-tc-nav-"] button {{ width:100%; justify-content:flex-start; border-radius:10px;
  border:1px solid var(--navy-700) !important; background:rgba(255,255,255,0.015) !important;
  color:var(--ink-500) !important; font-size:12.5px; font-weight:500; padding: 8px 12px; min-height: 0; }}
[class*="st-key-tc-nav-"] button p {{ font-size:12.5px; white-space:nowrap; }}
[class*="st-key-tc-nav-"] button:hover:not(:disabled) {{ border-color: var(--teal) !important; color: var(--ink-100) !important; }}
[class*="st-key-tc-nav-"] button:disabled {{ opacity:.7; }}

@media (max-width: 640px) {{
  [class*="st-key-tc-hero"] {{ padding: 24px 20px 20px !important; }}
  .tc-title {{ font-size: 23px; }}
  .tc-step {{ flex-basis: 100%; }}
}}
</style>
"""


def apply_theme() -> None:
    st.html(CSS)


def brand(app_label: str | None = "Investor Match") -> None:
    label = f'<div class="tc-app">{escape(app_label)}</div>' if app_label else ""
    st.html(f'<div class="tc-brand">{BRAND_MARK}<div class="tc-word">Ten Capital<span>Network</span></div>'
            f"{label}</div>")


def step_tracker(steps: list[str], current: int, done: set[int]) -> None:
    items = []
    for index, name in enumerate(steps):
        cls = "current" if index == current else ("done" if index in done else "")
        mark = "✓" if index in done and index != current else str(index + 1)
        items.append(f'<div class="tc-step {cls}"><b>{mark}</b>{escape(name)}</div>')
    st.html(f'<div class="tc-steps">{"".join(items)}</div>')


def hero(eyebrow: str, title: str, highlight: str | None, lede: str, *, narrow: bool = False, key: str = "main"):
    """A hero card; returns the container so a step can place its main controls inside it.
    ``narrow`` gives the focused, centered card of the input step (as in the design mockup)."""
    container = st.container(key="tc-hero-narrow" if narrow else f"tc-hero-{key}")
    title_html = escape(title)
    if highlight:
        title_html += f'<span class="arrow">&rarr;</span><span class="to">{escape(highlight)}</span>'
    container.html(f'<div class="tc-eyebrow">{escape(eyebrow)}</div><h1 class="tc-title">{title_html}</h1>'
                   f'<p class="tc-lede">{escape(lede)}</p>')
    return container


def step_nav(steps: list[str], current: int, done: set[int], enabled: set[int]) -> int | None:
    """Clickable step pills: current step has the gradient border, completed steps a teal check.
    Returns the index clicked (or None)."""
    styles = []
    for i in range(len(steps)):
        sel = f".st-key-tc-nav-{i} button"
        if i == current:
            styles.append(f"{sel} {{ color:var(--ink-100) !important; border-color:transparent !important;"
                          "background:linear-gradient(var(--navy-800),var(--navy-800)) padding-box,"
                          "linear-gradient(90deg,var(--coral),var(--amber),var(--teal)) border-box !important; }")
        elif i in done:
            styles.append(f"{sel} {{ color:var(--ink-300) !important; }}")
    st.html("<style>" + "".join(styles) + "</style>")
    clicked = None
    with st.container(key="tc-nav"):
        for i, (col, name) in enumerate(zip(st.columns(len(steps)), steps, strict=True)):
            mark = "✓" if i in done and i != current else str(i + 1)
            if col.button(f"{mark}  {name}", key=f"tc-nav-{i}", disabled=i not in enabled and i != current,
                          width="stretch"):
                clicked = i
    return clicked


def disclosure(html: str, target=None) -> None:
    (target or st).html(f'<div class="tc-disclosure">{html}</div>')


def code(text: str) -> str:
    return f"<code>{escape(text)}</code>"


def footer() -> None:
    st.html('<div class="tc-footer">Powered by TEN Capital Network</div>')
