#!/bin/bash
# Reliable USB enumeration check for the Rapsodo unit.
#
#   bash tools/usbcheck.sh baseline   # snapshot BEFORE plugging the unit in
#   bash tools/usbcheck.sh check      # snapshot AFTER, show what is genuinely new
#   bash tools/usbcheck.sh cable      # how to test a micro-USB cable for data lines
#
# Uses ioreg, NOT `system_profiler SPUSBDataType`, which returns zero bytes on
# this machine and silently reports "no devices" whatever is attached.
#
# Comparison is done on a SORTED MULTISET of (vendor, product, ids) - not a
# line diff of the ioreg tree, whose ordering and indentation shift between
# runs and produced false "new device" reports.

DIR="${TMPDIR:-/tmp}/rapsodo-usb"
mkdir -p "$DIR"

snap() {
python3 - "$1" <<'PY'
import re, subprocess, sys, json
out = subprocess.run("ioreg -p IOUSB -w0 -l", shell=True, capture_output=True, text=True).stdout
devs, cur = [], None
for line in out.splitlines():
    if "+-o" in line:
        if cur: devs.append(cur)
        cur = {}
    if cur is None: continue
    for k in ("USB Product Name","USB Vendor Name","idVendor","idProduct","USB Serial Number"):
        m = re.search(r'"%s"\s*=\s*"?([^"\n]+)"?' % re.escape(k), line)
        if m: cur[k] = m.group(1).strip()
if cur: devs.append(cur)
devs = [d for d in devs if d.get("USB Product Name")]
key = lambda d: "%s|%s|%s:%s" % (d.get("USB Vendor Name","?"), d["USB Product Name"],
                                 d.get("idVendor","?"), d.get("idProduct","?"))
json.dump(sorted(key(d) for d in devs), open(sys.argv[1],"w"), indent=1)
print(len(devs))
PY
  ls /dev/cu.* /dev/tty.* 2>/dev/null | sort > "$1.tty"
  ifconfig 2>/dev/null | grep -E "^en[0-9]+:" | cut -d: -f1 | sort > "$1.net"
}

case "$1" in
  baseline)
    N=$(snap "$DIR/before")
    echo "baseline: $N USB devices, $(wc -l < "$DIR/before.tty"|tr -d ' ') serial ports, $(wc -l < "$DIR/before.net"|tr -d ' ') net interfaces"
    echo
    echo "Plug the Rapsodo DIRECTLY INTO THE MAC (not a hub - hub charging"
    echo "ports often have no data lines). Wait 10s, then:"
    echo "  bash tools/usbcheck.sh check"
    ;;
  check)
    [ -f "$DIR/before" ] || { echo "No baseline. Run: bash tools/usbcheck.sh baseline"; exit 1; }
    N=$(snap "$DIR/after")
    python3 - "$DIR/before" "$DIR/after" <<'PY'
import json, sys
from collections import Counter
b = Counter(json.load(open(sys.argv[1])))
a = Counter(json.load(open(sys.argv[2])))
new, gone = a - b, b - a
print(f"=== USB: {sum(b.values())} before -> {sum(a.values())} now ===")
if new:
    print("NEW devices:")
    for k, n in new.items(): print(f"   +{n}  {k}")
else:
    print("  no new USB devices")
if gone:
    print("disappeared:")
    for k, n in gone.items(): print(f"   -{n}  {k}")
PY
    echo
    echo "=== NEW serial ports ==="
    diff "$DIR/before.tty" "$DIR/after.tty" 2>/dev/null | grep '^>' | sed 's/^> /  /' || echo "  (none)"
    echo "=== NEW network interfaces ==="
    diff "$DIR/before.net" "$DIR/after.net" 2>/dev/null | grep '^>' | sed 's/^> /  /' || echo "  (none)"
    ;;
  cable)
    echo "MICRO-USB CABLE TEST"
    echo
    echo "Plug a device you KNOW does data over micro-USB (PS4/Xbox controller,"
    echo "old Android phone, Kindle, camera, card reader) into the Mac using the"
    echo "cable under test:"
    echo "  1. bash tools/usbcheck.sh baseline   (with that device UNPLUGGED)"
    echo "  2. plug the known device in using the test cable, wait 10s"
    echo "  3. bash tools/usbcheck.sh check"
    echo
    echo "  appears -> cable carries DATA;  nothing -> charge-only cable"
    echo
    echo "Visual: look into the flat USB-A end. Four gold contacts = likely data."
    echo "Only the two OUTER contacts = definitely charge-only."
    ;;
  *) echo "usage: bash tools/usbcheck.sh {baseline|check|cable}"; exit 1 ;;
esac
