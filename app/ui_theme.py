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
.tc-disclosure {{ margin-top:18px; padding-top:14px; border-top:1px solid var(--navy-700); font-size:13px;
  line-height:1.6; color:var(--ink-300); }}
.tc-disclosure b {{ color: var(--ink-100); font-weight:600; }}
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
[data-testid="stFileUploaderDropzone"]::before {{ display:none !important; content:""; width:38px; height:38px; border-radius:10px;
  flex-shrink:0; margin: 0 auto; align-self:center;
  border:1px solid var(--navy-700);
  background: url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23F3F6FA' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14 3v4a1 1 0 0 0 1 1h4'/%3E%3Cpath d='M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z'/%3E%3C/svg%3E") center/18px no-repeat,
    linear-gradient(135deg, rgba(238,90,78,.16), rgba(243,162,42,.16)); }}
[data-testid="stFileUploaderDropzoneInstructions"] {{ font-family:inherit; font-size:12.5px;
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
[class*="st-key-tc-nav-"] button p {{ font-size:12.5px; white-space:normal; line-height:1.25; }}
[class*="st-key-tc-nav-"] button:hover:not(:disabled) {{ border-color: var(--teal) !important; color: var(--ink-100) !important; }}
[class*="st-key-tc-nav-"] button:disabled {{ opacity:.7; }}

/* ---- usability round: stepper states, disabled CTA, drop zones, tooltips, no sidebar ---- */
.st-key-tc-nav [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
.st-key-tc-nav [data-testid="stColumn"] {{ min-width: 110px; }}
.tc-locked button {{ opacity:.45; border-style:dashed !important; cursor:not-allowed !important; }}

/* main button: grey and inert until the required inputs are in */
[data-testid="stBaseButton-primary"]:disabled {{ background: var(--navy-700) !important; color: var(--ink-500) !important;
  box-shadow: none !important; filter: none !important; transform: none !important; cursor: not-allowed !important; }}
[data-testid="stBaseButton-primary"]:disabled p {{ color: var(--ink-500) !important; }}
.tc-cta-note {{ text-align:center; font-size:13px; color: var(--ink-300); margin: 2px 0 6px; }}
.tc-cta-note.todo {{ color: var(--amber); }}
.tc-cta-note b {{ color: var(--ink-100); font-weight:600; }}

/* drop zones: say what they do, highlight while a file is dragged over them */
.st-key-deck_upload [data-testid="stFileUploaderDropzoneInstructions"]::before,
.st-key-intro_upload [data-testid="stFileUploaderDropzoneInstructions"]::before {{
  display:block; color: var(--ink-100); font-size:14px; font-weight:600; margin-bottom:4px; }}
.st-key-deck_upload [data-testid="stFileUploaderDropzoneInstructions"]::before {{
  content: "Drag and drop or browse"; }}
.st-key-intro_upload [data-testid="stFileUploaderDropzoneInstructions"]::before {{
  content: "Drag and drop or browse"; }}
.st-key-intro_upload [data-testid="stFileUploaderDropzone"] {{ padding: 12px 16px !important; flex-direction: row; gap: 14px; }}
[data-testid="stFileUploaderDropzoneInstructions"] {{ display:flex; flex-direction:column; align-items:center; }}
[data-testid="stFileUploaderDropzone"].tc-drag {{ border-color: var(--teal) !important;
  background: rgba(53,190,187,0.10) !important; box-shadow: 0 0 0 3px rgba(53,190,187,0.25); }}
.tc-file-meta {{ font-size:13px; color: var(--ink-300); margin: -4px 0 10px 2px; }}
.tc-file-meta b {{ color: var(--ink-100); font-weight:600; }}

/* investor-list picker */
.tc-badge {{ display:inline-block; font-size:11px; font-weight:600; letter-spacing:.04em; padding:2px 8px;
  border-radius:999px; margin-left:8px; vertical-align:middle; }}
.tc-badge.rec {{ background: rgba(53,190,187,0.16); color: var(--teal); border:1px solid rgba(53,190,187,0.45); }}
.tc-list-meta {{ font-size:12.5px; color: var(--ink-500); margin: -10px 0 8px 30px; }}

/* tooltips always above dropdowns and popovers */
[data-baseweb="tooltip"] {{ z-index: 1000002 !important; }}

/* no sidebar (its content moved into the page) */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{ display:none !important; }}

/* ---- round 3: list age, lingering tooltips, compact step bar on phones ---- */
.tc-stale {{ color: var(--amber); font-weight:600; margin-left:6px; white-space:nowrap; }}
.tc-list-meta {{ line-height:1.5; }}
/* a tooltip must never keep itself open by catching the pointer */
[data-baseweb="tooltip"], [data-baseweb="popover"]:has([role="tooltip"]) {{ pointer-events:none !important; }}
@media (max-width: 640px) {{
  .st-key-tc-nav [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; gap: 4px; }}
  .st-key-tc-nav [data-testid="stColumn"] {{ min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }}
  [class*="st-key-tc-nav-"] button {{ padding: 6px 4px !important; justify-content:center; }}
}}

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


def step_nav(steps: list[str], current: int, done: set[int], locked: dict[int, str]) -> int | None:
    """Clickable step pills. Current step: gradient border; finished: ✓; locked: 🔒, dashed and dimmed,
    and a toast explains the unlock condition when clicked. Returns the index clicked (locked included, so the caller
    can explain why they are locked)."""
    styles = []
    for i in range(len(steps)):
        sel = f".st-key-tc-nav-{i} button"
        if i == current:
            styles.append(f"{sel} {{ color:var(--ink-100) !important; border-color:transparent !important;"
                          "background:linear-gradient(var(--navy-800),var(--navy-800)) padding-box,"
                          "linear-gradient(90deg,var(--coral),var(--amber),var(--teal)) border-box !important; }")
        elif i in locked:
            styles.append(f"{sel} {{ opacity:.4; border-style:dashed !important; cursor:not-allowed !important;"
                          "background:transparent !important; }")
        elif i in done:
            styles.append(f"{sel} {{ color:var(--teal) !important; border-color:rgba(53,190,187,.45) !important; }}")
    # Phones: one compact row — the current step keeps its name, the others show only ✓ / number / 🔒.
    mobile = []
    for i in range(len(steps)):
        if i == current:
            mobile.append(f"[data-testid='stColumn']:has(.st-key-tc-nav-{i}) {{ flex: 3 1 0 !important; }}")
            continue
        mark = "✓" if i in done and i not in locked else ("🔒" if i in locked else str(i + 1))
        mobile.append(f".st-key-tc-nav-{i} button p {{ font-size:0 !important; }}"
                      f".st-key-tc-nav-{i} button p::before {{ content:'{mark}'; font-size:12.5px; }}")
    st.html("<style>" + "".join(styles) + "@media (max-width: 640px) {" + "".join(mobile) + "}</style>")
    clicked = None
    with st.container(key="tc-nav"):
        for i, (col, name) in enumerate(zip(st.columns(len(steps)), steps, strict=True)):
            if i == current:
                mark = str(i + 1)
            elif i in locked:
                mark = "🔒"
            elif i in done:
                mark = "✓"
            else:
                mark = str(i + 1)
            if col.button(f"{mark}  {name}", key=f"tc-nav-{i}", width="stretch"):
                clicked = i
    return clicked


DRAG_SCRIPT = """
<script>
(function () {
  const doc = window.parent.document;
  if (doc.__tcDragInstalled) return;
  doc.__tcDragInstalled = true;
  const zone = (el) => el && el.closest ? el.closest('[data-testid="stFileUploaderDropzone"]') : null;
  const clear = (keep) => doc.querySelectorAll('.tc-drag').forEach((n) => { if (n !== keep) n.classList.remove('tc-drag'); });
  doc.addEventListener('dragenter', (e) => { const z = zone(e.target); clear(z); if (z) z.classList.add('tc-drag'); }, true);
  doc.addEventListener('dragleave', (e) => { const z = zone(e.target); if (z && !z.contains(e.relatedTarget)) z.classList.remove('tc-drag'); }, true);
  doc.addEventListener('drop', () => clear(null), true);
  doc.addEventListener('dragend', () => clear(null), true);
})();
</script>
"""


def install_drag_highlight() -> None:
    """Highlight a drop zone while a file is dragged over it (Streamlit exposes no CSS hook for this)."""
    import streamlit.components.v1 as components

    components.html(DRAG_SCRIPT, height=0)


def html_note(html: str, target=None) -> None:
    """A small styled note (trusted HTML built by the app)."""
    (target or st).html(html)


def disclosure(html: str, target=None) -> None:
    (target or st).html(f'<div class="tc-disclosure">{html}</div>')


def code(text: str) -> str:
    return f"<code>{escape(text)}</code>"


def footer(detail: str | None = None) -> None:
    extra = f" · {escape(detail)}" if detail else ""
    st.html(f'<div class="tc-footer">Powered by TEN Capital Network{extra}</div>')


SCROLL_TOP_SCRIPT = """
(function () {
  const doc = window.parent.document;
  const targets = () => ['[data-testid="stMain"]', '[data-testid="stAppViewContainer"]', 'section.main']
    .map((sel) => doc.querySelector(sel)).filter(Boolean);
  const go = () => { targets().forEach((el) => el.scrollTo({top: 0})); window.parent.scrollTo({top: 0}); };
  // The new step renders over the next moments; keep it at the top until it settles or the user interacts.
  const obs = new MutationObserver(go);
  const stop = () => { obs.disconnect(); ['wheel', 'touchstart', 'keydown', 'mousedown']
    .forEach((ev) => doc.removeEventListener(ev, stop, true)); };
  go();
  targets().forEach((el) => obs.observe(el, {childList: true, subtree: true}));
  ['wheel', 'touchstart', 'keydown', 'mousedown'].forEach((ev) => doc.addEventListener(ev, stop, true));
  setTimeout(stop, 6000);
})();
"""


def scroll_to_top(nonce: str) -> None:
    """Open a step at the top of the page (Streamlit otherwise keeps the previous scroll position).
    ``nonce`` must change whenever a new scroll is wanted, so the script is mounted again."""
    import streamlit.components.v1 as components

    components.html(f"<script>/* {escape(nonce)} */{SCROLL_TOP_SCRIPT}</script>", height=0)
