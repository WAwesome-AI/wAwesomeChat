# wAwesomeChat — Podman test image
#
# Build context is the PARENT directory (~/Development/Pytinc), not this repo.
# wAwesomeChat depends on two sibling checkouts through uv path sources:
#
#     [tool.uv.sources]
#     wapyt      = { path = "../wa_pytincture_widgetset" }
#     pytincture = { path = "../pytincture" }
#
# so the image reproduces the workspace layout under /workspace and keeps those
# relative paths resolvable. Build it with scripts/podman_build.sh, or by hand:
#
#     podman build --format docker -f wAwesomeChat/Containerfile \
#         -t localhost/wawesomechat:latest ~/Development/Pytinc
#
# --format docker is required for the HEALTHCHECK below; podman drops the field
# on an OCI-format build without warning.

FROM docker.io/library/python:3.13-slim AS base

# 3.13 because pytincture declares requires-python >=3.13,<3.15. The host runs
# 3.14; either satisfies every package here, but 3.13 matches what the published
# wheels are most exercised against.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache

# curl is for the HEALTHCHECK and for poking at the service while debugging.
#
# Deliberately NOT installed: build-essential, pkg-config, libxml2-dev,
# libxmlsec1-dev, libffi-dev. The old Dockerfile pulled all of those for
# xmlsec/SAML, but nothing in this app's dependency graph needs them --
# pytincture only requires xmlsec under its optional `saml` extra, which
# wAwesomeChat does not install. Dropping them removes several minutes and
# a few hundred MB. Add them back if you ever enable the saml extra.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Pinned to the version in use on the host, so a container build and a local
# `uv sync` resolve identically.
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv

WORKDIR /workspace

# Copied as three separate layers, cheapest-to-change last: pytincture and the
# widgetset move far less often than the app.
COPY pytincture/ /workspace/pytincture/
COPY wa_pytincture_widgetset/ /workspace/wa_pytincture_widgetset/
COPY wAwesomeChat/ /workspace/wAwesomeChat/

# Build the wapyt development wheel into the modules folder.
#
# This is not optional packaging polish -- it is how the widgetset reaches the
# browser at all. pytincture micropip-installs a *wheel* served from
# modules_folder; a source checkout on disk is invisible to it. The wheel is
# built at PYTINCTURE_DEV_WHEEL_VERSION (99.99.99) and carries a
# pytincture-assets.json whose SHA-256 entries are verified per file before any
# JS is evaluated, so building it here (rather than copying a stale one in)
# guarantees the manifest matches the assets in this image.
RUN /workspace/wa_pytincture_widgetset/scripts/dev_wheel.sh \
        /workspace/wAwesomeChat/src/wawesomechat

WORKDIR /workspace/wAwesomeChat

# --no-dev: the dev extra is pytest/ruff, which the test image does not run.
RUN uv sync --no-dev && rm -rf /tmp/uv-cache

# Bake the Whisper model into the image so the container never reaches for the
# network on first use, and so a cold start is not a 150MB download. base.en on
# CPU int8 is fast enough for push-to-talk clips and leaves the GPU entirely to
# LM Studio, which on this box is already holding most of the 12GB.
ENV WHISPER_MODEL=base.en \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE=int8 \
    WHISPER_CACHE=/app/models/whisper
RUN mkdir -p /app/models/whisper && \
    uv run python -c "\
from faster_whisper import WhisperModel; \
WhisperModel('base.en', device='cpu', compute_type='int8', download_root='/app/models/whisper')"

# pytincture ships Permissions-Policy: microphone=() -- a browser-level block on
# getUserMedia that no amount of user consent overrides. Voice input needs it
# relaxed to self. Everything else stays denied.
ENV PYTINCTURE_PERMISSIONS_POLICY="camera=(), microphone=(self), geolocation=(), payment=()"

# SQLite lives on a volume so provider records and (once persistence is fixed)
# transcripts survive `podman rm`. WA_DB_FILE is absolute, so config.py uses it
# verbatim instead of resolving it under the package directory.
ENV WA_DB_FILE=/data/wawesomechat.db
VOLUME /data

# 8070 is not configurable from the environment. chat.py calls
# launch_service(modules_folder=...) with no port argument, and launch_service
# defaults to 8070; pytincture never reads a PORT variable. The old Dockerfile's
# `ENV PORT=8080` and fly.toml's `PORT = '8070'` are both inert -- the listener
# has always been 8070. Remap on the host side with -p instead.
EXPOSE 8070

# Do not set ENABLE_USER_LOGIN + ENABLE_DEV_EMAIL_LOGIN, or
# PYTINCTURE_ALLOW_DEVELOPMENT_AUTH_ORIGIN, in this container. pytincture's
# _loopback_bind_host() forces a 127.0.0.1 bind when development auth is on,
# which inside a container means the published port answers nothing -- and if a
# non-loopback host is also passed it raises outright. Without those flags the
# default bind is 0.0.0.0, which is what a container needs.

# start-period covers uvicorn plus a cold litellm import, which is the slow part
# (~10s). The probe hits the real app route, not just the port: a 200 on /chat
# means pytincture resolved the entrypoint and is serving the page shell.
# It does NOT prove the browser-side Pyodide boot succeeded -- nothing
# server-side can. See CLAUDE.md for the lifecycle-stage check.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fs -o /dev/null http://localhost:8070/chat || exit 1

COPY wAwesomeChat/scripts/container_entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
