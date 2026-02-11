#!/bin/bash
set -e

# --- Takopi config ---
CONFIG_DIR="$HOME/.takopi"
CONFIG_FILE="$CONFIG_DIR/takopi.toml"

mkdir -p "$CONFIG_DIR"

# Seed config file with all documented defaults
# Env vars override via pydantic-settings at runtime (TAKOPI__KEY format)
cat > "$CONFIG_FILE" << 'EOF'
# Top-level settings
watch_config = true
default_engine = "claude"
transport = "telegram"

[transports.telegram]
bot_token = "placeholder"
chat_id = 0
allowed_user_ids = []
message_overflow = "split"
forward_coalesce_s = 1.0
voice_transcription = false
voice_max_bytes = 10485760
voice_transcription_model = "gpt-4o-mini-transcribe"
session_mode = "chat"
show_resume_line = false

[transports.telegram.topics]
enabled = false
scope = "auto"

[transports.telegram.files]
enabled = true
auto_put = true
auto_put_mode = "upload"
uploads_dir = "incoming"
allowed_user_ids = []
deny_globs = [".git/**", ".env", ".envrc", "**/*.pem", "**/.ssh/**"]

[plugins]
enabled = []

[codex]
model = "gpt-5.2"
extra_args = ["-c", "notify=[]", "--dangerously-bypass-approvals-and-sandbox"]

[claude]
model = "opus"
allowed_tools = ["Bash", "Read", "Edit", "Write", "WebSearch", "WebFetch"]
use_api_billing = true
EOF

# Debug: show generated config and env vars
echo "=== Generated TOML config ==="
cat "$CONFIG_FILE"
echo ""
echo "=== End config ==="
echo "=== TAKOPI env vars ==="
env | grep -i TAKOPI || echo "(none found)"
echo "=== End env vars ==="

# Try running takopi with verbose error output
echo "=== Attempting config load test ==="
python3 -c "
import tomllib, sys
with open('$CONFIG_FILE', 'rb') as f:
    try:
        data = tomllib.load(f)
        print('TOML parse OK:', list(data.keys()))
        if 'transports' in data and 'telegram' in data['transports']:
            tg = data['transports']['telegram']
            print('bot_token type:', type(tg.get('bot_token')).__name__, 'value:', repr(tg.get('bot_token'))[:30])
            print('chat_id type:', type(tg.get('chat_id')).__name__, 'value:', repr(tg.get('chat_id')))
    except Exception as e:
        print('TOML parse ERROR:', e)
" 2>&1 || echo "Python TOML check failed"

# Try loading settings via takopi's own loader to see the real error
echo "=== Attempting takopi load_settings ==="
python3 -c "
import traceback
try:
    from takopi.settings import load_settings
    settings, path = load_settings()
    print('load_settings OK!')
    print('transport:', settings.transport)
    tg = settings.transports.telegram
    print('bot_token:', repr(tg.bot_token)[:40])
    print('chat_id:', tg.chat_id)
except Exception as e:
    print('load_settings FAILED:', type(e).__name__, str(e))
    traceback.print_exc()
" 2>&1 || echo "takopi load_settings check failed"
echo "=== End takopi load_settings ==="

# --- GitHub CLI auth ---
if [ -n "$GITHUB_TOKEN" ]; then
  GITHUB_TOKEN="${GITHUB_TOKEN//\"/}"
  echo "Attempting GitHub CLI auth (token length: ${#GITHUB_TOKEN})..."
  if gh_output=$(echo "$GITHUB_TOKEN" | gh auth login --with-token 2>&1); then
    echo "✓ GitHub CLI authenticated"
    gh auth setup-git
    echo "✓ Git configured to use GitHub CLI authentication"
  else
    echo "⚠ GitHub CLI auth failed - continuing without GitHub integration"
    echo "  Error: $gh_output"
    echo "  Hint: Ensure GITHUB_TOKEN has 'repo' scope. Generate at: https://github.com/settings/tokens"
  fi
fi

