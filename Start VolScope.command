#!/bin/bash
# Fallback launcher — only needed if double-clicking VolScope.app is blocked.
# Runs the exact same thing VolScope.app does.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/VolScope.app/Contents/MacOS/VolScope"
