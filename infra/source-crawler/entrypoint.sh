#!/bin/sh
set -eu

raw_dir="${MINNE_RAW_DIR:-/app/knowledge/raw}"
mkdir -p "$raw_dir"
if [ ! -w "$raw_dir" ]; then
    echo "source-crawler: raw directory is not writable: $raw_dir" >&2
    exit 1
fi

echo "source-crawler: upgrading database schema"
python -m alembic upgrade head
echo "source-crawler: starting pipeline"
exec "$@"
