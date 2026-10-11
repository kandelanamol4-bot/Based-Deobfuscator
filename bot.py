"""Based Deobfuscator — entrypoint."""
from __future__ import annotations
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands

from config import Settings, load_engine_configs, validate_startup
from core.engine_registry import EngineRegistry
from core.job_manager import JobManager
from core.queue_manager import QueueManager
from storage.database import Database

BASE_DIR = Path(__file__).resolve().parent


def setup_logging(level: str) -> logging.Logger:
    BASE_DIR.joinpath("logs").mkdir(exist_ok=True)
    logger = logging.getLogger("based")
    logger.setLevel(getattr(logging, level, logging.INFO))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    fh = RotatingFileHandler(BASE_DIR / "logs" / "based.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.handlers = [fh, sh]
    # silence discord noise a bit
    logging.getLogger("discord").setLevel(logging.WARNING)
    return logger


class BasedBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True  # needed for !resync / !ping text fallback
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.jobs = JobManager()
        self.queue = QueueManager(settings.max_concurrent_jobs)
        self.registry = EngineRegistry()
        self.db = Database(BASE_DIR / "data" / "jobs.db", settings.enable_history)
        self.loop: asyncio.AbstractEventLoop | None = None

    async def setup_hook(self):
        log = logging.getLogger("based")
        self.loop = asyncio.get_running_loop()
        self.registry.load(load_engine_configs(self.settings.engines_file))
        await self.registry.health_check_all()
        await self.load_extension("cogs.deobfuscate")
        await self.load_extension("cogs.jobs")
        gid = self.settings.guild_id
        try:
            if gid:
                synced = await self.tree.sync(guild=discord.Object(id=gid))
                log.info("Slash sync: %d commands to guild %s: %s",
                         len(synced), gid, [c.name for c in synced])
            else:
                synced = await self.tree.sync()
                log.info("Slash sync: %d commands globally (can take up to 1h to appear): %s",
                         len(synced), [c.name for c in synced])
        except discord.HTTPException as e:
            log.error("Slash sync FAILED: %s (status %s). "
                      "Reinvite with 'applications.commands' scope.", e.text, e.status)
        except Exception:
            log.exception("Slash sync FAILED with unexpected error.")

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.content.strip() == "!ping":
            await message.channel.send("Based Deobfuscator is online.")
            return
        if message.content.strip() == "!resync":
            if message.author.id not in self.settings.admin_user_ids:
                await message.channel.send("Not authorized.")
                return
            log = logging.getLogger("based")
            try:
                gid = self.settings.guild_id
                if gid:
                    synced = await self.tree.sync(guild=discord.Object(id=gid))
                    scope = f"guild {gid} (should appear instantly)"
                else:
                    synced = await self.tree.sync()
                    scope = "global (can take up to 1h to appear)"
                names = ", ".join(f"/{c.name}" for c in synced)
                log.info("Manual !resync by %s: %d commands to %s", message.author.id, len(synced), scope)
                await message.channel.send(f"Synced {len(synced)} commands to {scope}: {names}")
            except Exception as e:
                log.exception("Manual !resync failed")
                await message.channel.send(f"Resync failed: {type(e).__name__} — check logs.")
        await self.process_commands(message)

    async def on_ready(self):
        log = logging.getLogger("based")
        log.info("Logged in as %s. Engines: %s",
                 self.user,
                 {eid: i.available for eid, i in self.registry.engines.items()})


async def main():
    settings = Settings.load()
    log = setup_logging(settings.log_level)
    for w in validate_startup(settings):
        log.warning("startup: %s", w)
    if not settings.token:
        log.error("DISCORD_TOKEN missing. Copy .env.example to .env and fill it in.")
        raise SystemExit(2)
    for d in ("data", "logs", "temp"):
        (BASE_DIR / d).mkdir(exist_ok=True)
    bot = BasedBot(settings)
    async with bot:
        await bot.start(settings.token)


if __name__ == "__main__":
    asyncio.run(main())
