"""Compatibility scoring between analysis report and engine capabilities."""
from __future__ import annotations
from .analyzer import AnalysisReport

# Which finding keys each generic engine family can plausibly handle.
FAMILY_HANDLES: dict[str, set[str]] = {
    "plain": {"clean", "unknown"},
    "minified": {"clean", "renamed-identifiers", "unknown"},
    "simple-hex-rename": {"renamed-identifiers", "unknown"},
    "decimal-string-escape": {"string-encoding", "renamed-identifiers", "unknown"},
    "luraph-v15": {"virtualized", "loader", "string-encoding", "control-flow",
                   "arithmetic-encode", "embedded-blob", "wrapper", "unknown"},
    "luraph-v14": {"virtualized", "loader", "string-encoding", "control-flow",
                   "arithmetic-encode", "embedded-blob", "unknown"},
}


def score_engine(engine_caps: dict, report: AnalysisReport) -> tuple[float, str]:
    """Return (score 0..1, reason). Honest: low scores when evidence is weak."""
    fams = set(engine_caps.get("obfuscator_families", []) or [])
    if not report.findings:
        return 0.0, "No analysis findings."
    top = report.findings[0]
    key = top["key"]
    conf = float(top["confidence"])
    handled: set[str] = set()
    for f in fams:
        handled |= FAMILY_HANDLES.get(f, set())
    # Local/custom engine: unknown capability -> medium score, flagged as generic
    if engine_caps.get("kind") == "local":
        if key in ("virtualized",):
            return 0.35, f"Local engine may handle '{top['label']}' but VM code is often unsupported."
        return 0.6, f"Local engine selected generically (top signal: {top['label']})."
    if key in handled:
        return min(0.55 + conf * 0.4, 0.95), f"Matches '{top['label']}' (confidence {conf:.0%})."
    if key in ("virtualized", "loader"):
        return 0.15, f"'{top['label']}' is likely unsupported by lightweight engines."
    if key == "clean":
        return 0.8, "Source looks nearly clean; bundled normalizer is sufficient."
    return 0.3, f"Weak match for '{top['label']}'."
