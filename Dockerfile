FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml .python-version ./
RUN uv sync --no-dev --no-install-project

COPY config.py voicevox_setup.py ./
RUN uv run python voicevox_setup.py

COPY . .

CMD ["uv", "run", "python", "main.py"]
