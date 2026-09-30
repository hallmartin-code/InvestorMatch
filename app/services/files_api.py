"""Anthropic Files API: keep the built-in TEN Capital investor lists available to Claude by file ID.

Each list in the trusted folder (``data/investor_lists/``) is uploaded once; its ``file_id`` is recorded
in ``data/investor_lists/files_api.json`` keyed by file name and SHA-256, so an unchanged file is never
re-uploaded and a changed one gets a new upload. File IDs are not secrets (they are only usable with the
same organization's API key), so the registry is deployed with the lists.

Uploaded files cannot be downloaded back through the API, so the app keeps matching on its local copy;
the file IDs let Claude open the same list inside its code-execution sandbox (see ``claude_review``).

    python -m app.services.files_api            # upload new/changed built-in lists, print the registry
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.errors import LLMUnavailableError
from app.utils.logging import get_logger

LOGGER = get_logger(__name__)
REGISTRY_NAME = "files_api.json"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME = {".xlsx": XLSX_MIME, ".xls": "application/vnd.ms-excel", ".csv": "text/csv"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def registry_path(settings: Settings | None = None) -> Path:
    return Path((settings or get_settings()).im_investor_lists_dir) / REGISTRY_NAME


def load_registry(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    path = registry_path(settings)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Files API registry unreadable; treating as empty")
        return {}


def file_id_for(path: Path, settings: Settings | None = None) -> str | None:
    """The Files API ID of this exact file version, or None if it has not been uploaded."""
    entry = load_registry(settings).get(Path(path).name)
    if entry and entry.get("sha256") == _sha256(path):
        return entry.get("file_id")
    return None


def _client(settings: Settings):
    if not (settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value()):
        raise LLMUnavailableError("ANTHROPIC_API_KEY is not set; cannot use the Files API.")
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value(), timeout=600.0)


def sync_builtin_lists(settings: Settings | None = None, client: Any = None) -> dict[str, dict[str, Any]]:
    """Upload built-in lists that are new or changed; drop registry entries for files no longer present."""
    settings = settings or get_settings()
    client = client or _client(settings)
    registry = load_registry(settings)
    present = {p.name: p for p in settings.builtin_investor_lists()}
    for name, path in present.items():
        sha = _sha256(path)
        entry = registry.get(name)
        if entry and entry.get("sha256") == sha:
            try:
                client.files.retrieve_metadata(entry["file_id"])
                continue                                   # still stored at Anthropic: reuse
            except Exception:  # noqa: BLE001 - deleted or unknown ID: upload again
                LOGGER.info("Files API ID for %s is no longer valid; re-uploading", name)
        mime = MIME.get(path.suffix.lower(), "application/octet-stream")
        with path.open("rb") as handle:
            uploaded = client.files.upload(file=(name, handle, mime))
        registry[name] = {"file_id": uploaded.id, "sha256": sha, "size_bytes": path.stat().st_size,
                          "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds")}
        LOGGER.info("Uploaded %s to the Files API", name)
    for stale in set(registry) - set(present):
        registry.pop(stale)
    path = registry_path(settings)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
    return registry


if __name__ == "__main__":
    for name, entry in sync_builtin_lists().items():
        print(f"{entry['file_id']}  {name}  ({entry['size_bytes'] / 1e6:.1f} MB, uploaded {entry['uploaded_at']})")
