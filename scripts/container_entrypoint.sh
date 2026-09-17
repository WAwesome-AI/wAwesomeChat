#!/usr/bin/env bash
# Container entrypoint for wAwesomeChat.
#
# Normally this just execs the app. Its one extra job is supporting the
# bind-mounted dev mode from podman_run.sh --dev: when the widgetset source is
# mounted over the baked-in copy, the wheel built at image-build time no longer
# matches those files, and pytincture fails closed at the widgetset-load stage
# because the SHA-256 manifest no longer verifies. Rebuilding on start keeps the
# mounted source and the served wheel in sync.
set -euo pipefail

WORKSPACE="${WORKSPACE:-/workspace}"
MODULES_DIR="${WORKSPACE}/wAwesomeChat/src/wawesomechat"

if [ "${WA_REBUILD_WIDGETSET:-0}" = "1" ]; then
    echo "[entrypoint] rebuilding wapyt dev wheel from mounted source..."
    "${WORKSPACE}/wa_pytincture_widgetset/scripts/dev_wheel.sh" "${MODULES_DIR}"
fi

# Fail loudly and early rather than letting the browser report an opaque
# widgetset-install error a minute later.
if ! ls "${MODULES_DIR}"/wapyt-*-py3-none-any.whl >/dev/null 2>&1; then
    echo "[entrypoint] FATAL: no wapyt wheel in ${MODULES_DIR}" >&2
    echo "[entrypoint] the browser installs a wheel, not the source checkout;" >&2
    echo "[entrypoint] run scripts/dev_wheel.sh or rebuild the image." >&2
    exit 1
fi

# Keep the database on the /data volume.
#
# The Containerfile sets WA_DB_FILE=/data/wawesomechat.db, but `podman run
# --env-file` OVERRIDES image ENV, and .env.example ships WA_DB_FILE=wawesomechat.db
# (relative). config.py resolves a relative name under the package directory, so
# without this the database silently lands inside the container's writable layer
# and disappears on `podman rm` -- with the volume mounted and empty the whole
# time. Absolute paths are honoured as given; WA_DB_URL wins over both.
if [ -z "${WA_DB_URL:-}" ]; then
    case "${WA_DB_FILE:-}" in
        /*) : ;;
        "") WA_DB_FILE=/data/wawesomechat.db ;;
        *)  WA_DB_FILE="/data/$(basename "${WA_DB_FILE}")" ;;
    esac
    export WA_DB_FILE
fi

# Surface which credentials actually arrived. Never print values -- only whether
# a key is set -- so this stays safe in shared logs. Without this, a bad
# --env-file shows up much later as an in-band LiteLLM auth error rendered as a
# chat message, which reads like an app bug rather than a config one.
echo "[entrypoint] provider credentials present:"
for key in OPENAI_API_KEY ANTHROPIC_API_KEY AWS_ACCESS_KEY_ID GEMINI_API_KEY XAI_API_KEY; do
    if [ -n "${!key:-}" ]; then echo "  ${key}: yes"; else echo "  ${key}: --"; fi
done
echo "[entrypoint] db: ${WA_DB_FILE:-<package default>}"

cd "${WORKSPACE}/wAwesomeChat"
exec uv run --no-sync --directory src/wawesomechat chat.py "$@"
