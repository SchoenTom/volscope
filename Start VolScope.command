#!/bin/bash
# First-run launcher for VolScope.
#
# A GitHub ZIP download strips the "executable" flag from files, so the very
# first launch can't be a double-click — it goes through this script once
# (run it with: bash "Start VolScope.command"). It runs the app's bootstrap
# via `bash`, which doesn't need the executable flag, and the bootstrap then
# re-sets that flag so every launch AFTER this one is a normal double-click on
# VolScope.app.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/VolScope.app/Contents/MacOS/VolScope"
