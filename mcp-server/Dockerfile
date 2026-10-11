FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install the MCP SDK version validated by GitHub Actions.
RUN python -m pip install --no-cache-dir "mcp==2.3.0"

# Copy the tested MCP server.
COPY server.py /app/server.py

# Run as a non-root user.
USER 10001:10001

EXPOSE 8080

CMD ["python", "server.py"]
