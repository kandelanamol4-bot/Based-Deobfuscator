"""Static Lua analysis — never executes submitted code."""
from __future__ import annotations
import math
import re
from collections import Counter
from dataclasses import dataclass, field

LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return",
    "then", "true", "until", "while",
}

HEX_IDENT = re.compile(r"\b(?:l{1,3}|I{1,3}|_+[A-Za-z0-9]+|[A-Za-z]_+[0-9A-Fa-f]{3,}|[0OIl]{6,})\b")
DEC_ESCAPE = re.compile(r"\\\d{1,3}")
HEX_ESCAPE = re.compile(r"\\x[0-9A-Fa-f]{2}|\\u\{[0-9A-Fa-f]+\}")
LONG_STRING = re.compile(r"\[\[.*?\]\]", re.S)
LOAD_CALL = re.compile(r"\b(loadstring|load)\s*\(")
GETFENV = re.compile(r"\b(getfenv|setfenv|debug\.(getupvalue|setupvalue|getregistry))\b")
BITLIB = re.compile(r"\b(bit|bit32)\.(bxor|band|bor|rshift|lshift)\b")
WHILE_TRUE = re.compile(r"while\s+true\s+do")
STATE_VAR = re.compile(r"_[A-Z]{2,}\s*=\s*\d+|_state\s*=|_CASES|switch")
VM_HINTS = re.compile(r"(OPCODE|_D_\d|VM_|bytecode|deseria|proto|const_|_ENV_epoch|LPH_ENCSTR|LPH_ENCFUNC|LPH_CRASH|LPH_NO_VIRTUALIZE)", re.I)
REQUIRE_WRAPPER = re.compile(r"function\s*\(\.\.\.\)|\(\.\.\.\)\s*;?\s*end|gethui|syn\.|Krnl|fluxus", re.I)


@dataclass
class AnalysisReport:
    language: str = "lua"
    lines: int = 0
    size_bytes: int = 0
    entropy: float = 0.0
    keyword_ratio: float = 0.0
    avg_line_len: float = 0.0
    long_lines: int = 0
    findings: list[dict] = field(default_factory=list)  # {key, label, confidence, evidence}

    def confidence_for(self, key: str) -> float:
        for f in self.findings:
            if f["key"] == key:
                return float(f["confidence"])
        return 0.0


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def detect_language(source: str) -> str:
    luau_markers = ("continue", "type ", "export type", "+=", "-=", "*=", "`{", "--!strict", "--!native")
    low = source.lower()
    if any(m.lower() in low for m in luau_markers):
        return "luau"
    return "lua"


def analyze_source(source: str) -> AnalysisReport:
    lines = source.splitlines() or [""]
    size = len(source.encode("utf-8"))
    ent = _entropy(source[:20000])
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source)
    kw = sum(1 for w in words if w in LUA_KEYWORDS)
    kw_ratio = (kw / max(len(words), 1))
    avg_len = sum(len(l) for l in lines) / max(len(lines), 1)
    long_lines = sum(1 for l in lines if len(l) > 300)

    findings: list[dict] = []

    def add(key, label, conf, evidence):
        findings.append({"key": key, "label": label, "confidence": round(min(max(conf, 0), 1), 2), "evidence": evidence})

    hex_idents = len(HEX_IDENT.findall(source))
    if hex_idents > 8:
        add("renamed-identifiers", "Likely renamed/minified identifiers", min(0.5 + hex_idents / 100, 0.9), f"{hex_idents} hex-like identifiers")
    dec_esc = len(DEC_ESCAPE.findall(source))
    hex_esc = len(HEX_ESCAPE.findall(source))
    if dec_esc + hex_esc > 5:
        add("string-encoding", "Likely string-encoding obfuscation", min(0.55 + (dec_esc + hex_esc) / 200, 0.92), f"{dec_esc} decimal escapes, {hex_esc} hex escapes")
    if len(re.findall(r"\\", source)) > 100 and (dec_esc + hex_esc) <= 20:
        add("string-encoding", "Possible string-encoding obfuscation", 0.45, "many backslashes")
    if WHILE_TRUE.search(source) and (STATE_VAR.search(source) or source.count("if ") > 15):
        add("control-flow", "Possible control-flow flattening", 0.7, "while true + state dispatch pattern")
    elif source.count("if ") > 40 and avg_len > 200:
        add("control-flow", "Possible control-flow flattening", 0.45, "dense branching, long lines")
    if VM_HINTS.search(source) or (LOAD_CALL.search(source) and len(source) > 5000 and ent > 4.5):
        add("virtualized", "Potential custom VM / bytecode interpreter", 0.65, "opcode/handler table or load() of large blob")
    if LOAD_CALL.search(source) or GETFENV.search(source):
        add("loader", "Loader/dynamic-execution wrapper detected", 0.6, "load/loadstring/getfenv usage")
    if BITLIB.search(source) and (dec_esc > 5 or ent > 4.3):
        add("arithmetic-encode", "Arithmetic/bitwise string decoding routines", 0.6, "bit32/bit ops with encoded data")
    if REQUIRE_WRAPPER.search(source):
        add("wrapper", "Executor/wrapper header", 0.4, "executor-specific globals")
    longstr = len(LONG_STRING.findall(source))
    if longstr >= 3 and ent > 4.6:
        add("embedded-blob", "Large embedded encoded constants", 0.55, f"{longstr} long-bracket blobs")
    if not findings:
        if kw_ratio > 0.08 and avg_len < 80 and ent < 4.2:
            add("clean", "No obvious obfuscation detected", 0.7, "readable identifiers, normal layout")
        else:
            add("unknown", "Unknown or mixed obfuscation", 0.4, "no strong single signature")

    return AnalysisReport(
        language=detect_language(source),
        lines=len(lines),
        size_bytes=size,
        entropy=round(ent, 3),
        keyword_ratio=round(kw_ratio, 4),
        avg_line_len=round(avg_len, 1),
        long_lines=long_lines,
        findings=sorted(findings, key=lambda f: f["confidence"], reverse=True),
    )
