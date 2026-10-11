"""Engine selection: score available engines, auto-pick or ask user."""
from __future__ import annotations
from .analyzer import AnalysisReport
from .detector import score_engine
from .engine_registry import EngineRegistry


def rank_engines(registry: EngineRegistry, report: AnalysisReport) -> list[tuple[str, float, str]]:
    ranked = []
    for info in registry.available_engines():
        if not info.enabled:
            continue
        caps = {"obfuscator_families": info.families, "kind": info.kind}
        s, reason = score_engine(caps, report)
        ranked.append((info.id, s, reason))
    return sorted(ranked, key=lambda r: r[1], reverse=True)


def auto_select(registry: EngineRegistry, report: AnalysisReport, threshold: float) -> tuple[str | None, list]:
    ranked = rank_engines(registry, report)
    if not ranked:
        return None, []
    best_id, best_score, _ = ranked[0]
    if best_score >= threshold:
        return best_id, ranked
    return None, ranked
