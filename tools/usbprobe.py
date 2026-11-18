#!/usr/bin/env python3
"""Probe the Rapsodo RBB1.0 over its vendor-specific USB bulk interface.

Device: VID 0x4003 PID 0x0002 "RAPSODO BB in HS"
  EP 0x81 BULK IN  (512)   <- data from the unit
  EP 0x01 BULK OUT (512)   -> commands to the unit

    python3 tools/usbprobe.py listen [secs]   # read-only: does it push data?
    python3 tools/usbprobe.py info            # descriptors only
    python3 tools/usbprobe.py send <hex>      # WRITE - changes device state

`listen` and `info` are read-only and safe. `send` transmits bytes to the
unit; it asks for confirmation unless --yes is given.
"""
import argparse, binascii, os, sys, time

try:
    import usb.core, usb.util
except ImportError:
    sys.exit("pyusb missing.  pip install pyusb   (and: brew install libusb)")

VID, PID = 0x4003, 0x0002
EP_IN, EP_OUT = 0x81, 0x01
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "findings")


def hexdump(b, width=16, limit=512):
    out = []
    for i in range(0, min(len(b), limit), width):
        c = b[i:i+width]
        h = " ".join(f"{x:02x}" for x in c)
        a = "".join(chr(x) if 32 <= x < 127 else "." for x in c)
        out.append(f"  {i:06x}  {h:<{width*3}} |{a}|")
    if len(b) > limit:
        out.append(f"  ... {len(b)-limit} more bytes")
    return "\n".join(out)


def open_dev():
    d = usb.core.find(idVendor=VID, idProduct=PID)
    if d is None:
        sys.exit("Rapsodo USB device not found. Plugged in and powered on?\n"
                 "Check with: bash tools/usbcheck.sh check")
    try:
        if d.is_kernel_driver_active(0):
            d.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass
    try:
        d.set_configuration()
    except usb.core.USBError as e:
        print(f"  note: set_configuration: {e}", file=sys.stderr)
    return d


def cmd_info(_):
    d = open_dev()
    print(f"{d.manufacturer} / {d.product} / serial {d.serial_number}")
    for cfg in d:
        for itf in cfg:
            print(f"  interface {itf.bInterfaceNumber} class 0x{itf.bInterfaceClass:02x} "
                  f"endpoints {itf.bNumEndpoints}")
            for ep in itf:
                dirn = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
                print(f"    EP 0x{ep.bEndpointAddress:02x} {dirn} maxpacket {ep.wMaxPacketSize}")


def cmd_listen(a):
    d = open_dev()
    usb.util.claim_interface(d, 0)
    print(f"Listening on EP 0x{EP_IN:02x} for {a.secs}s (read-only, nothing sent)...")
    end, total, reads, blob = time.time() + a.secs, 0, 0, bytearray()
    while time.time() < end:
        try:
            data = d.read(EP_IN, 512, timeout=1000)
        except usb.core.USBError as e:
            if e.errno in (60, 110) or "timeout" in str(e).lower():
                continue
            print(f"  USBError: {e}")
            break
        if data:
            reads += 1
            total += len(data)
            blob += bytes(data)
            if reads <= 8:
                print(f"\n[read {reads}] {len(data)} bytes")
                print(hexdump(bytes(data)))
    usb.util.release_interface(d, 0)
    print(f"\n{reads} reads, {total} bytes total")
    if total:
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, f"usb-listen-{int(time.time())}.bin")
        open(p, "wb").write(bytes(blob))
        print(f"raw capture -> {p}")
        print("THE UNIT PUSHES DATA UNSOLICITED - this is the live feed.")
    else:
        print("No unsolicited data. The unit likely needs a command on EP 0x01 first.")


def cmd_send(a):
    payload = binascii.unhexlify(a.hex.replace(" ", ""))
    if not a.yes:
        print(f"About to WRITE {len(payload)} bytes to the device: {payload.hex()}")
        if input("This changes device state. Type 'yes' to continue: ").strip() != "yes":
            sys.exit("aborted")
    d = open_dev()
    usb.util.claim_interface(d, 0)
    n = d.write(EP_OUT, payload, timeout=2000)
    print(f"wrote {n} bytes; reading reply...")
    try:
        r = d.read(EP_IN, 512, timeout=3000)
        print(f"reply {len(r)} bytes:\n{hexdump(bytes(r))}")
    except usb.core.USBError as e:
        print(f"no reply ({e})")
    usb.util.release_interface(d, 0)


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("info").set_defaults(fn=cmd_info)
p = sub.add_parser("listen"); p.add_argument("secs", nargs="?", type=int, default=20); p.set_defaults(fn=cmd_listen)
p = sub.add_parser("send"); p.add_argument("hex"); p.add_argument("--yes", action="store_true"); p.set_defaults(fn=cmd_send)
a = ap.parse_args(); a.fn(a)
