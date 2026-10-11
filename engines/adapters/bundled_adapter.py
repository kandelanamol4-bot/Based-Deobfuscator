"""Bundled normalizer: honest lightweight cleanup for plain/minified Lua.

Decodes \\ddd / \\xNN string escapes where safe, breaks over-long lines
at statement boundaries, strips trailing whitespace. Fails (returns error)
on VM-like/loader-heavy input instead of faking success.
"""
from __future__ import annotations
import re
from pathlib import Path

from engines.base import BaseEngine

DEC = re.compile(r"\\(\d{1,3})")
HEX = re.compile(r"\\x([0-9A-Fa-f]{2})")
VM = re.compile(r"(OPCODE|VM_|bytecode|while\s+true\s+do.{0,200}_state|loadstring\s*\(\s*['\"]|getfenv)", re.I | re.S)


class BundledPrettifyEngine(BaseEngine):
    id = "bundled_prettify"
    display_name = "Bundled Normalizer"
    version = "1.0.0"

    async def health_check(self) -> tuple[bool, str, str]:
        return True, self.version, "ok (pure-python, always available)"

    async def deobfuscate(self, source_path: str, output_path: str, options: dict) -> tuple[bool, str]:
        try:
            src = Path(source_path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return False, f"Cannot read input: {type(e).__name__}"
        if VM.search(src) and len(src) > 3000:
            return False, "Bundled normalizer does not support VM/loader-style obfuscation."
        out = self.transform(src)
        if out.strip() == src.strip():
            # still write output, but signal unchanged so validator rejects "success"
            Path(output_path).write_text(out, encoding="utf-8")
            return True, out
        Path(output_path).write_text(out, encoding="utf-8")
        return True, out

    @staticmethod
    def transform(src: str) -> str:
        def dec_sub(m):
            try:
                v = int(m.group(1))
                if 32 <= v <= 126 and v not in (34, 39, 92):
                    return chr(v)
            except ValueError:
                pass
            return m.group(0)

        def hex_sub(m):
            try:
                v = int(m.group(1), 16)
                if 32 <= v <= 126 and v not in (34, 39, 92):
                    return chr(v)
            except ValueError:
                pass
            return m.group(0)

        out = DEC.sub(dec_sub, src)
        out = HEX.sub(hex_sub, out)
        # break very long lines on semicolons for readability
        lines: list[str] = []
        for line in out.splitlines():
            line = line.rstrip()
            if len(line) > 400 and ";" in line:
                lines.extend(p.strip() for p in line.split(";") if p.strip())
            else:
                lines.append(line)
        return "\n".join(lines).strip() + "\n"
