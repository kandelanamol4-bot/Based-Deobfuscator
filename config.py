"""Central configuration: .env secrets + engines.yaml engine definitions."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _getenv_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _getenv_bool(name: str, default: bool) -> bool:
    val = os.getenv(name, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")


@dataclass
class Settings:
    token: str = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""))
    guild_id: int | None = None
    admin_user_ids: set[int] = field(default_factory=set)
    max_input_mb: float = 5.0
    max_output_mb: float = 8.0
    max_concurrent_jobs: int = 2
    max_jobs_per_user: int = 1
    job_timeout: int = 120
    engine_timeout: int = 90
    preview_max_lines: int = 40
    preview_max_chars: int = 1500
    enable_history: bool = False
    job_retention_days: int = 7
    temp_retention_seconds: int = 60
    fallback_enabled: bool = True
    auto_select_threshold: float = 0.65
    log_level: str = "INFO"
    engines_file: Path = BASE_DIR / "engines.yaml"

    @classmethod
    def load(cls) -> "Settings":
        gid = os.getenv("DISCORD_GUILD_ID", "").strip()
        admins = set()
        for part in os.getenv("ADMIN_USER_IDS", "").replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                admins.add(int(part))
        return cls(
            token=os.getenv("DISCORD_TOKEN", ""),
            guild_id=int(gid) if gid.isdigit() else None,
            admin_user_ids=admins,
            max_input_mb=_getenv_float("MAX_INPUT_SIZE_MB", 5.0),
            max_output_mb=_getenv_float("MAX_OUTPUT_SIZE_MB", 8.0),
            max_concurrent_jobs=_getenv_int("MAX_CONCURRENT_JOBS", 2),
            max_jobs_per_user=_getenv_int("MAX_JOBS_PER_USER", 1),
            job_timeout=_getenv_int("JOB_TIMEOUT_SECONDS", 120),
            engine_timeout=_getenv_int("ENGINE_TIMEOUT_SECONDS", 90),
            preview_max_lines=_getenv_int("PREVIEW_MAX_LINES", 40),
            preview_max_chars=_getenv_int("PREVIEW_MAX_CHARS", 1500),
            enable_history=_getenv_bool("ENABLE_JOB_HISTORY", False),
            job_retention_days=_getenv_int("JOB_RETENTION_DAYS", 7),
            temp_retention_seconds=_getenv_int("TEMP_RETENTION_SECONDS", 60),
            fallback_enabled=_getenv_bool("FALLBACK_ENABLED", True),
            auto_select_threshold=_getenv_float("AUTO_SELECT_THRESHOLD", 0.65),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    @property
    def max_input_bytes(self) -> int:
        return int(self.max_input_mb * 1024 * 1024)

    @property
    def max_output_bytes(self) -> int:
        return int(self.max_output_mb * 1024 * 1024)


def load_engine_configs(path: Path | None = None) -> list[dict]:
    p = path or (Settings.load().engines_file)
    if not p.exists() or yaml is None:
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    engines = data.get("engines", [])
    return [e for e in engines if isinstance(e, dict)]


def validate_startup(settings: Settings) -> list[str]:
    """Return list of warnings (non-fatal). Caller logs them."""
    warnings: list[str] = []
    if not settings.token or settings.token == "your_bot_token_here":
        warnings.append("DISCORD_TOKEN is missing or placeholder.")
    if settings.max_input_bytes <= 0:
        warnings.append("MAX_INPUT_SIZE_MB must be > 0.")
    if settings.max_concurrent_jobs < 1:
        warnings.append("MAX_CONCURRENT_JOBS must be >= 1.")
    for ecfg in load_engine_configs(settings.engines_file):
        if ecfg.get("kind") == "local" and ecfg.get("enabled"):
            exe = str(ecfg.get("exe_path", "")).strip()
            if not exe:
                warnings.append(
                    f"Engine '{ecfg.get('id')}' has no exe_path configured — marked unavailable until configured."
                )
            elif not Path(exe).exists():
                warnings.append(f"Engine '{ecfg.get('id')}': exe_path does not exist: {exe}")
            if ecfg.get("invocation", "cli") != "cli":
                warnings.append(
                    f"Engine '{ecfg.get('id')}': only 'cli' invocation is supported; GUI-only tools cannot run headless."
                )
    return warnings
