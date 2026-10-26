"""
Interface · Discord Bot
=======================
Async Discord bot that lets the user control VDX OpenAgent
remotely (e.g. from an iPhone Discord client).

Commands (prefix configurable, default ``!``):
    !ask <message>   — send a message to the agent
    !status          — check whether Ollama / agent are healthy
    !history         — show recent conversation turns
    !ping            — latency check
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from config.settings import get_settings

if TYPE_CHECKING:
    from core.agent import Agent

logger = logging.getLogger(__name__)


class VDXDiscordBot(commands.Bot):
    """Discord bot wired to a shared :class:`Agent` instance."""

    def __init__(self, agent: Agent) -> None:
        """Initialise intents, command prefix, and store the agent."""
        cfg = get_settings().discord
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=cfg.command_prefix,
            intents=intents,
            help_command=commands.DefaultHelpCommand(),
        )
        self.agent = agent
        self._allowed_ids = set(cfg.allowed_user_ids)
        self._cfg = cfg

    # ── Lifecycle ────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """Register slash-less text commands after login."""
        self.add_command(commands.Command(self.cmd_ask, name="ask"))
        self.add_command(commands.Command(self.cmd_status, name="status"))
        self.add_command(commands.Command(self.cmd_history, name="history"))
        self.add_command(commands.Command(self.cmd_ping, name="ping"))
        logger.info("Discord commands registered")

    async def on_ready(self) -> None:
        """Log a confirmation once the bot is connected."""
        logger.info("Discord bot online as %s", self.user)
        # Set a custom presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="VDX OpenAgent",
            )
        )

    # ── Auth helper ──────────────────────────────────────────────────

    def _is_authorised(self, user_id: int) -> bool:
        """Return True if the user is allowed (or the allow-list is empty)."""
        if not self._allowed_ids:
            return True  # open mode — no restriction
        return user_id in self._allowed_ids

    async def _deny(self, ctx: commands.Context) -> None:
        """Reply with an access-denied message."""
        await ctx.reply("⛔ You are not authorised to control VDX OpenAgent.")

    # ── Commands ─────────────────────────────────────────────────────

    async def cmd_ask(self, ctx: commands.Context, *, message: str) -> None:
        """Send a message to VDX OpenAgent.

        Usage: ``!ask Remind me to buy milk tomorrow at 9am``
        """
        if not self._is_authorised(ctx.author.id):
            await self._deny(ctx)
            return

        # Show typing indicator while the LLM thinks
        async with ctx.typing():
            try:
                reply = await self.agent.aprocess(message, source="discord")
            except Exception as exc:
                logger.exception("Discord ask failed")
                await ctx.reply(f"⚠️ Error: {exc}")
                return

        # Discord hard-limit is 2000 chars — chunk if needed
        for chunk in _split_message(reply, 1900):
            await ctx.reply(chunk)

    async def cmd_status(self, ctx: commands.Context) -> None:
        """Check Ollama availability and basic agent health."""
        if not self._is_authorised(ctx.author.id):
            await self._deny(ctx)
            return

        ollama_ok = self.agent.llm.is_available()
        model = self.agent.llm.model
        facts = len(self.agent.memory.get_all_facts())
        history_len = len(self.agent.memory.get_context())

        status = (
            f"**VDX OpenAgent — Status**\n"
            f"• Ollama: {'🟢 online' if ollama_ok else '🔴 offline'}\n"
            f"• Model: `{model}`\n"
            f"• Short-term messages: {history_len}\n"
            f"• Long-term facts: {facts}\n"
        )
        await ctx.reply(status)

    async def cmd_history(self, ctx: commands.Context) -> None:
        """Show the last few conversation turns."""
        if not self._is_authorised(ctx.author.id):
            await self._deny(ctx)
            return

        history = self.agent.memory.get_history(limit=10, source="discord")
        if not history:
            await ctx.reply("No Discord conversation history yet.")
            return

        lines = []
        for msg in history:
            role = msg["role"].upper()
            content = msg["content"][:120]
            lines.append(f"**{role}**: {content}")

        await ctx.reply("\n".join(lines))

    async def cmd_ping(self, ctx: commands.Context) -> None:
        """Simple latency check."""
        latency_ms = round(self.latency * 1000)
        await ctx.reply(f"🏓 Pong! Latency: {latency_ms} ms")


# ── Helpers ──────────────────────────────────────────────────────────

def _split_message(text: str, limit: int = 1900) -> list[str]:
    """Split a long reply into Discord-safe chunks."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


def run_discord_bot(agent: Agent) -> None:
    """Start the Discord bot (blocking — intended to run in a daemon thread).

    If ``DISCORD_BOT_TOKEN`` is empty the function returns immediately
    so the rest of the app can still launch without Discord.
    """
    token = get_settings().discord.token
    if not token:
        logger.warning(
            "DISCORD_BOT_TOKEN not set — Discord bot will not start. "
            "Set it in your .env file to enable remote control."
        )
        return

    bot = VDXDiscordBot(agent)
    logger.info("Starting Discord bot…")
    try:
        bot.run(token, log_handler=None)  # we use our own logging
    except discord.LoginFailure:
        logger.error("Discord login failed — check DISCORD_BOT_TOKEN")
    except Exception:
        logger.exception("Discord bot crashed")
