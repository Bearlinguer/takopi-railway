# takopi-railway

Railway deployment for [takopi](https://github.com/banteg/takopi) - Telegram bridge for AI coding agents.

## One-Click Deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/F5m5Aw?utm_medium=integration&utm_source=template&utm_campaign=generic)

> **Note:** After deploying, add a volume mounted at `/data` in Railway's dashboard.

## Required Environment Variables

```bash
# Telegram (required)
TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN=your_bot_token
TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID=your_chat_id

# Engine API keys (at least one required)
ANTHROPIC_API_KEY=your_anthropic_key

# Optional
OPENAI_API_KEY=your_openai_key
GITHUB_TOKEN=your_github_token

# Optional: repos to clone on startup (comma-separated)
TAKOPI_REPOS=owner/repo1,owner/repo2
```

### Creating Your Telegram Bot

Before deploying, you need to create a bot with BotFather:

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Start a chat and send `/newbot`
3. Follow the prompts:
   - Choose a display name (e.g., "My Takopi Bot")
   - Choose a unique username ending in "bot" (e.g., "mytakopi_bot")
4. BotFather will reply with your bot token (looks like `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)
5. Copy this token and use it as `TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN`

**Important:** Keep your bot token secret! Anyone with this token can control your bot.

### Getting Your Chat ID

For DMs, your chat ID is the same as your user ID. To get it:

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your user ID
3. Use that number as `TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID`

## Structure

```
/data/
├── github/         # GitHub repos only
└── knowledge/      # Knowledge vault (notes, todos, memory)
    ├── 00-inbox/
    ├── 01-todos/
    ├── 02-projects/
    ├── 03-resources/   # Layer 2: long-term knowledge
    ├── 04-claude-code/skills/
    ├── 05-prompts/
    ├── 06-meetings/
    ├── 07-logs/agent/  # Layer 1: daily logs
    ├── 07-logs/daily/
    ├── CLAUDE.md
    └── MEMORY.md
```

## Default Skills

- `skill-creator` - Create new skills
- `cron` - Manage scheduled automations

## Engines

Pre-installed:
- Claude Code (`@anthropic-ai/claude-code`)
- Codex (`@openai/codex`)
