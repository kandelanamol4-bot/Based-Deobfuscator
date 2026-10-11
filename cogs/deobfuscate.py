"""Slash commands: /deobfuscate, /analyze, /engines."""
from __future__ import annotations
import asyncio
from typing import Literal

import discord
from discord import app_commands

from core.input_handler import download_url, sniff_text, validate_extension, validate_raw_code
from core.security import sanitize_filename, safe_log_url
from core.analyzer import analyze_source
from core.engine_selector import rank_engines
from core.job_manager import JobStatus
from ui import embeds
from ui.formatting import fmt_size
from .pipeline import run_pipeline


class DeobfuscateCog(discord.ext.commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="deobfuscate", description="Submit a Lua script (URL, file upload, or raw code).")
    @app_commands.describe(
        method="How are you providing the script?",
        url="HTTPS link to a .lua/.luau file (method=url)",
        file="Attach a .lua/.luau/.txt file (method=file)",
        code="Paste Lua source directly (method=raw, small scripts only)",
    )
    async def deobfuscate(
        self,
        interaction: discord.Interaction,
        method: Literal["url", "file", "raw"],
        url: str | None = None,
        file: discord.Attachment | None = None,
        code: str | None = None,
    ):
        bot = self.bot
        s = bot.settings
        # per-user concurrency
        if await bot.jobs.user_active_count(interaction.user.id) >= s.max_jobs_per_user:
            await interaction.response.send_message(
                embed=embeds.invalid_input("You already have an active job. Use /cancel or wait."), ephemeral=True)
            return
        # ---- gather source ----
        source_text: str | None = None
        filename = "input.lua"
        if method == "url":
            if not url:
                await interaction.response.send_message(embed=embeds.invalid_input("Provide `url` with method=url."), ephemeral=True)
                return
            await interaction.response.send_message(embed=embeds.stage_update("…", "Receiving source..."))
            data, fname, err = await download_url(url.strip(), s.max_input_bytes)
            if data is None:
                await interaction.edit_original_response(embed=embeds.invalid_input(err))
                return
            text, verr = sniff_text(data, s.max_input_bytes)
            if text is None:
                await interaction.edit_original_response(embed=embeds.invalid_input(verr))
                return
            source_text, filename = text, sanitize_filename(fname)
        elif method == "file":
            if file is None:
                await interaction.response.send_message(embed=embeds.invalid_input("Attach a file with method=file."), ephemeral=True)
                return
            ok, msg = validate_extension(file.filename)
            if not ok:
                await interaction.response.send_message(embed=embeds.invalid_input(msg), ephemeral=True)
                return
            if file.size > s.max_input_bytes:
                await interaction.response.send_message(
                    embed=embeds.invalid_input(f"File is {fmt_size(file.size)} (limit {fmt_size(s.max_input_bytes)})."), ephemeral=True)
                return
            await interaction.response.send_message(embed=embeds.stage_update("…", "Receiving source..."))
            try:
                data = await asyncio.wait_for(file.read(), timeout=30)
            except asyncio.TimeoutError:
                await interaction.edit_original_response(embed=embeds.invalid_input("Attachment download timed out."))
                return
            text, verr = sniff_text(data, s.max_input_bytes)
            if text is None:
                await interaction.edit_original_response(embed=embeds.invalid_input(verr))
                return
            source_text, filename = text, sanitize_filename(file.filename)
        else:  # raw
            if not code:
                await interaction.response.send_message(embed=embeds.invalid_input("Paste code with method=raw."), ephemeral=True)
                return
            text, verr = validate_raw_code(code, 6000, s.max_input_bytes)
            if text is None:
                await interaction.response.send_message(embed=embeds.invalid_input(verr), ephemeral=True)
                return
            await interaction.response.send_message(embed=embeds.stage_update("…", "Receiving source..."))
            source_text, filename = text, "pasted.lua"

        job = await bot.jobs.create(interaction.user.id, filename, len(source_text.encode("utf-8")))
        job.channel_id = interaction.channel_id
        try:
            msg = await interaction.original_response()
            job.message_id = msg.id
        except discord.HTTPException:
            pass
        # visible "Detecting deobfuscator" message (spec requirement)
        try:
            await interaction.edit_original_response(
                embed=embeds.detecting(job.id, filename, fmt_size(job.original_size), analyze_source(source_text).language))
        except discord.HTTPException:
            pass
        job.status = JobStatus.ANALYZING
        bot.loop.create_task(run_pipeline(interaction, job, source_text, bot))

    @app_commands.command(name="analyze", description="Analyze Lua obfuscation without deobfuscating.")
    @app_commands.describe(file="Attach a .lua/.luau/.txt file", code="Or paste Lua source (small scripts)")
    async def analyze(self, interaction: discord.Interaction, file: discord.Attachment | None = None, code: str | None = None):
        s = self.bot.settings
        text: str | None = None
        if file is not None:
            ok, msg = validate_extension(file.filename)
            if not ok:
                await interaction.response.send_message(embed=embeds.invalid_input(msg), ephemeral=True)
                return
            if file.size > s.max_input_bytes:
                await interaction.response.send_message(embed=embeds.invalid_input("File too large."), ephemeral=True)
                return
            data = await file.read()
            text, verr = sniff_text(data, s.max_input_bytes)
            if text is None:
                await interaction.response.send_message(embed=embeds.invalid_input(verr), ephemeral=True)
                return
        elif code:
            text, verr = validate_raw_code(code, 6000, s.max_input_bytes)
            if text is None:
                await interaction.response.send_message(embed=embeds.invalid_input(verr), ephemeral=True)
                return
        else:
            await interaction.response.send_message(embed=embeds.invalid_input("Attach a file or paste code."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        report = analyze_source(text)
        ranked = rank_engines(self.bot.registry, report)
        await interaction.followup.send(embed=embeds.analysis_result("ANALYZE", report, ranked), ephemeral=True)

    @app_commands.command(name="engines", description="Show available deobfuscation engines.")
    async def engines(self, interaction: discord.Interaction):
        e = embeds.base("Based Deobfuscator — Engines")
        if not self.bot.registry.engines:
            e.description = "No engines configured."
        for info in self.bot.registry.engines.values():
            status = "Available" if info.available else f"Unavailable — {info.last_health[:150]}"
            e.add_field(
                name=f"{info.display_name} (`{info.id}`)",
                value=f"{info.description[:200]}\nVersion: {info.version} | Status: {status}",
                inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(DeobfuscateCog(bot))
