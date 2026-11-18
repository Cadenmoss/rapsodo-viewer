#!/bin/bash
# Listen for 802.11 frames from the Rapsodo RBB1.0 (Inventek radio).
#
#   sudo bash tools/rfscan.sh [seconds] [interface]
#
# Answers two questions a normal Wi-Fi scan cannot:
#   1. Is the unit broadcasting a HIDDEN network?  -> we'd see its beacons
#   2. Is it hunting for a saved network?          -> its probe requests name the SSID
#
# NOTE: monitor mode briefly disconnects this Mac's Wi-Fi. Your wired
# connection (en0) is unaffected, so you keep internet.

SECS=${1:-45}
IFACE=${2:-en1}
MAC="c4:7f:51:94:70:d7"
OUT="${TMPDIR:-/tmp}/rapsodo-rf.txt"

if [ "$EUID" -ne 0 ]; then
  echo "Needs root for monitor mode. Run:  sudo bash tools/rfscan.sh $SECS $IFACE"; exit 1
fi

echo "Rapsodo RF scan"
echo "  interface : $IFACE"
echo "  target MAC: $MAC"
echo "  duration  : ${SECS}s"
echo "  (Wi-Fi will drop while this runs)"
echo

tcpdump -I -i "$IFACE" -y IEEE802_11_RADIO -e -s 256 -nn -l \
  > "$OUT" 2>"$OUT.err" &
PID=$!
sleep "$SECS"
kill $PID 2>/dev/null; wait $PID 2>/dev/null

if [ ! -s "$OUT" ]; then
  echo "No frames captured. Check $OUT.err :"
  sed -n '1,6p' "$OUT.err"
  echo
  echo "If it says monitor mode is unsupported, this Mac cannot sniff 802.11"
  echo "and we fall back to the UART header or a USB re-test."
  exit 2
fi

TOTAL=$(grep -c . "$OUT" 2>/dev/null || echo 0)
BEACONS=$(grep -c "Beacon" "$OUT" 2>/dev/null || echo 0)
HITS=$(grep -ic -- "$MAC" "$OUT" 2>/dev/null || echo 0)
CHAN=$(system_profiler SPAirPortDataType 2>/dev/null | \
       grep -A3 "Current Network Information" | grep -m1 "Channel:" | sed 's/^ *//')

echo "captured $TOTAL frames ($BEACONS beacons) -> $OUT"
echo "interface was on: ${CHAN:-unknown}"
echo

# --- validity gate: prove the capture COULD have seen something ---
if [ "$TOTAL" -lt 10 ] || [ "$BEACONS" -eq 0 ]; then
  echo "################  CAPTURE FAILED - RESULT IS NOT VALID  ################"
  echo
  echo "Saw $TOTAL frames and $BEACONS beacons. Any location in range of a"
  echo "Wi-Fi network yields hundreds of beacons in ${SECS}s, so this capture"
  echo "was not receiving. This says NOTHING about whether the Rapsodo is"
  echo "transmitting - do not read it as the unit being silent."
  echo
  echo "Most likely causes:"
  echo "  * macOS did not actually hand frames to monitor mode (common on"
  echo "    recent macOS / Apple Silicon - largely unsupported)."
  echo "  * The interface stayed associated on a 5GHz channel. The Rapsodo"
  echo "    radio is 2.4GHz-ONLY, so a 5GHz capture is blind to it by design."
  echo
  echo "To sniff this reliably you need hardware that does monitor mode"
  echo "properly: a USB Wi-Fi adapter in monitor mode on Linux, or an ESP32."
  exit 3
fi

echo "=== Frames involving the Rapsodo ($MAC) ==="
grep -i -- "$MAC" "$OUT" | head -40
echo "  ($HITS matching frames)"
echo
echo "=== Every SSID any device is probing for ==="
grep -o "Probe Request ([^)]*)" "$OUT" | sort | uniq -c | sort -rn | head -25
echo
echo "=== Beacons seen (hidden networks show an empty/blank SSID) ==="
grep -o "Beacon ([^)]*)" "$OUT" | sort | uniq -c | sort -rn | head -25
echo
if [ "$HITS" -eq 0 ]; then
  echo "RESULT: capture was healthy ($TOTAL frames, $BEACONS beacons) but the"
  echo "  Rapsodo sent nothing on this channel. Re-run while associated to a"
  echo "  2.4GHz network before concluding its radio is idle."
else
  echo "RESULT: the unit IS transmitting - see its frames above."
fi
