FROM python:3.12-slim

# Stdlib-only runtime: no pip installs, no build dependencies, no network at build.
WORKDIR /app
COPY travelpayouts_mcp ./travelpayouts_mcp

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Token / marker / trs are provided at runtime (env or Docker MCP secrets).
ENTRYPOINT ["python", "-m", "travelpayouts_mcp"]
