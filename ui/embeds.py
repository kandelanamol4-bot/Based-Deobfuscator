"""Reusable embed templates — dark charcoal + electric-blue accent."""
from __future__ import annotations
import discord

ACCENT = 0x4F7CFF
SUCCESS = 0x2ECC71
ERROR = 0xE5484D
WARN = 0xE8A13D
FOOTER = "Based Deobfuscator"


def base(title: str, desc: str = "", color: int = ACCENT) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text=FOOTER)
    e.timestamp = discord.utils.utcnow()
    return e


def detecting(job_id: str, filename: str, size: str, lang: str) -> discord.Embed:
    e = base("Based Deobfuscator — Detecting deobfuscator")
    e.add_field(name="Status", value="Analyzing source", inline=True)
    e.add_field(name="Stage", value="Static analysis", inline=True)
    e.add_field(name="File", value=f"`{filename}`", inline=False)
    e.add_field(name="Size", value=size, inline=True)
    e.add_field(name="Language", value=lang, inline=True)
    e.add_field(name="Job ID", value=f"`{job_id}`", inline=False)
    return e


def stage_update(job_id: str, stage: str, extra: str = "") -> discord.Embed:
    e = base("Based Deobfuscator — Processing")
    e.add_field(name="Job ID", value=f"`{job_id}`", inline=True)
    e.add_field(name="Stage", value=stage, inline=True)
    if extra:
        e.add_field(name="Detail", value=extra[:1000], inline=False)
    return e


def analysis_result(job_id: str, report, ranked) -> discord.Embed:
    e = base("Based Deobfuscator — Analysis Results")
    e.add_field(name="Job ID", value=f"`{job_id}`", inline=True)
    e.add_field(name="Language", value=report.language, inline=True)
    e.add_field(name="Lines / Entropy", value=f"{report.lines} / {report.entropy}", inline=True)
    for f in report.findings[:5]:
        e.add_field(name=f["label"], value=f"Confidence {f['confidence']:.0%} — {f['evidence']}"[:1024], inline=False)
    if ranked:
        txt = "\n".join(f"`{eid}` — {s:.0%} ({r[:80]})" for eid, s, r in ranked[:4])
        e.add_field(name="Compatible engines", value=txt[:1024], inline=False)
    else:
        e.add_field(name="Compatible engines", value="None available.", inline=False)
    return e


def complete(job, engine: str, preview_note: str) -> discord.Embed:
    e = base("BASED DEOBFUSCATOR — DEOBFUSCATION COMPLETE", color=SUCCESS)
    e.add_field(name="Status", value="Success", inline=True)
    e.add_field(name="Engine", value=engine, inline=True)
    e.add_field(name="Original file", value=f"`{job.filename}`", inline=False)
    e.add_field(name="Original size", value=_s(job.original_size), inline=True)
    e.add_field(name="Output size", value=_s(job.output_size), inline=True)
    e.add_field(name="Processing time", value=f"{job.processing_time:.2f}s", inline=True)
    e.add_field(name="Validation", value="Passed", inline=True)
    e.add_field(name="Job ID", value=f"`{job.id}`", inline=True)
    if preview_note:
        e.add_field(name="Preview", value=preview_note[:1024], inline=False)
    return e


def _s(n: int) -> str:
    from .formatting import fmt_size
    return fmt_size(n)


def failed(job_id: str, reason: str, next_step: str = "") -> discord.Embed:
    e = base("Based Deobfuscator — Failed", color=ERROR)
    e.add_field(name="Job ID", value=f"`{job_id}`", inline=True)
    e.add_field(name="Reason", value=reason[:1000], inline=False)
    if next_step:
        e.add_field(name="Next step", value=next_step[:1000], inline=False)
    return e


def invalid_input(reason: str) -> discord.Embed:
    e = base("Based Deobfuscator — Invalid Input", color=WARN)
    e.description = reason[:1500]
    return e


def unsupported(reason: str) -> discord.Embed:
    e = base("Based Deobfuscator — Unsupported Obfuscation", color=WARN)
    e.description = reason[:1500]
    return e
