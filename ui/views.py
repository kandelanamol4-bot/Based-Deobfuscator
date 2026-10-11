"""Interactive views: engine select, cancel, info. Expire safely."""
from __future__ import annotations
import discord


class EngineSelectView(discord.ui.View):
    def __init__(self, job_id: str, owner_id: int, options: list[dict], timeout: float = 120):
        super().__init__(timeout=timeout)
        self.job_id = job_id
        self.owner_id = owner_id
        self.chosen: str | None = None
        self.cancelled = False
        self.info_requested = False
        select = discord.ui.Select(
            placeholder="Choose an engine…",
            options=[
                discord.SelectOption(
                    label=o["label"][:100],
                    value=o["value"][:100],
                    description=o.get("description", "")[:100],
                ) for o in options[:25]
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the job owner can choose.", ephemeral=True)
            return
        data = interaction.data or {}
        vals = data.get("values", [])
        self.chosen = vals[0] if vals else None
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Auto Detect", style=discord.ButtonStyle.primary)
    async def auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the job owner can choose.", ephemeral=True)
            return
        self.chosen = "auto"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel Job", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the job owner can cancel.", ephemeral=True)
            return
        self.cancelled = True
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self):
        self.stop()
