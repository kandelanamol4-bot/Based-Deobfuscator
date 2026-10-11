"""Configurable local CLI engine adapter (for user's desktop tool).

The tool is NOT assumed to exist. Configure exe_path etc. in engines.yaml.
Supports argv templates with {exe}, {input}, {output} placeholders.
Uses subprocess arg arrays (no shell). Captures sanitized errors.
"""
from __future__ import annotations
import asyncio
import shlex
from pathlib import Path

from .base import BaseEngine


class LocalCLIEngine(BaseEngine):
    id = "local_desktop"
    display_name = "Local Engine"

    def _build_argv(self, src: str, out: str) -> list[str] | None:
        cfg = self.config
        exe = str(cfg.get("exe_path", "")).strip().strip('"')
        if not exe:
            return None
        template = cfg.get("input_template")
        if template:
            argv = []
            for tok in template:
                tok = tok.replace("{exe}", exe).replace("{input}", src).replace("{output}", out)
                argv.append(tok)
            return argv
        argv = [exe]
        iarg = str(cfg.get("input_arg", "")).strip()
        oarg = str(cfg.get("output_arg", "")).strip()
        for a in list(cfg.get("extra_args", []) or []):
            argv.append(str(a).replace("{input}", src).replace("{output}", out))
        if iarg and iarg != "{input}":
            argv += [iarg, src]
        elif iarg == "{input}":
            argv.append(src)
        else:
            argv.append(src)
        if oarg and oarg != "{output}":
            argv += [oarg, out]
        elif oarg == "{output}":
            argv.append(out)
        return argv

    async def health_check(self) -> tuple[bool, str, str]:
        exe = str(self.config.get("exe_path", "")).strip().strip('"')
        if not exe:
            return False, "unconfigured", "exe_path is not configured — see engines.yaml."
        if not Path(exe).exists():
            return False, "missing", f"Executable not found: {exe}"
        args = list(self.config.get("health_check_args", ["--version"]) or ["--version"])
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.config.get("working_dir") or None),
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                return False, "unknown", "Health check timed out."
            text = (stdout or b"").decode("utf-8", errors="replace")[:500]
            ok = proc.returncode == 0
            ver = text.strip().splitlines()[0] if text.strip() else "unknown"
            return ok, ver[:100], ("ok: " + ver[:200]) if ok else ("non-zero exit: " + ver[:200])
        except Exception as e:
            return False, "unknown", f"Cannot launch executable: {type(e).__name__}"

    async def deobfuscate(self, source_path: str, output_path: str, options: dict) -> tuple[bool, str]:
        argv = self._build_argv(source_path, output_path)
        if not argv:
            return False, "Local engine is not configured (exe_path missing)."
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.config.get("working_dir") or None),
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=float(options.get("timeout", 90)))
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False, "Local engine timed out."
            if proc.returncode != 0:
                err = (stdout or b"").decode("utf-8", errors="replace")[:1000]
                return False, f"Engine exited with code {proc.returncode}: {err[:500]}"
            p = Path(output_path)
            if not p.exists():
                # some tools print to stdout instead
                text = (stdout or b"").decode("utf-8", errors="replace")
                if text.strip():
                    p.write_text(text, encoding="utf-8")
                else:
                    return False, "Engine produced no output file."
            return True, p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return False, f"Failed to launch local engine: {type(e).__name__}"
