#!/usr/bin/env python3
"""Daily morning crypto digest powered by free data APIs + AI summarization.

Fetches market data from CoinGecko and news from CryptoPanic, then uses
Claude (primary) or OpenAI (fallback) to generate a morning briefing.

Environment variables:
    ANTHROPIC_API_KEY                         - Anthropic API key (primary AI)
    OPENAI_API_KEY                            - OpenAI API key (fallback AI)
    TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN   - Telegram bot token (required)
    TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID     - Telegram chat ID (required)
    DIGEST_TOPICS                             - Extra topics, comma-separated (optional)

Usage:
    python3 daily_digest.py            # Send digest to Telegram
    python3 daily_digest.py --dry-run  # Print to stdout only
"""

from __future__ import annotations

import json
import logging
import os
import sys
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

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
BOT_TOKEN = os.environ.get("TAKOPI__TRANSPORTS__TELEGRAM__BOT_TOKEN", "")
CHAT_ID = os.environ.get("TAKOPI__TRANSPORTS__TELEGRAM__CHAT_ID", "")
DIGEST_TOPICS = os.environ.get("DIGEST_TOPICS", "")

HEADERS = {"User-Agent": "daily-digest/2.0"}


# ── Data Fetching ────────────────────────────────────────


def _http_get_json(url: str, timeout: int = 15) -> dict | list | None:
    """GET JSON from a URL. Returns None on error."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("HTTP GET failed for %s: %s", url, e)
        return None


def fetch_coingecko_global() -> dict | None:
    """Fetch global crypto market data from CoinGecko."""
    data = _http_get_json("https://api.coingecko.com/api/v3/global")
    if data and "data" in data:
        return data["data"]
    return None


def fetch_coingecko_trending() -> list | None:
    """Fetch trending coins from CoinGecko."""
    data = _http_get_json("https://api.coingecko.com/api/v3/search/trending")
    if data and "coins" in data:
        return data["coins"]
    return None


def fetch_coingecko_top_coins() -> list | None:
    """Fetch top 20 coins by market cap with 24h price change."""
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=20"
        "&sparkline=false&price_change_percentage=24h"
    )
    data = _http_get_json(url)
    if isinstance(data, list):
        return data
    return None


def build_raw_briefing() -> str:
    """Fetch all data sources and build a raw text briefing for AI summarization."""
    sections = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections.append(f"Data collected at: {today}\n")

    # Global market data
    global_data = fetch_coingecko_global()
    if global_data:
        cap = global_data.get("total_market_cap", {}).get("usd", 0)
        cap_change = global_data.get("market_cap_change_percentage_24h_usd", 0)
        btc_dom = global_data.get("market_cap_percentage", {}).get("btc", 0)
        eth_dom = global_data.get("market_cap_percentage", {}).get("eth", 0)
        vol = global_data.get("total_volume", {}).get("usd", 0)
        sections.append(
            f"GLOBAL MARKET DATA:\n"
            f"- Total Market Cap: ${cap / 1e9:,.1f}B ({cap_change:+.1f}% 24h)\n"
            f"- BTC Dominance: {btc_dom:.1f}%\n"
            f"- ETH Dominance: {eth_dom:.1f}%\n"
            f"- 24h Volume: ${vol / 1e9:,.1f}B\n"
        )
    else:
        sections.append("GLOBAL MARKET DATA: unavailable\n")

    # Trending coins
    trending = fetch_coingecko_trending()
    if trending:
        sections.append("TRENDING COINS ON COINGECKO:")
        for i, coin_data in enumerate(trending[:10], 1):
            item = coin_data.get("item", {})
            name = item.get("name", "?")
            symbol = item.get("symbol", "?")
            rank = item.get("market_cap_rank", "?")
            price_btc = item.get("price_btc", 0)
            data_info = item.get("data", {})
            price_change_24h = data_info.get("price_change_percentage_24h", {}).get("usd", 0) if isinstance(data_info, dict) else 0
            sections.append(
                f"  {i}. {name} ({symbol}) — Rank #{rank} — 24h: {price_change_24h:+.1f}%"
            )
        sections.append("")
    else:
        sections.append("TRENDING COINS: unavailable\n")

    # Top coins by market cap (with 24h movers)
    top_coins = fetch_coingecko_top_coins()
    if top_coins:
        sections.append("TOP 10 BY MARKET CAP:")
        for c in top_coins[:10]:
            name = c.get("name", "?")
            symbol = c.get("symbol", "?").upper()
            price = c.get("current_price", 0)
            change = c.get("price_change_percentage_24h", 0) or 0
            mcap = c.get("market_cap", 0)
            sections.append(
                f"  {name} ({symbol}): ${price:,.2f} | 24h: {change:+.1f}% | MCap: ${mcap / 1e9:,.1f}B"
            )
        sections.append("")

        # Biggest movers (gainers/losers)
        sorted_by_change = sorted(
            [c for c in top_coins if c.get("price_change_percentage_24h") is not None],
            key=lambda c: c["price_change_percentage_24h"],
            reverse=True,
        )
        if sorted_by_change:
            top_gainer = sorted_by_change[0]
            top_loser = sorted_by_change[-1]
            sections.append(
                f"BIGGEST MOVERS (top 20):\n"
                f"  🟢 Top gainer: {top_gainer['name']} ({top_gainer['symbol'].upper()}) {top_gainer['price_change_percentage_24h']:+.1f}%\n"
                f"  🔴 Top loser: {top_loser['name']} ({top_loser['symbol'].upper()}) {top_loser['price_change_percentage_24h']:+.1f}%\n"
            )
    else:
        sections.append("TOP COINS: unavailable\n")

    if DIGEST_TOPICS:
        sections.append(f"USER WATCHLIST TOPICS: {DIGEST_TOPICS}\n")

    return "\n".join(sections)


# ── AI Summarization ─────────────────────────────────────

SYSTEM_PROMPT = """\
You are a crypto morning briefing analyst. Given raw market data, trending coins, \
and news headlines, compile a concise daily digest for Telegram.

