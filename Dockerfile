FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --no-dev --no-install-project

COPY src ./src
RUN uv sync --no-dev && uv run python -m morning_news_podcast.voicevox_setup

COPY . .

CMD ["uv", "run", "morning-news-podcast"]
