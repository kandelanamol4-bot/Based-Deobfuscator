"""Isolated worker: runs engine with timeout, no shell, temp dirs, cleanup."""
from __future__ import annotations
import asyncio
import logging
import shutil
import tempfile
import time
from pathlib import Path

log = logging.getLogger("based.runner")


async def run_engine(engine, source_text: str, timeout: int, job_id: str) -> tuple[bool, str, float, str]:
    """Return (success, output_text_or_error, elapsed, engine_version)."""
    tmpdir = Path(tempfile.mkdtemp(prefix=f"based_{job_id.replace(':', '_')}_"))
    src = tmpdir / "input.lua"
    out = tmpdir / "output.lua"
    start = time.time()
    try:
        src.write_text(source_text, encoding="utf-8")
        result = await asyncio.wait_for(
            engine.deobfuscate(str(src), str(out), {}),
            timeout=timeout,
        )
        elapsed = time.time() - start
        # adapter returns (ok, text_or_err)
        if isinstance(result, tuple) and len(result) == 2:
            ok, payload = result
            return bool(ok), payload, elapsed, getattr(engine, "version", "unknown")
        return False, "Engine returned malformed result.", elapsed, "unknown"
    except asyncio.TimeoutError:
        return False, f"Engine timed out after {timeout}s.", time.time() - start, "unknown"
    except Exception as e:
        log.exception("engine run failed")
        return False, f"Engine error: {type(e).__name__}", time.time() - start, "unknown"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