Format with these sections using emoji headers:
📊 MARKET MOOD: One word (Bullish/Bearish/Neutral/Mixed) + brief reason (1 sentence)
📰 TOP STORIES: 3-5 most important items from the headlines, each as a bullet
🔥 TRENDING: Notable trending coins with brief context
📈 MACRO: Any macro-relevant news (skip if nothing)
👀 WATCHLIST: 3-5 tickers with one-word sentiment tag

Rules:
- Keep total under 1800 characters
- Use plain text with emoji. No markdown links or formatting
- Be factual. Do not speculate or add information not in the data
- If data is sparse, keep the briefing shorter rather than padding"""


def summarize_claude(raw_text: str) -> str | None:
    """Summarize using Anthropic Claude API."""
    if not ANTHROPIC_API_KEY:
        return None

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": f"Here is today's raw crypto market data and news. Create the morning briefing:\n\n{raw_text}"}
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "User-Agent": "daily-digest/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        # Extract text from Claude response
        content = body.get("content", [])
        if content and isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            if texts:
                logger.info("Claude summarization successful")
                return "\n".join(texts).strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.warning("Claude API HTTP %d: %s", e.code, error_body[:300])
    except Exception as e:
        logger.warning("Claude API failed: %s", e)

    return None


def summarize_openai(raw_text: str) -> str | None:
    """Summarize using OpenAI API (fallback)."""
    if not OPENAI_API_KEY:
        return None

    payload = {
        "model": "gpt-4o-mini",
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Here is today's raw crypto market data and news. Create the morning briefing:\n\n{raw_text}"},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "User-Agent": "daily-digest/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
            if text.strip():
                logger.info("OpenAI summarization successful")
                return text.strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.warning("OpenAI API HTTP %d: %s", e.code, error_body[:300])
    except Exception as e:
        logger.warning("OpenAI API failed: %s", e)

    return None


def format_no_ai(raw_text: str) -> str:
    """Simple formatted output when no AI is available."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"📰 Raw Crypto Briefing — {today}\n\n{raw_text[:3500]}"


# ── Telegram ─────────────────────────────────────────────


def send_telegram(text: str) -> bool:
    """Send a message to Telegram. Splits if >4096 chars."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Telegram BOT_TOKEN or CHAT_ID not set")
        return False

    max_len = 4096
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    success = True

    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "daily-digest/2.0"},
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
    text = f"⚠️ Daily Digest Failed\n{error_msg}\nWill retry tomorrow."
    send_telegram(text)


# ── Formatting ───────────────────────────────────────────


def format_digest(summary: str) -> str:
    """Wrap the AI summary with a header and footer."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"📰 Morning Crypto Digest — {today}\n"
    footer = "\n—\nPowered by CoinGecko | AI Summary"

    max_body = 4096 - len(header) - len(footer) - 50
    body = summary[:max_body]
    if len(summary) > max_body:
        body += "..."

    return header + "\n" + body + footer


# ── Main ─────────────────────────────────────────────────


def main():
    dry_run = "--dry-run" in sys.argv

    logger.info("Starting daily digest (dry_run=%s)", dry_run)

    if not dry_run and (not BOT_TOKEN or not CHAT_ID):
        logger.error("Telegram credentials not set — aborting")
        sys.exit(1)

    if not ANTHROPIC_API_KEY and not OPENAI_API_KEY:
        logger.warning("No AI API keys set — will use raw format")

    # Fetch data
    logger.info("Fetching market data...")
    raw_text = build_raw_briefing()
    logger.info("Raw briefing: %d chars", len(raw_text))

    # Summarize with AI (fallback chain)
    summary = None

    if ANTHROPIC_API_KEY:
        logger.info("Attempting Claude summarization...")
        summary = summarize_claude(raw_text)

    if summary is None and OPENAI_API_KEY:
        logger.info("Attempting OpenAI summarization...")
        summary = summarize_openai(raw_text)

    if summary is None:
        logger.warning("All AI summarization failed — using raw format")
        summary = format_no_ai(raw_text)

    # Format
    message = format_digest(summary)

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
        send_error_notice("Failed to send digest message.")
        sys.exit(1)


if __name__ == "__main__":
    main()
