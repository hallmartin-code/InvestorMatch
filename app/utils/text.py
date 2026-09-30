"""Text helpers: whitespace cleanup, name/organization normalization, email syntax."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"[ \t   ]+")
_BLANKS = re.compile(r"\n{3,}")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_ORG_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|plc|gmbh|pbc|lp|llp|"
    r"holdings?|group|the)\b\.?",
    re.IGNORECASE,
)
_NAME_TITLES = re.compile(r"\b(mr|mrs|ms|dr|prof|sir|jr|sr|ii|iii|iv|md|phd|cfa|mba)\b\.?", re.IGNORECASE)

# RFC 5322 is far looser; this accepts the addresses people actually use and rejects the rest.
_EMAIL = re.compile(
    r"^(?=.{3,254}$)(?=[^@]{1,64}@)"
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
_EMPTY_TOKENS = {"", "nan", "none", "null", "n/a", "na", "-", "--", "#n/a", "tbd", "unknown", "?"}


def normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    lines = [_WS.sub(" ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def clean_cell(value: object) -> str:
    """Spreadsheet cell → trimmed text; blanks and placeholders become ''."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        if value.is_integer():
            value = int(value)
    text = _WS.sub(" ", str(value)).strip()
    return "" if text.lower() in _EMPTY_TOKENS else text


def truncate(text: str | None, limit: int, ellipsis: str = "…") -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - len(ellipsis)].rstrip()
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(",;:—- ") + ellipsis


def fold(text: str) -> str:
    """Accent-free lower-case ASCII."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()


def normalize_org(name: str | None) -> str:
    text = fold(name or "").replace("&", " and ")
    text = _ORG_SUFFIX.sub(" ", text)
    return _NON_ALNUM.sub(" ", text).strip()


def normalize_person(name: str | None) -> str:
    text = fold(name or "")
    if "," in text:  # "Last, First"
        last, _, first = text.partition(",")
        text = f"{first} {last}"
    text = _NAME_TITLES.sub(" ", text)
    return _NON_ALNUM.sub(" ", text).strip()


def normalize_email(email: str | None) -> str:
    text = (email or "").strip().strip("<>").strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    return text.lower()


def is_valid_email(email: str | None) -> bool:
    """Syntax only. A syntactically valid address may still be undeliverable."""
    return bool(email) and bool(_EMAIL.match(email.strip()))


def email_local_part(email: str) -> str:
    return email.split("@", 1)[0].lower()


def split_name(full: str) -> tuple[str, str]:
    full = (full or "").strip()
    if "," in full:
        last, _, first = full.partition(",")
        return first.strip(), last.strip()
    parts = full.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def split_list(value: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"\s*[,;|\n•/]\s*", value or "") if p.strip()]


def sanitize_filename(name: str, max_length: int = 100) -> str:
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = _UNSAFE_FILENAME.sub("_", base).strip("._") or "file"
    return base[:max_length]


def slugify(text: str, max_length: int = 50) -> str:
    return (_NON_ALNUM.sub("_", fold(text)).strip("_") or "company")[:max_length]


def is_truthy(value: str | None) -> bool | None:
    """Yes/No style cell → True/False; None when blank or unrecognized."""
    text = fold(value or "").strip()
    if not text:
        return None
    if text in {"y", "yes", "true", "1", "x", "core", "active", "member", "✓", "checked"}:
        return True
    if text in {"n", "no", "false", "0", "none", "inactive"}:
        return False
    return None
