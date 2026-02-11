#!/usr/bin/env python3
"""Daily morning news digest powered by Grok API with live X + web search.

Standalone cron script. Queries xAI Grok with x_search and web_search tools
for a Crypto Twitter / news digest, then sends it to Telegram.

Environment variables:
    GROK_API_KEY                              - xAI API key (required)
    TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN   - Telegram bot token (required)
    TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID     - Telegram chat ID (required)
    DIGEST_TOPICS                             - Extra topics, comma-separated (optional)
    GROK_MODEL                                - Model override (default: grok-4-1-fast)

Usage:
    python3 daily_digest.py            # Send digest to Telegram
    python3 daily_digest.py --dry-run  # Print to stdout only
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("daily_digest")

# ── Configuration ────────────────────────────────────────

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
BOT_TOKEN = os.environ.get("TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN", "")
CHAT_ID = os.environ.get("TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID", "")
DIGEST_TOPICS = os.environ.get("DIGEST_TOPICS", "")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4-1-fast")

GROK_API_URL = "https://api.x.ai/v1/responses"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

SYSTEM_PROMPT = """\
You are a crypto and financial markets morning briefing analyst with real-time \
access to X (Twitter) and the web. Compile a concise daily digest covering:

1. MARKET MOOD: Overall Crypto Twitter sentiment in one word (Bullish / Bearish / \
Neutral / Mixed) plus a brief reason (1 sentence).

2. TOP STORIES: The 3-5 most important crypto/web3 developments from the last 24 hours. \
Each story gets one bullet with a short headline and 1-sentence summary.

3. CT PULSE: 2-3 notable tweets, threads, or discussions from key crypto accounts on X. \
Include the @handle and a brief summary of what they said.

4. MACRO: Any relevant macro/TradFi news that could affect crypto markets (interest rates, \
regulation, institutional moves). Skip if nothing significant.

5. WATCHLIST: Tokens or projects seeing unusual social buzz (positive or negative). \
List 3-5 tickers with a one-word sentiment tag.

Rules:
- Keep total response under 2000 characters (Telegram readability).
- Use plain text with emoji for section headers. No markdown links.
- Be factual and source-attributed. Do not speculate.
- Current UTC date: {date}
"""


def build_user_message() -> str:
    """Build the user message requesting the digest."""
    base = "Give me today's crypto morning briefing. Search X for the latest crypto discussions and search the web for breaking crypto news from the last 24 hours."
    if DIGEST_TOPICS:
        base += f" Pay special attention to these topics: {DIGEST_TOPICS}."
    return base


# ── Grok API ─────────────────────────────────────────────


def query_grok() -> str | None:
    """Call the Grok Responses API with x_search + web_search tools."""
    if not GROK_API_KEY:
        logger.error("GROK_API_KEY not set")
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "model": GROK_MODEL,
        "temperature": 0.3,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT.format(date=today)},
            {"role": "user", "content": build_user_message()},
        ],
        "tools": [
            {"type": "x_search"},
            {"type": "web_search"},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROK_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROK_API_KEY}",
            "User-Agent": "daily-digest/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.error("Grok API HTTP %d: %s", e.code, error_body[:500])
        return None
    except Exception as e:
        logger.error("Grok API request failed: %s", e)
        return None

    return _extract_text(body)


def _extract_text(body: dict) -> str | None:
    """Extract the final text from the Grok Responses API output.

    The Responses API returns an 'output' array. We look for items
    with type 'message' containing 'content' sub-items of type 'output_text'.
    Falls back to OpenAI-compatible format if needed.
    """
    # Try Responses API format: output[].type=="message" -> content[].type=="output_text"
    output = body.get("output")
    if isinstance(output, list):
        for item in output:
            if item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, list):
                    texts = [
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "output_text"
                    ]
                    if texts:
                        return "\n".join(texts).strip()
                # content might be a string directly
                if isinstance(content, str) and content.strip():
                    return content.strip()

    # Fallback: output_text at top level
    if isinstance(output, list):
        for item in output:
            if item.get("type") == "output_text":
                text = item.get("text", "")
                if text.strip():
                    return text.strip()

    # Fallback: OpenAI chat completion format
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        text = msg.get("content", "")
        if text.strip():
            return text.strip()

    logger.error("Could not extract text from Grok response: %s", json.dumps(body)[:500])
    return None


# ── Telegram ─────────────────────────────────────────────


def send_telegram(text: str) -> bool:
    """Send a message to Telegram. Splits if >4096 chars."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Telegram BOT_TOKEN or CHAT_ID not set")
        return False

    # Telegram max message length
    max_len = 4096
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a good split point
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    url = TELEGRAM_API_URL.format(token=BOT_TOKEN)
    success = True

    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "daily-digest/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("ok"):
                    logger.error("Telegram API error: %s", result)
                    success = False
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            success = False

    return success


def send_error_notice(error_msg: str):
    """Send a brief error notification to Telegram."""
    text = f"\u26a0\ufe0f <b>Daily Digest Failed</b>\n{error_msg}\nWill retry tomorrow."
    send_telegram(text)


# ── Formatting ───────────────────────────────────────────


def format_digest(raw_text: str) -> str:
    """Wrap the Grok response with a header and footer."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"\U0001f4f0 <b>Morning Crypto Digest</b> \u2014 {today}\n"
    footer = "\n\u2014\n<i>Powered by Grok | Data from X &amp; Web</i>"

    # Truncate if needed (leave room for header + footer)
    max_body = 4096 - len(header) - len(footer) - 50
    body = raw_text[:max_body]
    if len(raw_text) > max_body:
        body += "..."

    return header + "\n" + body + footer


# ── Main ─────────────────────────────────────────────────


def main():
    dry_run = "--dry-run" in sys.argv

    logger.info("Starting daily digest (dry_run=%s, model=%s)", dry_run, GROK_MODEL)

    # Validate required env vars (unless dry-run without API key)
    if not GROK_API_KEY:
        logger.error("GROK_API_KEY not set — aborting")
        sys.exit(1)
    if not dry_run and (not BOT_TOKEN or not CHAT_ID):
        logger.error("Telegram credentials not set — aborting")
        sys.exit(1)

    # Query Grok with retry
    text = query_grok()
    if text is None:
        logger.warning("First attempt failed, retrying in 10s...")
        time.sleep(10)
        text = query_grok()

    if text is None:
        logger.error("Grok query failed after retry")
        if not dry_run:
            send_error_notice("Grok API returned no response after 2 attempts.")
        sys.exit(1)

    # Format
    message = format_digest(text)

    if dry_run:
        print("=" * 60)
        print(message)
        print("=" * 60)
        print(f"\nLength: {len(message)} chars")
        logger.info("Dry run complete")
        return

    # Send to Telegram
    if send_telegram(message):
        logger.info("Digest sent successfully (%d chars)", len(message))
    else:
        logger.error("Failed to send digest to Telegram")
        sys.exit(1)


if __name__ == "__main__":
    main()
