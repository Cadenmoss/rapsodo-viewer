#!/usr/bin/env python3
"""Systematic BULK-OUT probe campaign against the Rapsodo RBB1.0.

Sends short, benign payloads to EP 0x01 and watches EP 0x81 for any reply.
Deliberately does NOT send vendor CONTROL requests - on EZ-USB-style parts
those can overwrite firmware. Bulk writes of unrecognised payloads are
normally ignored by firmware.

    python3 tools/usbsweep.py            # run the campaign
    python3 tools/usbsweep.py --dry-run  # list payloads without sending
"""
import argparse, json, os, sys, time

try:
    import usb.core, usb.util
except ImportError:
    sys.exit("pyusb missing:  pip install pyusb   (brew install libusb)")

VID, PID, EP_IN, EP_OUT = 0x4003, 0x0002, 0x81, 0x01
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "findings")

def P(label, data):
    return {"label": label, "payload": data if isinstance(data, bytes) else data.encode()}

PROBES = [
    # line-oriented / ASCII consoles
    P("CR LF",            "\r\n"),
    P("question mark",    "?\r\n"),
    P("AT",               "AT\r\n"),
    P("VERSION",          "VERSION\r\n"),
    P("version lower",    "version\r\n"),
    P("HELP",             "HELP\r\n"),
    P("INFO",             "INFO\r\n"),
    P("STATUS",           "STATUS\r\n"),
    P("ID query (SCPI)",  "*IDN?\r\n"),
    P("GET",              "GET\r\n"),
    P("START",            "START\r\n"),
    P("hello",            "hello\r\n"),
    # single-byte opcodes
    P("0x00",             b"\x00"),
    P("0x01",             b"\x01"),
    P("0x02",             b"\x02"),
    P("0xFF",             b"\xff"),
    # tiny length-prefixed frames
    P("len-prefixed 0x01", b"\x01\x00\x00\x00"),
    P("len-prefixed 0x02", b"\x02\x00\x00\x00"),
    # 'BB' magic guesses (device string is "RAPSODO BB in HS")
    P("'RAPSODO'",        "RAPSODO"),
    P("'BB'",             "BB"),
]

def hexdump(b, width=16, limit=256):
    out = []
    for i in range(0, min(len(b), width*16), width):
        c = b[i:i+width]
        out.append(f"    {i:04x}  {' '.join(f'{x:02x}' for x in c):<{width*3}} "
                   f"|{''.join(chr(x) if 32<=x<127 else '.' for x in c)}|")
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--read-ms", type=int, default=900)
    a = ap.parse_args()

    if a.dry_run:
        for p in PROBES:
            print(f"  {p['label']:20} {p['payload'][:32].hex()}")
        return

    d = usb.core.find(idVendor=VID, idProduct=PID)
    if d is None:
        sys.exit("device not found - plugged in and powered?")
    d.set_configuration()
    usb.util.claim_interface(d, 0)

    results, hits = [], 0
    print(f"Probing {len(PROBES)} payloads on EP 0x{EP_OUT:02x}, "
          f"reading EP 0x{EP_IN:02x} ({a.read_ms}ms each)\n")

    # drain anything stale
    try:
        while True:
            if not d.read(EP_IN, 512, timeout=200):
                break
    except usb.core.USBError:
        pass

    for p in PROBES:
        rec = {"label": p["label"], "sent": p["payload"].hex()}
        try:
            n = d.write(EP_OUT, p["payload"], timeout=1500)
            rec["wrote"] = n
        except usb.core.USBError as e:
            rec["write_error"] = str(e)
            print(f"  {p['label']:20} WRITE FAILED: {e}")
            try: d.clear_halt(EP_OUT)
            except Exception: pass
            results.append(rec); continue
        chunks = b""
        try:
            while True:
                r = d.read(EP_IN, 512, timeout=a.read_ms)
                if not r: break
                chunks += bytes(r)
                if len(chunks) > 8192: break
        except usb.core.USBError as e:
            if "pipe" in str(e).lower() or getattr(e, "errno", None) == 32:
                try: d.clear_halt(EP_IN)
                except Exception: pass
                rec["stalled"] = True
        if chunks:
            hits += 1
            rec["reply_hex"] = chunks[:1024].hex()
            rec["reply_len"] = len(chunks)
            print(f"  {p['label']:20} *** REPLY {len(chunks)} bytes ***")
            print(hexdump(chunks))
        else:
            print(f"  {p['label']:20} (silent){'  [stall]' if rec.get('stalled') else ''}")
        results.append(rec)
        time.sleep(0.15)

    usb.util.release_interface(d, 0)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"usbsweep-{int(time.time())}.json")
    json.dump(results, open(path, "w"), indent=2)
    print(f"\n{hits}/{len(PROBES)} payloads produced a reply")
    print(f"log -> {path}")
    if not hits:
        print("\nNothing answered. The command set isn't guessable this way;")
        print("the unit likely expects a specific binary framing we can't derive")
        print("without a reference client to observe.")

main()
