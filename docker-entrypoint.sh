#!/bin/sh
# Starts as root only long enough to hand the data volume to the unprivileged
# `anamna` account, then drops to it for good. A container started with
# `--user` is already unprivileged and skips straight to the command.
set -eu

if [ "$(id -u)" = "0" ]; then
    data_dir="$(dirname "${ANAMNA_DB:-/data/anamna.sqlite3}")"
    sources_dir="${ANAMNA_SOURCES:-/data/sources}"
    mkdir -p "$data_dir" "$sources_dir"
    writable=1
    for dir in "$data_dir" "$sources_dir"; do
        # Only when something is not ours already: a recursive chown of a large
        # archive on every start would be slow for no reason.
        if [ -n "$(find "$dir" ! -user anamna -print -quit)" ]; then
            chown -R anamna:anamna "$dir" 2>/dev/null || writable=0
        fi
    done
    if [ "$writable" = "1" ]; then
        exec setpriv --reuid=anamna --regid=anamna --init-groups "$@"
    fi
    # Some network shares refuse chown. Staying root there is what every
    # earlier image did, and is better than a container that cannot start.
    echo "anamna: could not take ownership of the data directory; continuing as root" >&2
fi

exec "$@"
