#!/bin/bash
# Listen on the Rapsodo USB bulk IN endpoint while you physically trigger the unit.
cd "$(dirname "$0")"
SECS="${1:-60}"
echo "Listening for ${SECS}s. While this runs, wave your hand in front of the"
echo "unit's lens, or swing something past it, so it has something to detect."
echo
exec ./.venv/bin/python tools/usbprobe.py listen "$SECS"
