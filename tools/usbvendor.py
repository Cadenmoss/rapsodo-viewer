#!/usr/bin/env python3
"""Sweep VENDOR control requests in the DEVICE-TO-HOST (IN) direction only.

bmRequestType 0xC0 = vendor | device-to-host | device recipient.
These ASK the device for data rather than writing to it.

0xA0 is EXCLUDED unconditionally: on EZ-USB-style parts it is the firmware
load/RAM-write request. Nothing here uses bmRequestType 0x40 (host-to-device).
"""
import json, os, sys, time
try:
    import usb.core, usb.util
except ImportError:
    sys.exit("pyusb missing")

VID, PID = 0x4003, 0x0002
FORBIDDEN = {0xA0}
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "findings")

def hexdump(b, width=16):
    return "\n".join(
        f"    {i:04x}  {' '.join(f'{x:02x}' for x in b[i:i+width]):<{width*3}} "
        f"|{''.join(chr(x) if 32<=x<127 else '.' for x in b[i:i+width])}|"
        for i in range(0, min(len(b), 256), width))

d = usb.core.find(idVendor=VID, idProduct=PID)
if d is None:
    sys.exit("device not found")
d.set_configuration()

results, hits = [], []
# 0xC0 = device recipient, 0xC1 = interface recipient - both IN direction
for bmRT in (0xC0, 0xC1):
    print(f"\n=== bmRequestType 0x{bmRT:02x} (vendor, device-to-host) ===")
    for req in range(0x00, 0x100):
        if req in FORBIDDEN:
            print(f"  req 0x{req:02x}  SKIPPED (firmware-write request)")
            continue
        try:
            r = d.ctrl_transfer(bmRT, req, 0, 0, 64, timeout=400)
        except usb.core.USBError:
            continue
        except Exception:
            continue
        b = bytes(r)
        if b:
            hits.append({"bmRequestType": bmRT, "bRequest": req, "len": len(b), "hex": b.hex()})
            print(f"  req 0x{req:02x}  *** {len(b)} BYTES ***")
            print(hexdump(b))
        results.append({"bmRequestType": bmRT, "bRequest": req, "len": len(b)})

os.makedirs(OUT_DIR, exist_ok=True)
p = os.path.join(OUT_DIR, f"usbvendor-{int(time.time())}.json")
json.dump({"hits": hits, "all": results}, open(p, "w"), indent=2)
print(f"\n{len(hits)} vendor requests returned data (out of {len(results)} that did not error)")
print(f"log -> {p}")
