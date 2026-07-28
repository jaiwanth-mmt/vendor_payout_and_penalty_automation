#!/bin/sh
set -eu

# Named volumes are root-owned on first mount; the API writes job artifacts here.
mkdir -p /app/backend/.runtime
chown -R appuser:appuser /app/backend/.runtime

exec runuser -u appuser -- "$@"
