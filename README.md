# discord-echo-bot

A minimal Discord bot that logs messages to console.

## Local run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DISCORD_TOKEN=your_bot_token_here
python bot.py
```

## Environment

Copy `.env.example` or provide the token directly as an environment variable:

```bash
export DISCORD_TOKEN=your_bot_token_here
```

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