# --- Codex CLI auth (optional) ---
if [ -n "$OPENAI_API_KEY" ]; then
  OPENAI_API_KEY="${OPENAI_API_KEY//\"/}"
  echo "Attempting Codex CLI auth (token length: ${#OPENAI_API_KEY})..."
  if codex_output=$(echo "$OPENAI_API_KEY" | codex login --with-api-key 2>&1); then
    echo "\u2713 Codex CLI authenticated"
  else
    echo "\u26a0 Codex CLI auth failed - continuing without Codex"
    echo "  Error: $codex_output"
    echo "  Hint: Ensure OPENAI_API_KEY is valid. Generate at: https://platform.openai.com/api-keys"
  fi
fi

# --- Knowledge vault bootstrap ---
VAULT="${KNOWLEDGE_PATH:-/data/knowledge}"

dirs=(
  00-inbox
  01-todos
  02-projects
  03-resources
  04-claude-code/skills
  05-prompts
  06-meetings
  07-logs/agent
  07-logs/daily
  _templates
  _assets
)

for d in "${dirs[@]}"; do
  mkdir -p "$VAULT/$d"
done

# MEMORY.md
if [ ! -f "$VAULT/MEMORY.md" ]; then
  cat > "$VAULT/MEMORY.md" << 'MEMO'
# Memory

Persistent context for the agent. Updated as significant things are learned.
MEMO
fi

# Todo files
[ -f "$VAULT/01-todos/inbox.md" ]  || echo "# Inbox"   > "$VAULT/01-todos/inbox.md"
[ -f "$VAULT/01-todos/active.md" ] || echo "# Active"  > "$VAULT/01-todos/active.md"
[ -f "$VAULT/01-todos/arxiv.md" ]  || echo "# Archive" > "$VAULT/01-todos/arxiv.md"

# Vault CLAUDE.md (agent memory instructions)
if [ ! -f "$VAULT/CLAUDE.md" ]; then
  cat > "$VAULT/CLAUDE.md" << 'VEOF'
# Knowledge Vault

## Directory Structure

```
/data/
├── github/      # GitHub repos ONLY
└── knowledge/      # Everything else (notes, docs, memory)
```

## Where Things Go

### `/data/github/` — GitHub Repos Only
- Clone all GitHub repos here
- All coding work happens here

### `/data/knowledge/` — Everything Else
- `00-inbox/` — Quick capture, unsorted notes
- `01-todos/` — Task management (inbox.md → active.md → arxiv.md)
- `02-projects/` — Project context and planning docs
- `03-resources/` — Long-term knowledge (Layer 2 memory)
- `04-claude-code/` — Claude configs and skills
- `05-prompts/` — Prompt library
- `06-meetings/` — Meeting notes
- `07-logs/agent/` — Daily agent logs (Layer 1 memory)
- `07-logs/daily/` — Human journal

## Agent Memory

### Layer 1: Daily Agent Logs (`07-logs/agent/YYYY-MM-DD.md`)
Append-only notes. Write here when:
- A decision is made (with rationale)
- User preference discovered
- Important action completed
- Something to follow up on

Format:
```markdown
## HH:MM AM/PM - Topic
Brief factual note. Decision: X. Reason: Y.
```

### Layer 2: Long-term Knowledge (`03-resources/`)
Curated, processed knowledge notes. Significant learnings get promoted here.

### Reading Memory
At session start:
1. Read `07-logs/agent/` for today + yesterday
2. Search `03-resources/` for relevant context
VEOF
fi

echo "✓ Knowledge vault ready at $VAULT"

# --- Symlink Claude skills to persistent volume ---
CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$VAULT/04-claude-code/skills"
mkdir -p "$CLAUDE_DIR"
if [ ! -L "$CLAUDE_DIR/skills" ]; then
  ln -sf "$SKILLS_DIR" "$CLAUDE_DIR/skills"
fi

# --- Global CLAUDE.md (agent instructions) ---
if [ ! -f "$CLAUDE_DIR/CLAUDE.md" ]; then
  cat > "$CLAUDE_DIR/CLAUDE.md" << 'GLOBALEOF'
# Global Agent Instructions

## Agent Memory

All sessions write memory to the knowledge vault at `/data/knowledge/`.

### Layer 1: Daily Agent Logs (`/data/knowledge/07-logs/agent/YYYY-MM-DD.md`)
Append-only notes to remember things for future sessions.

IMPORTANT: Proactively and automatically append to daily logs throughout the session without asking. Only ask if unsure whether something qualifies as worth logging.

