#!/usr/bin/env python3
"""Watch USB continuously for ANY change while you try recovery combinations.

Goal: get the unit to enumerate as something OTHER than 0x4003:0x0002.
The prize is ST's ROM DFU bootloader, 0x0483:0xDF11 — it lives in silicon,
cannot be erased, and if we can reach it we can flash BB1.bin with the free
dfu-util and never open the case.

    python3 tools/usbwatch.py            # watch until Ctrl-C
    python3 tools/usbwatch.py --secs 300

Leave this running, then work through the recovery sequences. Every appearance,
disappearance or VID/PID change is timestamped so you can tell which action did
it. Uses ioreg, because `system_profiler SPUSBDataType` returns nothing here.
"""
import argparse, re, subprocess, sys, time
from datetime import datetime

RAPSODO = (0x4003, 0x0002)
INTERESTING = {
    (0x0483, 0xDF11): "*** ST ROM DFU BOOTLOADER *** <- THE PRIZE: flash with dfu-util",
    (0x0483, 0x5740): "STM32 virtual COM port",
    (0x0483, 0x3748): "ST-LINK debug probe",
}


def snapshot():
    out = subprocess.run("ioreg -p IOUSB -w0 -l", shell=True,
                         capture_output=True, text=True).stdout
    devs, cur = [], None
    for line in out.splitlines():
        if "+-o" in line:
            if cur: devs.append(cur)
            cur = {}
        if cur is None: continue
        for k in ("USB Product Name", "USB Vendor Name", "idVendor", "idProduct"):
            m = re.search(r'"%s"\s*=\s*"?([^"\n]+)"?' % re.escape(k), line)
            if m: cur[k] = m.group(1).strip()
    if cur: devs.append(cur)
    out_set = {}
    for d in devs:
        if not d.get("USB Product Name"): continue
        try:
            vid, pid = int(d.get("idVendor", -1)), int(d.get("idProduct", -1))
        except ValueError:
            continue
        key = (vid, pid, d["USB Product Name"])
        out_set[key] = out_set.get(key, 0) + 1
    return out_set


def label(vid, pid, name):
    tag = INTERESTING.get((vid, pid))
    base = f"{name}  [{vid:#06x}:{pid:#06x}]"
    if tag:   return f"{base}\n        {tag}"
    if (vid, pid) == RAPSODO: return f"{base}  <- the Rapsodo, normal mode"
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=0, help="0 = until Ctrl-C")
    ap.add_argument("--interval", type=float, default=0.4)
    a = ap.parse_args()

    print("Watching USB. Try the recovery sequences now — every change is timestamped.")
    print("Looking for ANY new VID:PID, especially 0x0483:0xdf11 (ST ROM DFU).\n")
    prev = snapshot()
    rap = [k for k in prev if (k[0], k[1]) == RAPSODO]
    print(f"baseline: {sum(prev.values())} devices; "
          f"Rapsodo {'PRESENT' if rap else 'absent'}\n")

    end = time.time() + a.secs if a.secs else None
    changes = 0
    try:
        while end is None or time.time() < end:
            time.sleep(a.interval)
            now = snapshot()
            if now == prev:
                continue
            ts = datetime.now().strftime("%H:%M:%S")
            for k in now:
                if now[k] > prev.get(k, 0):
                    changes += 1
                    print(f"[{ts}] + APPEARED  {label(*k)}")
            for k in prev:
                if prev[k] > now.get(k, 0):
                    changes += 1
                    print(f"[{ts}] - GONE      {label(*k)}")
            prev = now
    except KeyboardInterrupt:
        pass
    print(f"\n{changes} change(s) observed.")
    if any((v, p) in INTERESTING for v, p, _ in prev):
        print("A recovery-mode device is PRESENT RIGHT NOW — stop and report this.")


main()
