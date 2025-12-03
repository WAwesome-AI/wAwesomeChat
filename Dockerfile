FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies for xmlsec/SAML + build tooling
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libxml2-dev \
        libxmlsec1-dev \
        libxmlsec1-openssl \
        libffi-dev \
        curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv (used to run the app)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy project files and install the remaining dependencies
COPY . .

EXPOSE 8080

ENTRYPOINT ["uv", "run", "--directory", "src/wawesomechat", "chat.py"]
