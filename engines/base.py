"""Base engine interface. All adapters must implement this."""
from __future__ import annotations
from abc import ABC, abstractmethod


class BaseEngine(ABC):
    id = "base"
    display_name = "Base"
    version = "unknown"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    async def health_check(self) -> tuple[bool, str, str]:
        """Return (available, version, message)."""

    @abstractmethod
    async def deobfuscate(self, source_path: str, output_path: str, options: dict) -> tuple[bool, str]:
        """Read source_path, write output_path. Return (ok, output_text_or_error). Never return input as success unchanged."""
