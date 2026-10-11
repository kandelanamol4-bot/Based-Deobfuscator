"""Output validation: never claim success without evidence."""
from __future__ import annotations
import re
from dataclasses import dataclass

BALANCED = {"(": ")", "{": "}", "[": "]"}


@dataclass
class ValidationResult:
    ok: bool
    checks: dict
    message: str


def _balanced(text: str) -> bool:
    stack: list[str] = []
    in_str: str | None = None
    esc = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = ch
        elif ch in BALANCED:
            stack.append(BALANCED[ch])
        elif ch in (")", "}", "]"):
            if not stack or stack.pop() != ch:
                return False
        i += 1
    return not stack and in_str is None


def validate_output(original: str, output: str, max_bytes: int) -> ValidationResult:
    checks: dict = {}
    if not output or not output.strip():
        return ValidationResult(False, {"non_empty": False}, "Engine produced empty output.")
    checks["non_empty"] = True
    if "\x00" in output:
        return ValidationResult(False, checks, "Output is binary, not Lua text.")
    checks["is_text"] = True
    if len(output.encode("utf-8")) > max_bytes:
        checks["size_ok"] = False
        return ValidationResult(False, checks, "Output exceeds size limit.")
    checks["size_ok"] = True
    if output.strip() == original.strip():
        checks["changed"] = False
        return ValidationResult(False, checks, "Output is identical to input — deobfuscation could not be demonstrated.")
    checks["changed"] = True
    # crude syntax sanity: balanced delimiters + has some Lua structure
    checks["balanced"] = _balanced(output[:200000])
    has_code = bool(re.search(
        r"\b(local|function|end|return|if|for|while|print|require|assert|pairs|ipairs|game|script|task|tick)\b|=[^=]",
        output))
    checks["has_lua_structure"] = has_code
    if not checks["balanced"]:
        return ValidationResult(False, checks, "Output failed syntax sanity check (unbalanced delimiters).")
    if not has_code:
        return ValidationResult(False, checks, "Output lacks recognizable Lua structure (inconclusive).")
    return ValidationResult(True, checks, "Passed")
