FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies
RUN uv venv && \
    uv pip install --no-cache -e .

# Expose API port
EXPOSE 8000

# Run application
CMD [".venv/bin/uvicorn", "econext_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
