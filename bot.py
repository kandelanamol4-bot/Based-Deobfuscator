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
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.jobs = JobManager()
        self.queue = QueueManager(settings.max_concurrent_jobs)
        self.registry = EngineRegistry()
        self.db = Database(BASE_DIR / "data" / "jobs.db", settings.enable_history)
        self.loop: asyncio.AbstractEventLoop | None = None

    async def setup_hook(self):
        self.loop = asyncio.get_running_loop()
        self.registry.load(load_engine_configs(self.settings.engines_file))
        await self.registry.health_check_all()
        await self.load_extension("cogs.deobfuscate")
        await self.load_extension("cogs.jobs")
        gid = self.settings.guild_id
        if gid:
            await self.tree.sync(guild=discord.Object(id=gid))
        else:
            await self.tree.sync()

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
