#!/bin/sh
# Wrapper script to run the onenote-dump-mcp server from the correct directory

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$PROJECT_DIR" || exit 1

echo "Executing 'poetry run onenote-dump-mcp' in $PROJECT_DIR" >&2
exec poetry run onenote-dump-mcp
