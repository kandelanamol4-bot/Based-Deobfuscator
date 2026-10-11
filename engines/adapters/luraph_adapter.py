"""Luraph v15 (+experimental v14) deobfuscator adapter.

Tool: Deobfuscator-Luraph-V15 (Node.js CLI, MIT/ISC per its repo).
Interface (from its README, verified 2026-10-11):
    node deob.js <input.lua> [-o <output.lua>] [--timeout S] [--budget S]
                            [--no-devirt] [--detect] [--debug]
    node deob.js <folder>/ --jobs N          (batch, not used here)
    exit code 0 on success; --detect prints "<file>\\t<id>\\t<conf>\\t<label>"
Requires: Node 18+, Python 3.10+ (PYTHON_BIN env if `python` is wrong),
and the bundled bin/luau-ast.exe + bin/luau.exe on Windows.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

from engines.base import BaseEngine

DEFAULT_TIMEOUT = 600


class LuraphEngine(BaseEngine):
    id = "luraph_v15"
    display_name = "Luraph Deobfuscator"
    version = "unknown"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.tool_dir = Path(str(self.config.get("tool_dir", ""))).expanduser()
        self.node_bin = str(self.config.get("node_bin", "node"))
        self.script = self.tool_dir / str(self.config.get("script", "deob.js"))
        self.version = str(self.config.get("version", "1.0.0"))

    def _env(self) -> dict:
        env = dict(os.environ)
        for k, v in dict(self.config.get("env", {}) or {}).items():
            env[str(k)] = str(v)
        env.setdefault("PYTHON_BIN", "python")
        return env

    async def health_check(self) -> tuple[bool, str, str]:
        if not self.tool_dir.is_dir():
            return False, "missing", f"tool_dir not found: {self.tool_dir}"
        if not self.script.is_file():
            return False, "missing", f"deob.js not found in {self.tool_dir}"
        for exe in ("bin/luau-ast.exe", "bin/luau.exe"):
            if not (self.tool_dir / exe).is_file():
                return False, "missing", f"Bundled binary absent: {exe}"
        try:
            proc = await asyncio.create_subprocess_exec(
                self.node_bin, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                return False, "unknown", "node --version timed out."
            if proc.returncode != 0:
                return False, "unknown", "node binary not working."
            node_ver = (out or b"").decode("utf-8", errors="replace").strip()
            return True, f"tool {self.version} / {node_ver}", f"ok ({node_ver})"
        except FileNotFoundError:
            return False, "unknown", f"node binary not found: {self.node_bin}"
        except Exception as e:
            return False, "unknown", f"health check error: {type(e).__name__}"

    async def detect(self, source_path: str) -> tuple[str, float, str]:
        """Run --detect (static, fast). Returns (family_id, confidence, label)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.node_bin, str(self.script), source_path, "--detect",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.tool_dir), env=self._env())
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            except asyncio.TimeoutError:
                proc.kill()
                return "unknown", 0.0, "detect timed out"
            text = (out or b"").decode("utf-8", errors="replace").strip()
            parts = text.split("\t")
            if len(parts) >= 3:
                try:
                    return parts[1].strip(), float(parts[2]), parts[3] if len(parts) > 3 else parts[1]
                except ValueError:
                    pass
            return "unknown", 0.0, text[:200] or "no output"
        except Exception as e:
            return "unknown", 0.0, type(e).__name__

    async def deobfuscate(self, source_path: str, output_path: str, options: dict) -> tuple[bool, str]:
        timeout = float(options.get("timeout", self.config.get("timeout_seconds", DEFAULT_TIMEOUT)))
        fast_trace = bool(options.get("fast_trace_only", False))
        argv = [self.node_bin, str(self.script), source_path, "-o", output_path,
                "--timeout", str(int(self.config.get("pass_timeout", 300))),
                "--budget", str(int(self.config.get("pass_budget", 120)))]
        if fast_trace:
            argv.append("--no-devirt")
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.tool_dir), env=self._env())
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False, f"Luraph engine timed out after {timeout:.0f}s."
            log = (out or b"").decode("utf-8", errors="replace")
            p = Path(output_path)
            if proc.returncode != 0 or not p.is_file() or p.stat().st_size == 0:
                tail = "\n".join(log.strip().splitlines()[-8:]) if log.strip() else "(no output)"
                return False, f"Engine failed (exit {proc.returncode}): {tail[:800]}"
            return True, p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return False, f"Failed to launch Luraph engine: {type(e).__name__}"
