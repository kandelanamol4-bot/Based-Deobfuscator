"""Job commands: /job, /cancel, /history. Help: /help, /privacy. Admin: /admin."""
from __future__ import annotations
import discord
from discord import app_commands

from ui import embeds


class JobsCog(discord.ext.commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="job", description="Show status of one of your jobs.")
    @app_commands.describe(job_id="Job ID, e.g. BD-1A2B3C4D")
    async def job(self, interaction: discord.Interaction, job_id: str):
        job = await self.bot.jobs.get(job_id.strip())
        if not job or (job.user_id != interaction.user.id and interaction.user.id not in self.bot.settings.admin_user_ids):
            await interaction.response.send_message(embed=embeds.invalid_input("Job not found or not yours."), ephemeral=True)
            return
        e = embeds.stage_update(job.id, f"{job.status.value} — {job.stage}")
        e.add_field(name="Engine", value=job.engine_id or "—", inline=True)
        if job.error:
            e.add_field(name="Error", value=job.error[:500], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="cancel", description="Cancel one of your active jobs.")
    @app_commands.describe(job_id="Job ID to cancel")
    async def cancel(self, interaction: discord.Interaction, job_id: str):
        job = await self.bot.jobs.get(job_id.strip())
        if not job or (job.user_id != interaction.user.id and interaction.user.id not in self.bot.settings.admin_user_ids):
            await interaction.response.send_message(embed=embeds.invalid_input("Job not found or not yours."), ephemeral=True)
            return
        job.cancelled.set()
        from core.job_manager import JobStatus
        job.status = JobStatus.CANCELLED
        await interaction.response.send_message(embed=embeds.stage_update(job.id, "Cancelled."), ephemeral=True)

    @app_commands.command(name="history", description="Show your recent jobs.")
    async def history(self, interaction: discord.Interaction):
        if not self.bot.settings.enable_history:
            await interaction.response.send_message(
                embed=embeds.base("History disabled", "Job history is disabled on this server."), ephemeral=True)
            return
        rows = self.bot.db.recent(interaction.user.id)
        e = embeds.base("Based Deobfuscator — Recent Jobs")
        if not rows:
            e.description = "No recorded jobs."
        for jid, fn, eng, st, _, _ in rows[:5]:
            e.add_field(name=f"`{jid}` — {st}", value=f"{fn} via {eng or '—'}"[:200], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


class HelpCog(discord.ext.commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="How to use Based Deobfuscator.")
    async def help(self, interaction: discord.Interaction):
        s = self.bot.settings
        e = embeds.base("Based Deobfuscator — Help")
        e.description = (
            "**Submit:** `/deobfuscate method:url url:<https link>` • "
            "`method:file file:<attach .lua/.luau/.txt>` • `method:raw code:<paste small script>`\n"
            f"Limits: input {s.max_input_mb} MB, output {s.max_output_mb} MB, timeout {s.job_timeout}s.\n"
            "**Other:** `/analyze` (no deobfuscation) • `/engines` • `/job` • `/cancel` • `/history` • `/privacy`\n"
            "Large scripts: upload a file instead of pasting. Never post tokens in code."
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="privacy", description="What the bot stores.")
    async def privacy(self, interaction: discord.Interaction):
        s = self.bot.settings
        e = embeds.base("Based Deobfuscator — Privacy")
        e.description = (
            "Source code is processed in an isolated temp dir and deleted after delivery "
            f"(retention ~{s.temp_retention_seconds}s). Only minimal job metadata "
            f"(id, filename, engine, sizes, timing) is kept {'for ' + str(s.job_retention_days) + ' days' if s.enable_history else 'in memory only — history is disabled'}. "
            "Source is never sent to external APIs. Use /cancel to stop a job."
        )
        await interaction.response.send_message(embed=e, ephemeral=True)


def _is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id in interaction.client.settings.admin_user_ids


admin_group = app_commands.Group(name="admin", description="Administrator diagnostics")


@admin_group.command(name="status", description="Bot health, queue, engines.")
async def admin_status(interaction: discord.Interaction):
    if not _is_admin(interaction):
        await interaction.response.send_message("Not authorized.", ephemeral=True)
        return
    bot = interaction.client
    e = embeds.base("Based Deobfuscator — Admin Status")
    e.add_field(name="Queue waiting", value=str(bot.queue.position()), inline=True)
    e.add_field(name="Max concurrent", value=str(bot.settings.max_concurrent_jobs), inline=True)
    for info in bot.registry.engines.values():
        e.add_field(name=info.id, value=f"{'OK' if info.available else 'DOWN'} — {info.last_health[:120]}", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@admin_group.command(name="engines", description="Enable/disable a configured engine.")
@app_commands.describe(engine_id="Engine id", enabled="Enable or disable")
async def admin_engines(interaction: discord.Interaction, engine_id: str, enabled: bool):
    if not _is_admin(interaction):
        await interaction.response.send_message("Not authorized.", ephemeral=True)
        return
    ok = interaction.client.registry.set_enabled(engine_id, enabled)
    await interaction.response.send_message(f"{'Updated' if ok else 'Unknown engine'}: `{engine_id}` -> {enabled}", ephemeral=True)


@admin_group.command(name="config", description="Show safe config (no secrets).")
async def admin_config(interaction: discord.Interaction):
    if not _is_admin(interaction):
        await interaction.response.send_message("Not authorized.", ephemeral=True)
        return
    s = interaction.client.settings
    e = embeds.base("Based Deobfuscator — Config")
    e.add_field(name="Limits", value=f"in {s.max_input_mb}MB / out {s.max_output_mb}MB / timeout {s.job_timeout}s / concurrent {s.max_concurrent_jobs}", inline=False)
    e.add_field(name="History", value=str(s.enable_history), inline=True)
    e.add_field(name="Fallback", value=str(s.fallback_enabled), inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


class AdminCog(discord.ext.commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.tree.add_command(admin_group)

    async def cog_unload(self):
        try:
            self.bot.tree.remove_command("admin")
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(JobsCog(bot))
    await bot.add_cog(HelpCog(bot))
    await bot.add_cog(AdminCog(bot))
