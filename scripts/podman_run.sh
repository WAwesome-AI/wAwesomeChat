#!/usr/bin/env bash
# Run the wAwesomeChat test container.
#
#   scripts/podman_run.sh                 # → http://127.0.0.1:8070/chat
#   scripts/podman_run.sh --port 9000     # publish on a different host port
#   scripts/podman_run.sh --dev           # bind-mount source; edits are live
#   scripts/podman_run.sh --fg            # run in the foreground, logs to stdout
#   scripts/podman_run.sh --rebuild       # rebuild the image first
#   scripts/podman_run.sh --shell         # drop into a shell instead of the app
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"
IMAGE="${WA_IMAGE:-localhost/wawesomechat:latest}"
CONTAINER_NAME="${WA_CONTAINER:-wawesomechat}"
VOLUME_NAME="${WA_VOLUME:-wawesomechat-data}"
HOST_PORT=8070
DEV=0
FOREGROUND=0
REBUILD=0
SHELL_MODE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --port)    HOST_PORT="${2:?--port needs a value}"; shift 2 ;;
        --dev)     DEV=1; shift ;;
        --fg)      FOREGROUND=1; shift ;;
        --rebuild) REBUILD=1; shift ;;
        --shell)   SHELL_MODE=1; FOREGROUND=1; shift ;;
        -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
        *)         echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ "${REBUILD}" = "1" ] || ! podman image exists "${IMAGE}"; then
    "${REPO_ROOT}/scripts/podman_build.sh"
fi

# Replace any container with this name, running or not.
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    podman rm -f "${CONTAINER_NAME}" >/dev/null
fi

ARGS=(
    --name "${CONTAINER_NAME}"
    # Bind IPv4 loopback explicitly rather than 0.0.0.0. Two reasons:
    #
    # 1. On this host `localhost` resolves to ::1 first, and rootless podman's
    #    pasta networking does not forward IPv6 loopback here -- a plain
    #    `--publish 8070:8070` leaves http://localhost:8070 dead while
    #    http://127.0.0.1:8070 works. Verified 2026-09-17.
    # 2. A test container holding real provider API keys has no business
    #    listening on the LAN.
    --publish "127.0.0.1:${HOST_PORT}:8070"
    --volume "${VOLUME_NAME}:/data"
)

# Credentials are passed as real environment variables, never copied into the
# image. config.py reads them with os.getenv, and its load_dotenv() call is a
# no-op when no file is present -- so an --env-file works without any .env
# existing inside the container.
#
# src/.env is the path config.py actually resolves (PACKAGE_ROOT.parent), which
# is neither the repo root where .env.example lives nor src/wawesomechat/.env
# where push_fly_secrets.py points. Prefer it, fall back to the repo root.
ENV_FILE=""
for candidate in "${REPO_ROOT}/src/.env" "${REPO_ROOT}/.env"; do
    if [ -f "${candidate}" ]; then ENV_FILE="${candidate}"; break; fi
done
if [ -n "${ENV_FILE}" ]; then
    echo "env-file: ${ENV_FILE}"
    ARGS+=(--env-file "${ENV_FILE}")
else
    echo "env-file: none found (src/.env or .env) -- the app will start, but"
    echo "          every provider call will fail with an authentication error."
fi

# LM Studio (and anything else on the host) needs its base URL rewritten for the
# container's view of the world: "localhost" inside the container is the
# container. Rootless podman exposes the host as host.containers.internal.
#
# Two caveats, both verified 2026-09-17:
#  - A host service bound to 127.0.0.1 is NOT reachable this way (connection
#    fails outright). LM Studio binds loopback by default, so its
#    "Serve on Local Network" toggle must be on for the container to reach it.
#  - This rewrite is applied as an explicit --env AFTER --env-file, so it wins.
if [ -n "${ENV_FILE}" ] && grep -q '^LM_STUDIO_API_BASE=.\+' "${ENV_FILE}" 2>/dev/null; then
    HOST_BASE="$(grep '^LM_STUDIO_API_BASE=' "${ENV_FILE}" | tail -1 | cut -d= -f2-)"
    CONTAINER_BASE="${HOST_BASE//localhost/host.containers.internal}"
    CONTAINER_BASE="${CONTAINER_BASE//127.0.0.1/host.containers.internal}"
    if [ "${CONTAINER_BASE}" != "${HOST_BASE}" ]; then
        echo "lm studio: ${HOST_BASE} -> ${CONTAINER_BASE}"
        ARGS+=(--env "LM_STUDIO_API_BASE=${CONTAINER_BASE}")
    fi
fi

if [ "${DEV}" = "1" ]; then
    # Mount the live checkouts over the baked-in copies. The wheel built into
    # the image no longer matches the mounted widgetset source, and pytincture
    # verifies every asset's SHA-256 against the wheel manifest before running
    # it, so the entrypoint rebuilds the wheel on start.
    #
    # :z relabels for SELinux, which is enforcing on Bazzite -- without it the
    # container gets permission denied on every mounted path.
    echo "dev mode: bind-mounting source (wheel rebuilt at startup)"
    ARGS+=(
        --volume "${REPO_ROOT}/src:/workspace/wAwesomeChat/src:z"
        --volume "${WORKSPACE_ROOT}/wa_pytincture_widgetset:/workspace/wa_pytincture_widgetset:z"
        --env WA_REBUILD_WIDGETSET=1
    )
fi

if [ "${SHELL_MODE}" = "1" ]; then
    echo "starting shell in ${IMAGE}"
    exec podman run --rm -it "${ARGS[@]}" --entrypoint /bin/bash "${IMAGE}"
fi

if [ "${FOREGROUND}" = "1" ]; then
    exec podman run --rm -it "${ARGS[@]}" "${IMAGE}"
fi

podman run --detach "${ARGS[@]}" "${IMAGE}" >/dev/null
echo
echo "wAwesomeChat → http://127.0.0.1:${HOST_PORT}/chat"
echo "  (use 127.0.0.1, not localhost -- see the --publish note in this script)"
echo "  logs:    podman logs -f ${CONTAINER_NAME}"
echo "  health:  podman inspect --format '{{.State.Health.Status}}' ${CONTAINER_NAME}"
echo "  stop:    podman rm -f ${CONTAINER_NAME}"
echo
echo "A 200 on /chat only means the page shell is served. To confirm the app"
echo "actually booted in the browser, open it and check the console -- or run"
echo "the Playwright lifecycle check described in CLAUDE.md."
