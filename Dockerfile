FROM ghcr.io/astral-sh/uv:python3.14-bookworm

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm git curl cron && rm -rf /var/lib/apt/lists/*

# Install engine CLIs
RUN npm install -g @anthropic-ai/claude-code @openai/codex

# Install takopi
RUN uv tool install takopi

# Persistent data mount point
WORKDIR /data/github

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["takopi"]
