# discord-echo-bot

A minimal Discord bot that forwards Discord messages to an ACP harness and sends the reply back.

This version uses `codex-acp` by default, so the flow is:

`Discord message -> bot -> codex-acp child process -> Codex reply -> Discord`

Behavior:

- Mention the bot in a channel to start a conversation
- The bot creates a thread when possible
- Follow-up messages in that thread reuse the same ACP session
- The bot streams intermediate text into a placeholder message and posts the final reply back to Discord

## Local run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DISCORD_TOKEN=your_bot_token_here
export ACP_COMMAND=codex-acp
python bot.py
```

## Environment

Copy `.env.example` or provide the token directly as an environment variable.

Required:

```bash
export DISCORD_TOKEN=your_bot_token_here
```

Optional:

```bash
export ACP_COMMAND=codex-acp
export ACP_WORKDIR=/home/ubuntu/openab
```

Notes:

- `ACP_WORKDIR` defaults to the parent directory of this project, which is `/home/ubuntu/openab` in this workspace
- `codex-acp` must already be installed and authenticated
- Current Codex auth can be checked with `codex login status`

## systemd service

This repo includes a service template at `systemd/discord-echo-bot.service`.

1. Put the bot token in a local machine-only env file:

```bash
mkdir -p ~/.config
chmod 700 ~/.config
printf '%s\n' 'DISCORD_TOKEN=your_bot_token_here' > ~/.config/discord-echo-bot.env
chmod 600 ~/.config/discord-echo-bot.env
```

2. Install and start the service:

```bash
sudo install -m 0644 systemd/discord-echo-bot.service /etc/systemd/system/discord-echo-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now discord-echo-bot.service
```

3. Manage the service:

```bash
sudo systemctl status discord-echo-bot
sudo systemctl restart discord-echo-bot
sudo systemctl stop discord-echo-bot
sudo journalctl -u discord-echo-bot -f
```
