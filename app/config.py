"""Runtime settings (environment) and scoring configuration (TOML).

Secrets come only from environment variables or a local ``.env``. Scoring numbers come from
``config/scoring.toml`` so they are reviewable and fingerprinted into every run.
"""

from __future__ import annotations

import hashlib
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
ASSET_DIR = APP_DIR / "assets"
FONT_DIR = ASSET_DIR / "fonts"
LOGO_PATH = ASSET_DIR / "TEN_Capital_logo_footer.png"
STATIC_DIR = APP_DIR / "static"
FAVICON_PATH = STATIC_DIR / "favicon.png"  # browser tab icon (st.set_page_config page_icon) and header mark
DEFAULT_CONFIG_PATH = ROOT / "config" / "scoring.toml"
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Optional default TEN Capital Investor List (used when no list is uploaded).
    im_investor_list_path: Path | None = None
    # Trusted folder of built-in investor lists offered in the app (their unsubscribe sheets always apply).
    im_investor_lists_dir: Path = DATA_DIR / "investor_lists"
    im_config_path: Path = DEFAULT_CONFIG_PATH
    im_log_level: str = "INFO"

    # Claude deck analysis: on whenever ANTHROPIC_API_KEY is set (deck text is sent to the API).
    im_llm_enabled: bool = True
    anthropic_api_key: SecretStr | None = None
    im_llm_model: str = "claude-opus-5-5"

    # Access password for the web app (set it on any public deployment).
    ten_app_password: SecretStr | None = None

    # Automated results email via Resend: on whenever RESEND_API_KEY is set.
    resend_api_key: SecretStr | None = None
    im_notify_enabled: bool = True
    im_notify_to: str = "Info@tencapital.group"
    im_notify_from: str = "TEN Capital Investor Match <reports@tencapital.group>"
    im_notify_reply_to: str = ""
    im_notify_subject_prefix: str = "[TEN Capital]"
    im_notify_timeout_seconds: float = 30.0
    im_public_url: str = ""                 # link in the email; defaults to the Railway public domain
    railway_public_domain: str = ""

    def notify_recipients(self) -> list[str]:
        return [p.strip() for p in self.im_notify_to.replace(";", ",").split(",") if p.strip()]

    @property
    def notify_available(self) -> bool:
        return bool(self.im_notify_enabled and self.resend_api_key and self.resend_api_key.get_secret_value().strip()
                    and self.notify_recipients())

    @property
    def public_url(self) -> str | None:
        if self.im_public_url:
            return self.im_public_url
        return f"https://{self.railway_public_domain}" if self.railway_public_domain else None

    # Optional Google Sheets export (service account JSON file; never commit it).
    im_google_service_account_file: Path | None = None
    google_application_credentials: Path | None = None
    im_google_share_with: str = ""          # comma-separated addresses; shared without notification email
    im_google_drive_folder_id: str = ""

    @property
    def llm_available(self) -> bool:
        return bool(self.im_llm_enabled and self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

    @property
    def google_credentials_file(self) -> Path | None:
        for candidate in (self.im_google_service_account_file, self.google_application_credentials):
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    def builtin_investor_lists(self) -> list[Path]:
        """Trusted, built-in investor lists (``data/investor_lists/`` or IM_INVESTOR_LISTS_DIR), newest first."""
        folder = Path(self.im_investor_lists_dir)
        if not folder.is_dir():
            return []
        files = [p for p in folder.iterdir() if p.suffix.lower() in {".xlsx", ".xls", ".csv"}
                 and not p.name.startswith("~$")]
        return sorted(files, key=lambda p: (-p.stat().st_mtime, p.name))

    def default_investor_list(self) -> Path | None:
        """IM_INVESTOR_LIST_PATH, else the newest built-in list, else ``data/TEN*Investor*List*``."""
        if self.im_investor_list_path and Path(self.im_investor_list_path).is_file():
            return Path(self.im_investor_list_path)
        builtin = self.builtin_investor_lists()
        if builtin:
            return builtin[0]
        if DATA_DIR.is_dir():
            for pattern in ("TEN*Investor*List*.xlsx", "TEN*Investor*List*.csv", "TEN*Investor*List*.xls"):
                found = sorted(DATA_DIR.glob(pattern))
                if found:
                    return found[0]
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_CONFIG_PATH)
    raw = path.read_bytes()
    config = tomllib.loads(raw.decode("utf-8"))
    weights = config["weights"]
    total = round(sum(weights.values()), 6)
    if total != 1.0:
        raise ValueError(f"Scoring weights in {path.name} must sum to 1.0 (got {total}).")
    config["_fingerprint"] = hashlib.sha256(raw).hexdigest()[:12]
    return config
