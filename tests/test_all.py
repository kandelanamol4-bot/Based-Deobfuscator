"""Tests: analyzer, validation, security, registry/selector, runner, queue."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.analyzer import analyze_source
from core.detector import score_engine
from core.engine_selector import rank_engines, auto_select
from core.job_manager import JobManager, JobStatus
from core.output_validator import validate_output
from core.queue_manager import QueueManager
from core.security import is_safe_http_url, sanitize_filename
from core.input_handler import sniff_text, validate_raw_code
from engines.adapters.bundled_adapter import BundledPrettifyEngine
from workers.runner import run_engine
from ui.formatting import code_preview, fmt_size


def read_fx(name):
    return (ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")


def test_plain_detected_clean():
    r = analyze_source(read_fx("plain.lua"))
    assert r.language == "lua"
    assert any(f["key"] in ("clean", "unknown") for f in r.findings)


def test_encoded_detected():
    r = analyze_source(read_fx("encoded.lua"))
    assert r.confidence_for("string-encoding") > 0 or r.confidence_for("renamed-identifiers") > 0


def test_controlflow_detected():
    r = analyze_source(read_fx("controlflow.lua"))
    assert r.confidence_for("control-flow") >= 0.4


def test_vm_detected():
    r = analyze_source(read_fx("vm.lua"))
    assert r.confidence_for("virtualized") >= 0.4


def test_validation_rejects_identical():
    src = "local x = 1\n"
    v = validate_output(src, src, 10_000)
    assert not v.ok and "identical" in v.message.lower()


def test_validation_rejects_empty():
    v = validate_output("local x=1", "   ", 10_000)
    assert not v.ok


def test_validation_accepts_real_change():
    v = validate_output("local x=1", "local y = 2\nreturn y\n", 10_000)
    assert v.ok


def test_validation_accepts_minimal_valid_output():
    # real case: 170KB Luraph VM wrapper around print("hello") lifts to this
    big_vm = "x" * 5000 + " while true do end"
    v = validate_output(big_vm, 'print("hello")\n', 10_000)
    assert v.ok


def test_validation_still_rejects_garbage():
    v = validate_output("local x = 1", "asdf qwer !!! ???", 10_000)
    assert not v.ok


def test_ssrf_rejects_private():
    for u in ["http://localhost/x.lua", "http://127.0.0.1/a.lua", "http://169.254.169.254/",
              "http://[::1]/x.lua", "ftp://example.com/x.lua", "http://example.com/x.lua"]:
        if u.startswith("http://"):
            ok, _ = is_safe_http_url(u)
            assert not ok, u
    ok, _ = is_safe_http_url("https://raw.githubusercontent.com/o/r/main/a.lua")
    assert ok


def test_sniff_rejects_html_and_binary():
    t, _ = sniff_text(b"<html><body>hi</body></html>", 10000)
    assert t is None
    t, _ = sniff_text(b"\x00\x01\x02bin", 10000)
    assert t is None
    t, _ = sniff_text(b"local x=1", 5)
    assert t is None


def test_raw_code_limit_message():
    t, msg = validate_raw_code("x" * 7000, 6000, 10_000_000)
    assert t is None and "file" in msg.lower()


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd.lua" or "passwd" in sanitize_filename("../../etc/passwd")
    assert len(sanitize_filename("a" * 200)) <= 100


class FakeEngine:
    version = "fake-1"
    def __init__(self, succeed=True):
        self.succeed = succeed
    async def health_check(self):
        return True, "fake-1", "ok"
    async def deobfuscate(self, src, out, opts):
        if not self.succeed:
            return False, "boom"
        Path(out).write_text("local clean = 1\nreturn clean\n", encoding="utf-8")
        return True, "local clean = 1\nreturn clean\n"


class FakeRegistry:
    def __init__(self, engines):
        self._e = engines
    def available_engines(self):
        return self._e


def _info(eid, fams, kind="bundled"):
    from core.engine_registry import EngineInfo
    return EngineInfo(id=eid, display_name=eid, description="", kind=kind, enabled=True,
                      timeout=10, supports_auto=True, lua_versions=[], families=fams,
                      available=True, instance=FakeEngine())


def test_ranking_prefers_matching_engine():
    reg = FakeRegistry([_info("a", ["plain"]), _info("b", ["decimal-string-escape"])])
    r = analyze_source(read_fx("encoded.lua"))
    ranked = rank_engines(reg, r)
    assert ranked[0][0] == "b"


def test_auto_select_threshold():
    reg = FakeRegistry([_info("a", ["plain"])])
    r = analyze_source(read_fx("vm.lua"))
    eid, _ = auto_select(reg, r, 0.95)
    assert eid is None  # honest: no strong match -> ask user


@pytest.mark.asyncio
async def test_runner_success_and_timeout():
    eng = FakeEngine(True)
    ok, payload, el, _ = await run_engine(eng, "local x=1", 10, "BD-TEST")
    assert ok and "clean" in payload

    class Slow:
        version = "s"
        async def deobfuscate(self, s, o, opts):
            await asyncio.sleep(5)
            return True, "x"
    ok, msg, _, _ = await run_engine(Slow(), "x", 1, "BD-TEST")
    assert not ok and "timed out" in msg.lower()


@pytest.mark.asyncio
async def test_bundled_decodes_decimal_escapes():
    eng = BundledPrettifyEngine({})
    ok, ver, msg = await eng.health_check()
    assert ok
    import tempfile
    d = tempfile.mkdtemp()
    src = Path(d) / "i.lua"
    out = Path(d) / "o.lua"
    src.write_text('local s = "\\72\\101\\108\\108\\111"\nprint(s)\n', encoding="utf-8")
    ok, text = await eng.deobfuscate(str(src), str(out), {})
    assert ok and "Hello" in text


@pytest.mark.asyncio
async def test_job_states_and_cancel():
    jm = JobManager()
    j = await jm.create(123, "a.lua", 10)
    assert j.status == JobStatus.PENDING
    await jm.update(j, status=JobStatus.RUNNING)
    assert (await jm.get(j.id)).status == JobStatus.RUNNING
    j.cancelled.set()
    assert j.cancelled.is_set()


@pytest.mark.asyncio
async def test_queue_concurrency():
    q = QueueManager(1)
    order = []

    async def worker(n):
        await q.acquire()
        order.append(f"start{n}")
        await asyncio.sleep(0.05)
        order.append(f"end{n}")
        q.release()
    await asyncio.gather(worker(1), worker(2))
    assert order == ["start1", "end1", "start2", "end2"]


def test_preview_truncation():
    text = "\n".join(f"line {i}" for i in range(100))
    block, trunc = code_preview(text, 40, 1500)
    assert trunc and len(block.splitlines()) <= 40
    assert fmt_size(142800).startswith("139")
