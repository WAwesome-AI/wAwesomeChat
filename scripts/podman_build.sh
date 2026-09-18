#!/usr/bin/env bash
# Build the wAwesomeChat test image.
#
#   scripts/podman_build.sh              # build if needed
#   scripts/podman_build.sh --no-cache   # force a clean rebuild
#
# The build context is the PARENT of this repo, because wAwesomeChat resolves
# wapyt and pytincture through uv path sources pointing at sibling checkouts.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"
IMAGE="${WA_IMAGE:-localhost/wawesomechat:latest}"

for sibling in pytincture wa_pytincture_widgetset; do
    if [ ! -d "${WORKSPACE_ROOT}/${sibling}" ]; then
        echo "missing sibling checkout: ${WORKSPACE_ROOT}/${sibling}" >&2
        echo "wAwesomeChat builds against local clones of pytincture and the widgetset." >&2
        exit 1
    fi
done

# podman reads .containerignore from the context root, but ours lives with the
# Containerfile in this repo. Stage it into the context for the build and put
# the directory back exactly as it was afterwards -- including restoring any
# pre-existing file rather than deleting one that was not ours.
STAGED_IGNORE="${WORKSPACE_ROOT}/.containerignore"
BACKUP=""
if [ -e "${STAGED_IGNORE}" ]; then
    BACKUP="$(mktemp)"
    cp "${STAGED_IGNORE}" "${BACKUP}"
fi
cleanup() {
    if [ -n "${BACKUP}" ]; then
        mv "${BACKUP}" "${STAGED_IGNORE}"
    else
        rm -f "${STAGED_IGNORE}"
    fi
}
trap cleanup EXIT
cp "${REPO_ROOT}/.containerignore" "${STAGED_IGNORE}"

echo "building ${IMAGE}"
echo "  context:       ${WORKSPACE_ROOT}"
echo "  containerfile: ${REPO_ROOT}/Containerfile"

# --format docker: podman silently drops HEALTHCHECK on an OCI-format build.
podman build \
    --format docker \
    -f "${REPO_ROOT}/Containerfile" \
    -t "${IMAGE}" \
    "$@" \
    "${WORKSPACE_ROOT}"

echo
echo "built ${IMAGE} -- run it with scripts/podman_run.sh"
