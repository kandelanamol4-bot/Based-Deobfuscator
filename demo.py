"""End-to-end demo without Discord: analyze fixtures, run bundled engine, validate."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.analyzer import analyze_source
from core.engine_selector import rank_engines
from core.engine_registry import EngineRegistry
from core.output_validator import validate_output
from config import load_engine_configs
from workers.runner import run_engine


async def main():
    reg = EngineRegistry()
    reg.load(load_engine_configs(ROOT / "engines.yaml"))
    await reg.health_check_all()
    print("Engines:", {e: (i.available, i.last_health) for e, i in reg.engines.items()})
    for fx in sorted((ROOT / "tests" / "fixtures").glob("*.lua")):
        src = fx.read_text(encoding="utf-8")
        rep = analyze_source(src)
        ranked = rank_engines(reg, rep)
        print(f"\n== {fx.name} == lang={rep.language} lines={rep.lines} entropy={rep.entropy}")
        for f in rep.findings[:3]:
            print(f"  - {f['label']} ({f['confidence']:.0%}): {f['evidence']}")
        print("  ranked:", [(e, round(s, 2)) for e, s, _ in ranked])
        avail = [e for e in ranked if reg.get(e[0]).available]
        if avail:
            info = reg.get(avail[0][0])
            ok, payload, el, _ = await run_engine(info.instance, src, info.timeout, "BD-DEMO")
            print(f"  engine={info.id} ok={ok} time={el:.2f}s")
            if ok:
                v = validate_output(src, payload, 8 * 1024 * 1024)
                print(f"  validation: ok={v.ok} — {v.message}")
                print("  output head:", payload[:200].replace("\n", "\\n"))
            else:
                print("  engine error:", payload[:200])


if __name__ == "__main__":
    asyncio.run(main())
