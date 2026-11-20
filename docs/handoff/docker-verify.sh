#!/usr/bin/env bash
# For a Claude cloud session only: build a checkout of this repo with Docker and see that it answers on port 8080.
# Usage: docker-verify.sh <repo-dir>
# Starts dockerd if needed, builds a local base image (Playwright base + this machine's proxy CA)
# if missing, builds <repo-dir>/Dockerfile against it, runs it, curls http://127.0.0.1:8080/.
# Leaves dockerd and the images in place. Exit 0 on PASS, 1 on FAIL.
set -u
REPO="$(cd "${1:?usage: docker-verify.sh <repo-dir>}" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
UPSTREAM_BASE="${UPSTREAM_BASE:-mcr.microsoft.com/playwright/python:v1.65.2-noble}"
LOCAL_BASE="${LOCAL_BASE:-watchtower-local-base}"
TAG="watchtower-verify:$(basename "$REPO" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_.-]/-/g' | cut -c1-100)"
NAME="watchtower-verify-$$"
PORT=8080

fail() { echo "FAIL: $*"; exit 1; }

# 1. Docker daemon
if ! docker info >/dev/null 2>&1; then
    echo "Starting dockerd (log: $HERE/dockerd.log)"
    nohup dockerd --iptables=false --storage-driver=vfs --bridge=none >"$HERE/dockerd.log" 2>&1 &
    for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
    docker info >/dev/null 2>&1 || fail "dockerd did not start, see $HERE/dockerd.log"
fi

# 2. Local base image: upstream base plus the proxy CA and proxy settings of this machine
if ! docker image inspect "$LOCAL_BASE" >/dev/null 2>&1; then
    echo "Building local base image $LOCAL_BASE from $UPSTREAM_BASE"
    CTX="$(mktemp -d "$HERE/base-ctx.XXXX")"
    cp /root/.ccr/ca-bundle.crt "$CTX/ccr-ca-bundle.crt"
    cat >"$CTX/Dockerfile" <<EOF
FROM $UPSTREAM_BASE
COPY ccr-ca-bundle.crt /usr/local/share/ca-certificates/ccr-ca-bundle.crt
RUN update-ca-certificates
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \\
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \\
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \\
    HTTPS_PROXY=${HTTPS_PROXY:-} \\
    https_proxy=${HTTPS_PROXY:-} \\
    NO_PROXY=${NO_PROXY:-} \\
    no_proxy=${NO_PROXY:-}
EOF
    docker build --network host -t "$LOCAL_BASE" "$CTX" || { rm -rf "$CTX"; fail "local base build failed"; }
    rm -rf "$CTX"
fi

# 3. Build the repo's Dockerfile against the local base
echo "Building $REPO as $TAG"
START=$(date +%s)
docker build --network host --build-arg BASE_IMAGE="$LOCAL_BASE" -t "$TAG" "$REPO" || fail "docker build failed after $(( $(date +%s) - START ))s"
BUILD_SECS=$(( $(date +%s) - START ))

# 4. Run it and check port 8080
if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/"; then
    fail "something already answers on port $PORT; stop it first"
fi
docker run -d --rm --network host --name "$NAME" "$TAG" >/dev/null || fail "docker run failed"
trap 'docker stop "$NAME" >/dev/null 2>&1' EXIT
CODE=000
for _ in $(seq 1 30); do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$PORT/" || true)
    [ "$CODE" = "200" ] && break
    sleep 1
done
if [ "$CODE" = "200" ]; then
    echo "PASS: build ${BUILD_SECS}s, GET http://127.0.0.1:$PORT/ -> 200 (image $TAG)"
    exit 0
fi
echo "--- container log ---"; docker logs "$NAME" 2>&1 | tail -30
fail "build ${BUILD_SECS}s, GET http://127.0.0.1:$PORT/ -> $CODE"
