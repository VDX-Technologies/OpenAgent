"""
VDX OpenAgent — Configuration
=========================
Settings are loaded from environment variables (via a .env file)
or fall back to sensible defaults. The Settings page in the web UI
persists changes back to `.env` and hot-reloads the API.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

load_dotenv(_ENV_PATH)


def _env(key: str, default: str = "") -> str:
    """Read an environment variable with a default."""
    return os.getenv(key, default)


@dataclass
class OllamaConfig:
    """Settings for the local Ollama LLM server."""

    base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))
    model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:7b"))
    temperature: float = field(
        default_factory=lambda: float(_env("OLLAMA_TEMPERATURE", "0.7"))
    )
    timeout: int = field(default_factory=lambda: int(_env("OLLAMA_TIMEOUT", "120")))
    # context window in tokens; 0 = pick from the Mac's RAM (Ollama's own default is too small)
    num_ctx: int = field(default_factory=lambda: int(_env("OLLAMA_NUM_CTX", "0") or 0))
    # how long Ollama keeps the model loaded after a request (its default, 5m, means slow reloads)
    keep_alive: str = field(default_factory=lambda: _env("OLLAMA_KEEP_ALIVE", "30m"))


@dataclass
class DiscordConfig:
    """Settings for the Discord bot integration."""

    token: str = field(default_factory=lambda: _env("DISCORD_BOT_TOKEN", ""))
    command_prefix: str = field(default_factory=lambda: _env("DISCORD_PREFIX", "!"))
    allowed_user_ids: list[int] = field(default_factory=lambda: [
        int(uid.strip())
        for uid in _env("DISCORD_ALLOWED_USERS", "").split(",")
        if uid.strip().isdigit()
    ])


@dataclass
class GmailConfig:
    """SMTP settings for sending email via Gmail."""

    address: str = field(default_factory=lambda: _env("GMAIL_ADDRESS", ""))
    app_password: str = field(default_factory=lambda: _env("GMAIL_APP_PASSWORD", ""))
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587


@dataclass
class WhatsAppConfig:
    """WhatsApp Business Cloud API credentials (optional)."""

    token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN", ""))
    phone_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_ID", ""))


@dataclass
class GitHubConfig:
    """GitHub personal access token (repo scope)."""

    token: str = field(default_factory=lambda: _env("GITHUB_TOKEN", ""))


@dataclass
class CodeConfig:
    """Local git repository the coding agent operates in."""

    workspace: str = field(default_factory=lambda: _env("CODE_WORKSPACE", ""))


@dataclass
class DatabaseConfig:
    """SQLite memory database settings."""

    path: str = field(
        default_factory=lambda: _env(
            "DB_PATH",
            str(_PROJECT_ROOT / "data" / "memory.db"),
        )
    )


@dataclass
class Settings:
    """Top-level settings container."""

    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    code: CodeConfig = field(default_factory=CodeConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    disabled_connectors: list[str] = field(default_factory=lambda: [
        c.strip() for c in _env("CONNECTORS_DISABLED", "").split(",") if c.strip()
    ])


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the global (cached) Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Re-read `.env` from disk and rebuild the singleton."""
    global _settings
    load_dotenv(_ENV_PATH, override=True)
    _settings = Settings()
    return _settings


def _upsert_env_key(content: str, key: str, value: str) -> str:
    """Insert or replace a KEY=value line inside an .env file body."""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(line, content)
    if content and not content.endswith("\n"):
        content += "\n"
    return content + line + "\n"


def save_settings_to_env(updates: dict[str, str]) -> Path:
    """Persist key/value pairs into the project `.env` file."""
    if _ENV_PATH.exists():
        content = _ENV_PATH.read_text(encoding="utf-8")
    else:
        example = _PROJECT_ROOT / ".env.example"
        content = example.read_text(encoding="utf-8") if example.exists() else ""

    for key, value in updates.items():
        safe = value.replace("\n", "\\n")
        content = _upsert_env_key(content, key, safe)

    _ENV_PATH.write_text(content, encoding="utf-8")
    return _ENV_PATH


def project_root() -> Path:
    """Return the absolute project root directory."""
    return _PROJECT_ROOT
