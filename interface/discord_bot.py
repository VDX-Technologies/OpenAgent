"""
Interface · Discord Bot
=======================
Async Discord bot that lets the user control VDX OpenAgent remotely (e.g.
from an iPhone Discord client).

Only the user IDs in ``DISCORD_ALLOWED_USERS`` may use it — with an empty list
it refuses everyone, since anyone sharing a server with the bot could
otherwise run tools on this Mac. Sensitive actions (sending, deleting…) ask
for a ✅ reaction from the same user before running.

Commands (prefix configurable, default ``!``):
    !ask <message>   — send a message to the agent
    !status          — check whether Ollama / agent are healthy
    !history         — show recent conversation turns
    !ping            — latency check
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from config.settings import get_settings
from core import approvals

if TYPE_CHECKING:
    from core.agent import Agent

logger = logging.getLogger(__name__)
APPROVE, DENY = "✅", "❌"


class VDXDiscordBot(commands.Bot):
    """Discord bot wired to a shared :class:`Agent` instance."""

    def __init__(self, agent: Agent) -> None:
        cfg = get_settings().discord
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=cfg.command_prefix, intents=intents,
                         help_command=commands.DefaultHelpCommand())
        self.agent = agent
        self._allowed_ids = set(cfg.allowed_user_ids)

    async def setup_hook(self) -> None:
        self.add_command(commands.Command(self.cmd_ask, name="ask"))
        self.add_command(commands.Command(self.cmd_status, name="status"))
        self.add_command(commands.Command(self.cmd_history, name="history"))
        self.add_command(commands.Command(self.cmd_ping, name="ping"))

    async def on_ready(self) -> None:
        logger.info("Discord bot online as %s", self.user)
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="VDX OpenAgent"))

    def _is_authorised(self, user_id: int) -> bool:
        return user_id in self._allowed_ids

    async def _deny(self, ctx: commands.Context) -> None:
        if not self._allowed_ids:
            await ctx.reply("⛔ No Discord users are allowed yet. Add your user ID in VDX → Settings → Discord → Allowed user IDs.")
        else:
            await ctx.reply("⛔ You are not authorised to control VDX OpenAgent.")

    async def _ask_approval(self, ctx: commands.Context, name: str, args: dict[str, Any]) -> bool:
        """Post the action and wait (2 min) for the requesting user's ✅ / ❌."""
        detail = json.dumps(args, ensure_ascii=False, indent=1)[:1500]
        msg = await ctx.reply(f"🔐 **{approvals.label(name)}**\n```json\n{detail}\n```React {APPROVE} to allow or {DENY} to cancel.")
        await msg.add_reaction(APPROVE)
        await msg.add_reaction(DENY)

        def check(reaction: discord.Reaction, user: discord.abc.User) -> bool:
            return reaction.message.id == msg.id and user.id == ctx.author.id and str(reaction.emoji) in (APPROVE, DENY)

        try:
            reaction, _ = await self.wait_for("reaction_add", timeout=120, check=check)
        except asyncio.TimeoutError:
            await msg.reply("⌛ No answer — not done.")
            return False
        return str(reaction.emoji) == APPROVE

    async def cmd_ask(self, ctx: commands.Context, *, message: str) -> None:
        """Send a message to VDX OpenAgent. Usage: ``!ask Remind me to buy milk tomorrow at 9am``"""
        if not self._is_authorised(ctx.author.id):
            await self._deny(ctx)
            return
        loop = asyncio.get_running_loop()

        def approve(_aid: str, name: str, args: dict[str, Any]) -> bool:
            fut = asyncio.run_coroutine_threadsafe(self._ask_approval(ctx, name, args), loop)
            try:
                return bool(fut.result(timeout=150))
            except Exception:
                return False

        def run() -> str:
            # same lock as the app's chat and automations: one run at a time
            with self.agent.lock:
                return self.agent.process(message, source="discord", approve=approve)

        async with ctx.typing():
            try:
                reply = await asyncio.to_thread(run)
            except Exception as exc:
                logger.exception("Discord ask failed")
                await ctx.reply(f"⚠️ Error: {exc}")
                return
        for chunk in _split_message(reply or "(no reply)", 1900):
            await ctx.reply(chunk)

    async def cmd_status(self, ctx: commands.Context) -> None:
        if not self._is_authorised(ctx.author.id):
            await self._deny(ctx)
            return
        ok = await asyncio.to_thread(self.agent.llm.is_available)
        await ctx.reply(
            f"**VDX OpenAgent — Status**\n• Ollama: {'🟢 online' if ok else '🔴 offline'}\n"
            f"• Model: `{self.agent.llm.model}`\n• Long-term facts: {len(self.agent.memory.get_all_facts())}\n"
        )

    async def cmd_history(self, ctx: commands.Context) -> None:
        if not self._is_authorised(ctx.author.id):
            await self._deny(ctx)
            return
        history = [m for m in self.agent.memory.get_history(limit=20, source="discord") if m["role"] in ("user", "assistant")]
        if not history:
            await ctx.reply("No Discord conversation history yet.")
            return
        text = "\n".join(f"**{m['role'].upper()}**: {m['content'][:120]}" for m in history[-10:])
        await ctx.reply(text[:1990])

    async def cmd_ping(self, ctx: commands.Context) -> None:
        await ctx.reply(f"🏓 Pong! Latency: {round(self.latency * 1000)} ms")


def _split_message(text: str, limit: int = 1900) -> list[str]:
    """Split a long reply into Discord-safe chunks (never an empty one)."""
    text = text or "(no reply)"
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def run_discord_bot(agent: Agent) -> None:
    """Start the Discord bot (blocking — intended to run in a daemon thread)."""
    cfg = get_settings().discord
    if not cfg.token:
        logger.warning("DISCORD_BOT_TOKEN not set — Discord bot will not start.")
        return
    if not cfg.allowed_user_ids:
        logger.warning("DISCORD_ALLOWED_USERS is empty — the bot will refuse every command until it is set.")
    bot = VDXDiscordBot(agent)
    try:
        bot.run(cfg.token, log_handler=None)
    except discord.LoginFailure:
        logger.error("Discord login failed — check DISCORD_BOT_TOKEN")
    except Exception:
        logger.exception("Discord bot crashed")
