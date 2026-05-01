import json
import os
import re
import shutil
from glob import glob

import discord
from acp_bridge import AgentConfig, SessionPool
from azure_agent_bridge import run_azure_agent

DEFAULT_ACP_WORKDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AZURE_TRIGGER = "azure:"


class Client(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.pool = SessionPool(
            AgentConfig(
                command=_resolve_acp_command(),
                args=_build_acp_args(),
                working_dir=os.environ.get("ACP_WORKDIR", DEFAULT_ACP_WORKDIR),
                env={
                    "PATH": _build_acp_path(),
                    "HOME": os.environ.get("HOME", "/home/ubuntu"),
                },
            )
        )

    async def on_ready(self):
        print(f'[ready] user={self.user} user_id={self.user.id}')

    async def on_message(self, message):
        if self.user is None:
            return
        if message.author.bot:
            return

        in_managed_thread = isinstance(message.channel, discord.Thread) and self.pool.has_session(
            str(message.channel.id)
        )
        mentioned = self.user in message.mentions
        if not mentioned and not in_managed_thread:
            return

        prompt = _strip_mentions(message.content).strip() if mentioned else message.content.strip()
        if not prompt:
            return

        channel_name = getattr(message.channel, 'name', str(message.channel))
        guild_name = getattr(message.guild, 'name', 'DM')
        print(f"[seen] author={message.author} author_id={message.author.id} is_bot={message.author.bot} guild={guild_name} channel={channel_name} content={message.content!r}")

        target_channel = await self._resolve_target_channel(message, prompt)
        thinking_message = await target_channel.send("...")
        sender_context = _build_sender_context(message)
        prompt_with_sender = f"<sender_context>\n{sender_context}\n</sender_context>\n\n{prompt}"
        azure_prompt = _strip_azure_trigger(prompt)

        try:
            if _is_azure_prompt(prompt):
                response = await run_azure_agent(azure_prompt)
                final_text = response or "_(no response)_"
                chunks = _split_message(final_text)
                await thinking_message.edit(content=chunks[0])
                for chunk in chunks[1:]:
                    await target_channel.send(chunk)
            else:
                connection = await self.pool.get_or_create(str(target_channel.id))
                latest_content = "..."

                async def on_update(content: str) -> None:
                    nonlocal latest_content
                    if content != latest_content:
                        latest_content = content
                        await thinking_message.edit(content=_split_message(content)[0])

                response = await connection.prompt(prompt_with_sender, on_update=on_update)
                final_text = latest_content if latest_content != "..." else response or "_(no response)_"
                chunks = _split_message(final_text)
                await thinking_message.edit(content=chunks[0])
                for chunk in chunks[1:]:
                    await target_channel.send(chunk)
        except Exception as exc:
            print(f"[error] discord_reply_failed error={exc!r}")
            await thinking_message.edit(content=f"⚠️ {exc}")

    async def _resolve_target_channel(self, message: discord.Message, prompt: str):
        if isinstance(message.channel, discord.Thread):
            return message.channel

        thread_name = _shorten_thread_name(prompt)
        try:
            return await message.create_thread(name=thread_name)
        except Exception:
            return message.channel


def _build_sender_context(message: discord.Message) -> str:
    display_name = getattr(message.author, "display_name", message.author.name)
    return json.dumps(
        {
            "schema": "openab.sender.v1",
            "sender_id": str(message.author.id),
            "sender_name": message.author.name,
            "display_name": display_name,
            "channel": "discord",
            "channel_id": str(message.channel.id),
            "is_bot": message.author.bot,
        },
        ensure_ascii=False,
    )


def _strip_mentions(content: str) -> str:
    return re.sub(r"<@[!&]?\d+>", "", content).strip()


def _shorten_thread_name(prompt: str) -> str:
    shortened = re.sub(
        r"https?://github\.com/([^/]+/[^/]+)/(issues|pull)/(\d+)",
        r"\1#\3",
        prompt,
    )
    return (shortened[:40] + "...") if len(shortened) > 40 else shortened


def _split_message(content: str, limit: int = 1900) -> list[str]:
    if len(content) <= limit:
        return [content]

    chunks = []
    remaining = content
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _is_azure_prompt(prompt: str) -> bool:
    return prompt.lower().startswith(AZURE_TRIGGER)


def _strip_azure_trigger(prompt: str) -> str:
    if not _is_azure_prompt(prompt):
        return prompt
    return prompt[len(AZURE_TRIGGER):].strip()


def _resolve_acp_command() -> str:
    configured = os.environ.get("ACP_COMMAND")
    if configured:
        return configured

    resolved = shutil.which("codex-acp")
    if resolved:
        return resolved

    candidates = sorted(glob(os.path.expanduser("~/.nvm/versions/node/*/bin/codex-acp")))
    if candidates:
        return candidates[-1]

    return "codex-acp"


def _build_acp_args() -> list[str]:
    return [
        "-c",
        'approval_policy="never"',
        "-c",
        'sandbox_mode="danger-full-access"',
    ]


def _build_acp_path() -> str:
    path_entries: list[str] = []

    codex_acp = shutil.which("codex-acp")
    if codex_acp:
        path_entries.append(os.path.dirname(codex_acp))

    node_bins = sorted(glob(os.path.expanduser("~/.nvm/versions/node/*/bin")))
    if node_bins:
        path_entries.append(node_bins[-1])

    current_path = os.environ.get("PATH", "")
    if current_path:
        path_entries.extend(current_path.split(":"))

    deduped: list[str] = []
    seen = set()
    for entry in path_entries:
        if entry and entry not in seen:
            deduped.append(entry)
            seen.add(entry)
    return ":".join(deduped)


intents = discord.Intents.default()
intents.message_content = True

client = Client(intents=intents)
client.run(os.environ['DISCORD_TOKEN'])
