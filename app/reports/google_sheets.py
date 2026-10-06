"""Google Sheets export (same sheets as the Excel workbook), using a configured service account.

Values are written with valueInputOption=RAW, so nothing is parsed as a formula. Sharing (optional)
uses notify=False: this app never sends email or contacts investors.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.errors import ExportUnavailableError
from app.models import RunResult
from app.reports.frames import build_sheets

ENABLE_INSTRUCTIONS = (
    "Google Sheets export is not configured. To enable it: (1) in Google Cloud, create a service account and "
    "enable the Google Sheets and Google Drive APIs; (2) download its JSON key and store it outside the "
    "project (never commit it); (3) set IM_GOOGLE_SERVICE_ACCOUNT_FILE (or GOOGLE_APPLICATION_CREDENTIALS) to "
    "that path in .env — or, on a hosted deployment such as Railway, put the key's JSON content in the secret "
    "variable IM_GOOGLE_SERVICE_ACCOUNT_JSON; (4) optionally set IM_GOOGLE_DRIVE_FOLDER_ID to a folder shared with the service "
    "account, and IM_GOOGLE_SHARE_WITH to the addresses that should get access. The PDF and Excel exports "
    "are complete without it."
)


def rowcol_to_a1(row: int, col: int) -> str:
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def _grid(sheet) -> list[list[Any]]:
    rows = [sheet.columns] + [[("" if v is None else v) for v in row] for row in sheet.rows]
    for title, cols, block in sheet.extra_blocks:
        rows += [[], [title], cols] + [list(r) for r in block]
    width = max(len(r) for r in rows)
    return [list(r) + [""] * (width - len(r)) for r in rows]


def client_from_settings(settings: Settings):
    """Key content (IM_GOOGLE_SERVICE_ACCOUNT_JSON, hosted) takes precedence over a key file (local)."""
    info, path = settings.google_credentials_info, settings.google_credentials_file
    if info is None and path is None:
        raise ExportUnavailableError(ENABLE_INSTRUCTIONS)
    try:
        import gspread
    except ImportError as exc:
        raise ExportUnavailableError("Install the 'gspread' package (pip install -r requirements.txt). "
                                     + ENABLE_INSTRUCTIONS) from exc
    return gspread.service_account_from_dict(info) if info else gspread.service_account(filename=str(path))


def export_to_google_sheets(result: RunResult, settings: Settings, title: str, client: Any = None) -> str:
    """Create a spreadsheet and return its URL. ``client`` is injectable for tests."""
    client = client or client_from_settings(settings)
    try:
        spreadsheet = client.create(title, folder_id=settings.im_google_drive_folder_id or None)
        sheets = build_sheets(result)
        first = spreadsheet.sheet1
        for index, sheet in enumerate(sheets):
            grid = _grid(sheet)
            if index == 0:
                ws = first
                ws.update_title(sheet.name)
                ws.resize(rows=max(len(grid), 2), cols=len(grid[0]))
            else:
                ws = spreadsheet.add_worksheet(title=sheet.name, rows=max(len(grid), 2), cols=len(grid[0]))
            ws.update(grid, "A1", value_input_option="RAW")
            ws.freeze(rows=1)
            ws.set_basic_filter(f"A1:{rowcol_to_a1(len(sheet.rows) + 1, len(sheet.columns))}")
            ws.format(f"A1:{rowcol_to_a1(1, len(sheet.columns))}", {"textFormat": {"bold": True}})
        for address in [a.strip() for a in settings.im_google_share_with.split(",") if a.strip()]:
            spreadsheet.share(address, perm_type="user", role="writer", notify=False)
    except ExportUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - gspread/google-auth raise many types
        if "storage quota" in str(exc).lower():
            raise ExportUnavailableError(
                "Google Sheets export failed: the service account has no Drive storage of its own, so it cannot "
                "create sheets in a My Drive folder. Set IM_GOOGLE_DRIVE_FOLDER_ID to a folder in a Shared Drive "
                "where the service account is a Content manager. The PDF and Excel exports are unaffected.") from exc
        raise ExportUnavailableError(f"Google Sheets export failed ({exc.__class__.__name__}: {exc}). "
                                     "The PDF and Excel exports are unaffected.") from exc
    return spreadsheet.url
