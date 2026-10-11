"""Shared deobfuscation pipeline used by /deobfuscate and /analyze flows."""
from __future__ import annotations
import asyncio
import io
import logging
import time

import discord

from core.analyzer import analyze_source
from core.engine_selector import rank_engines, auto_select
from core.job_manager import JobStatus
from core.output_validator import validate_output
from ui import embeds
from ui.formatting import fmt_size, code_preview
from ui.views import EngineSelectView
from workers.runner import run_engine

log = logging.getLogger("based.pipeline")
STAGES = [
    "Receiving source...", "Validating input...", "Analyzing obfuscation patterns...",
    "Detecting compatible engines...", "Selecting deobfuscator...",
    "Deobfuscating source...", "Validating output...", "Preparing downloadable file...",
]


async def run_pipeline(interaction: discord.Interaction, job, source_text: str, bot) -> None:
    """Edit the original response message through each stage; deliver result."""
    settings = bot.settings
    msg = await interaction.original_response()

    async def set_stage(stage: str, status: JobStatus | None = None):
        await bot.jobs.update(job, stage=stage)
        if status:
            job.status = status
        try:
            await msg.edit(embed=embeds.stage_update(job.id, stage))
        except discord.HTTPException:
            pass

    started = time.time()
    try:
        await set_stage(STAGES[2], JobStatus.ANALYZING)
        if job.cancelled.is_set():
            return await _cancelled(msg, job)
        report = analyze_source(source_text)
        await set_stage(STAGES[3])
        ranked = rank_engines(bot.registry, report)
        if not ranked:
            await bot.jobs.update(job, status=JobStatus.FAILED)
            job.error = "No compatible engine available."
            await msg.edit(embed=embeds.unsupported(
                "No installed engine matches this script. "
                "The bundled normalizer handles plain/minified Lua only; "
                "VM/loader-style obfuscation is unsupported."))
            bot.db.record(job)
            return

        await set_stage(STAGES[4])
        engine_id, _ = auto_select(bot.registry, report, settings.auto_select_threshold)
        if engine_id is None:
            # interactive selection
            await bot.jobs.update(job, status=JobStatus.AWAITING_SELECTION)
            opts = [
                {"label": f"{'Auto Detect (recommended)' if False else bot.registry.get(eid).display_name}",
                 "value": eid,
                 "description": f"score {s:.0%} — {r[:80]}"}
                for eid, s, r in ranked
            ]
            view = EngineSelectView(job.id, interaction.user.id, opts)
            try:
                await msg.edit(embed=embeds.analysis_result(job.id, report, ranked), view=view)
            except discord.HTTPException:
                pass
            await view.wait()
            if view.cancelled or job.cancelled.is_set():
                return await _cancelled(msg, job)
            if view.chosen in (None, "auto"):
                engine_id, _ = auto_select(bot.registry, report, 0.0)
                engine_id = engine_id or ranked[0][0]
            else:
                engine_id = view.chosen
        info = bot.registry.get(engine_id)
        if not info or not info.available or not info.enabled:
            await bot.jobs.update(job, status=JobStatus.FAILED)
            await msg.edit(embed=embeds.failed(job.id, f"Engine '{engine_id}' is unavailable."))
            return
        await bot.jobs.update(job, engine_id=engine_id, status=JobStatus.RUNNING)

        # concurrency gate (don't hold interaction)
        pos = bot.queue.position()
        if pos > 0:
            try:
                await msg.edit(embed=embeds.stage_update(job.id, f"Queued — position {pos + 1}"))
            except discord.HTTPException:
                pass
        await bot.queue.acquire()
        try:
            await set_stage(STAGES[5], JobStatus.RUNNING)
            ok, payload, elapsed, ver = await asyncio.wait_for(
                run_engine(info.instance, source_text, info.timeout, job.id),
                timeout=settings.job_timeout + 10,
            )
            job.processing_time = elapsed
        finally:
            bot.queue.release()

        if job.cancelled.is_set():
            return await _cancelled(msg, job)
        if not ok:
            # fallback
            if settings.fallback_enabled:
                for eid, _, _ in ranked:
                    if eid == engine_id:
                        continue
                    alt = bot.registry.get(eid)
                    if not alt or not alt.available:
                        continue
                    job.attempts.append({"engine": engine_id, "error": payload[:300]})
                    await set_stage(f"Trying fallback engine: {alt.display_name}...")
                    ok2, payload2, el2, _ = await run_engine(alt.instance, source_text, alt.timeout, job.id)
                    job.processing_time += el2
                    if ok2:
                        engine_id, payload, info = eid, payload2, alt
                        ok = True
                        break
                    job.attempts.append({"engine": eid, "error": payload2[:300]})
            if not ok:
                await bot.jobs.update(job, status=JobStatus.FAILED)
                job.error = payload[:500]
                await msg.edit(embed=embeds.failed(
                    job.id, payload[:800],
                    "Try the /analyze command for details, or a different engine."))
                bot.db.record(job, engine_id)
                return

        await set_stage(STAGES[6], JobStatus.VALIDATING)
        verdict = validate_output(source_text, payload, settings.max_output_bytes)
        if not verdict.ok:
            await bot.jobs.update(job, status=JobStatus.FAILED)
            job.error = verdict.message
            await msg.edit(embed=embeds.failed(job.id, verdict.message,
                "The engine ran but the result did not pass validation. It was NOT reported as success."))
            bot.db.record(job, engine_id)
            return

        await set_stage(STAGES[7])
        job.output_size = len(payload.encode("utf-8"))
        job.processing_time = round(time.time() - started, 2)
        await bot.jobs.update(job, status=JobStatus.COMPLETED)
        preview, trunc = code_preview(payload, settings.preview_max_lines, settings.preview_max_chars)
        note = f"first {settings.preview_max_lines} lines" + (" (truncated)" if trunc else "")
        embed = embeds.complete(job, info.display_name, note)
        data = payload.encode("utf-8")
        if len(data) > settings.max_output_bytes:
            await msg.edit(embed=embeds.failed(job.id, "Output exceeds Discord upload limit."), view=None)
            return
        file = discord.File(io.BytesIO(data), filename="deobfuscated.lua")
        try:
            await msg.edit(embed=embed, view=None, attachments=[file])
            await interaction.followup.send(f"```lua\n{preview}\n```\n*Preview — {note}*")
        except discord.HTTPException as e:
            await msg.edit(embed=embeds.failed(job.id, f"Could not attach result: {type(e).__name__}"), view=None)
        bot.db.record(job, engine_id)
    except asyncio.TimeoutError:
        await bot.jobs.update(job, status=JobStatus.FAILED)
        try:
            await msg.edit(embed=embeds.failed(job.id, "Job timed out.", "Try a smaller file or retry later."), view=None)
        except discord.HTTPException:
            pass
    except Exception:
        log.exception("pipeline error %s", job.id)
        await bot.jobs.update(job, status=JobStatus.FAILED)
        try:
            await msg.edit(embed=embeds.failed(job.id, "Unexpected internal error.", "Please retry; admins see logs."), view=None)
        except discord.HTTPException:
            pass


async def _cancelled(msg: discord.Message, job) -> None:
    from core.job_manager import JobStatus
    job.status = JobStatus.CANCELLED
    try:
        await msg.edit(embed=embeds.failed(job.id, "Job cancelled by user."), view=None)
    except discord.HTTPException:
        pass