Write here when:
- A decision is made (with rationale)
- User preference discovered
- Important action completed
- Something to follow up on

Format:
```markdown
## HH:MM AM/PM - Topic
Brief factual note. Decision: X. Reason: Y.
```

### Layer 2: Long-term Knowledge (`/data/knowledge/03-resources/`)
Significant learnings get promoted here as curated notes.

### Reading Memory
At session start (when context matters):
1. Read `/data/knowledge/MEMORY.md` for persistent context
2. Read `/data/knowledge/07-logs/agent/` for today + yesterday
3. Search `/data/knowledge/03-resources/` for relevant context
GLOBALEOF
fi

# --- Install default skills ---
if [ ! -d "$SKILLS_DIR/skill-creator" ]; then
  echo "Installing skill-creator skill..."
  npx --yes skills add https://github.com/anthropics/skills --skill skill-creator --global --yes
fi

# --- Seed cron skill ---
CRON_SKILL="$SKILLS_DIR/cron"
mkdir -p "$CRON_SKILL"
if [ ! -f "$CRON_SKILL/skill.md" ]; then
  cat > "$CRON_SKILL/skill.md" << 'SKILL'
# Cron

Manage scheduled automation for your skills.

## Usage

```
/cron <action>
```

**Actions:**
- `list` — Show all cron jobs
- `add` — Add a new scheduled job
- `remove` — Remove a job
- `sync` — Install crontab.txt to system

## Files

- Source: `04-claude-code/cron/crontab.txt`
- This file is version-controlled and synced to the system crontab

## Process

### /cron list
```bash
crontab -l
```

### /cron add
1. Ask: What skill/command to run?
2. Ask: What schedule? (daily, weekly, custom cron expression)
3. Add entry to `04-claude-code/cron/crontab.txt`
4. Install with `crontab 04-claude-code/cron/crontab.txt`
5. Confirm with `crontab -l`

### /cron remove
1. Show current jobs (numbered)
2. Ask which to remove
3. Edit `04-claude-code/cron/crontab.txt`
4. Reinstall crontab
5. Confirm removal

### /cron sync
```bash
crontab $KNOWLEDGE_PATH/04-claude-code/cron/crontab.txt
```

## Cron Schedule Reference

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sun=0)
│ │ │ │ │
* * * * * command
```

**Common patterns:**
- `0 6 * * *` — Daily at 6am
- `0 8 * * 0` — Weekly on Sunday at 8am
- `0 9 1 * *` — Monthly on 1st at 9am
- `*/15 * * * *` — Every 15 minutes

## Log Output

All cron jobs should append to a log:
```bash
>> $KNOWLEDGE_PATH/07-logs/.cron.log 2>&1
```
SKILL
fi

# Start cron daemon
cron
echo "✓ Cron daemon started"

# --- Daily digest cron (Grok-powered morning news) ---
DIGEST_HOUR="${DIGEST_CRON_HOUR_UTC:-7}"
if [ -n "$GROK_API_KEY" ]; then
  # Cron runs with minimal env — write required vars to a file and source before running
  ENV_FILE="/etc/daily_digest.env"
  {
    echo "GROK_API_KEY=${GROK_API_KEY}"
    echo "TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN=${TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN}"
    echo "TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID=${TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID}"
    echo "DIGEST_TOPICS=${DIGEST_TOPICS:-}"
    echo "GROK_MODEL=${GROK_MODEL:-grok-4-1-fast}"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  CRON_LINE="0 ${DIGEST_HOUR} * * * . ${ENV_FILE} && /usr/local/bin/python3 /usr/local/bin/daily_digest.py >> /data/knowledge/07-logs/.cron.log 2>&1"
  (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
  echo "✓ Daily digest scheduled at ${DIGEST_HOUR}:00 UTC"
else
  echo "⚠ GROK_API_KEY not set — daily digest disabled"
fi

# --- Clone repos if requested ---
if [ -n "$TAKOPI_REPOS" ]; then
  IFS=',' read -ra REPOS <<< "$TAKOPI_REPOS"
  for repo in "${REPOS[@]}"; do
    name=$(basename "$repo")
    if [ ! -d "/data/github/$name" ]; then
      echo "Cloning $repo..."
      git clone "https://github.com/$repo.git" "/data/github/$name"
    fi
  done
fi

exec "$@"
