"""Engine registry: loads engines.yaml, instantiates adapters, health-checks."""
from __future__ import annotations
import importlib
import logging
from dataclasses import dataclass, field

log = logging.getLogger("based.registry")


@dataclass
class EngineInfo:
    id: str
    display_name: str
    description: str
    kind: str
    enabled: bool
    timeout: int
    supports_auto: bool
    lua_versions: list
    families: list
    available: bool = False
    version: str = "unknown"
    last_health: str = "not checked"
    instance: object = None


class EngineRegistry:
    def __init__(self):
        self.engines: dict[str, EngineInfo] = {}

    def load(self, configs: list[dict]):
        for cfg in configs:
            if not cfg.get("enabled", True):
                continue
            mod_path, _, cls_name = str(cfg.get("module", "")).partition(":")
            if not mod_path or not cls_name:
                log.warning("Engine %s has bad module ref; skipped", cfg.get("id"))
                continue
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                inst = cls(cfg)
                info = EngineInfo(
                    id=cfg.get("id", cls_name),
                    display_name=cfg.get("display_name", cls_name),
                    description=cfg.get("description", ""),
                    kind=cfg.get("kind", "external"),
                    enabled=True,
                    timeout=int(cfg.get("timeout_seconds", 90)),
                    supports_auto=bool(cfg.get("supports_auto_detect", True)),
                    lua_versions=list(cfg.get("lua_versions", [])),
                    families=list(cfg.get("obfuscator_families", [])),
                    instance=inst,
                )
                self.engines[info.id] = info
            except Exception as e:
                log.warning("Could not load engine %s: %s", cfg.get("id"), e)

    async def health_check_all(self):
        for info in self.engines.values():
            try:
                ok, ver, msg = await info.instance.health_check()  # type: ignore
                info.available = bool(ok)
                info.version = ver or "unknown"
                info.last_health = msg
            except Exception as e:
                info.available = False
                info.last_health = f"health check error: {type(e).__name__}"

    def available_engines(self) -> list[EngineInfo]:
        return [e for e in self.engines.values() if e.available]

    def get(self, engine_id: str) -> EngineInfo | None:
        return self.engines.get(engine_id)

    def set_enabled(self, engine_id: str, enabled: bool) -> bool:
        info = self.engines.get(engine_id)
        if not info:
            return False
        info.enabled = enabled
        if not enabled:
            info.available = False
        return True
