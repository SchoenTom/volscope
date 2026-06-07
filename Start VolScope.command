#!/bin/bash
# First-run launcher for VolScope.
#
# A GitHub ZIP download strips the "executable" flag from files, so the very
# first launch can't be a double-click — run this once instead, with:
#     bash "Start VolScope.command"
# It runs VolScope's launch logic via `bash` (which ignores the missing flag)
# and that logic self-heals the VolScope.app bundle (restores the flag, clears
# the download quarantine, ad-hoc signs it), so EVERY launch after this one is
# a normal double-click on the VolScope.app icon.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/scripts/ops/launch_app.sh"
