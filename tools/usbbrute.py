#!/usr/bin/env python3
"""Brute-force the Rapsodo RBB1.0 BULK-OUT command set, with state oracles.

Writes only to BULK OUT (EP 0x01). Reads: BULK IN (EP 0x81) and vendor
control IN (0xC0) - both read-only. Never uses bmRequestType 0x40, never 0xA0.

Four oracles per probe:
  1. BULK IN reply            - the real prize
  2. vendor-buffer change     - device SRAM shifted => state changed
  3. endpoint halt/stall      - firmware rejected the frame (also a signal!)
  4. write duration outlier   - firmware spent time processing

    python3 tools/usbbrute.py --phase 1
    python3 tools/usbbrute.py --phase all --read-ms 200
"""
import argparse, itertools, json, os, sys, time

import usb.core, usb.util

VID, PID, EP_IN, EP_OUT = 0x4003, 0x0002, 0x81, 0x01
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "findings")


def phase1():
    """every single byte"""
    for b in range(256):
        yield (f"byte {b:#04x}", bytes([b]))

def phase2():
    """two bytes: opcode + arg, and sync-word style pairs"""
    for a in range(256):
        yield (f"{a:#04x} 00", bytes([a, 0]))
    for sync in (0x55, 0xAA, 0x02, 0x7E, 0xA5, 0x5A, 0xFF, 0x01, 0x24, 0x23):
        for c in range(256):
            yield (f"sync {sync:#04x} cmd {c:#04x}", bytes([sync, c]))

def phase3():
    """text commands x terminators"""
    words = ["", "?", "AT", "ID", "V", "VER", "VERSION", "INFO", "STAT", "STATUS",
             "GET", "READ", "START", "STOP", "RUN", "GO", "INIT", "RESET", "PING",
             "HELLO", "RAPSODO", "RAP", "BB", "HS", "DATA", "STREAM", "ARM", "CAL",
             "MODE", "CONFIG", "DUMP", "TEST", "DIAG", "SN", "MAC", "WIFI", "SSID"]
    terms = [b"", b"\n", b"\r", b"\r\n", b"\x00", b";", b"\x03", b"\x04"]
    for w, t in itertools.product(words, terms):
        yield (f"{w!r}+{t!r}", w.encode() + t)

def phase4():
    """structured frames: sync, cmd, length, checksum variants"""
    for sync in (0x55, 0xAA, 0x7E, 0xA5, 0x02, 0x5A):
        for cmd in range(0, 32):
            yield (f"[{sync:#04x}][{cmd:#04x}][len0]", bytes([sync, cmd, 0x00, 0x00]))
            yield (f"[{sync:#04x}][{cmd:#04x}][len0][sum]", bytes([sync, cmd, 0x00, 0x00, (sync+cmd) & 0xFF]))
            yield (f"[{sync:#04x}{sync:#04x}][{cmd:#04x}]", bytes([sync, sync, cmd, 0x00]))
    for cmd in range(0, 32):
        yield (f"LE32 cmd {cmd}", cmd.to_bytes(4, "little"))
        yield (f"BE32 cmd {cmd}", cmd.to_bytes(4, "big"))
        yield (f"len+cmd {cmd}", bytes([0x04, 0x00, cmd, 0x00]))

PHASES = {1: phase1, 2: phase2, 3: phase3, 4: phase4}



STATE = os.path.join(OUT_DIR, "usbbrute-progress.json")


def connect(wait=True, quiet=False):
    """Get the device, waiting through the unit's idle power-off if needed."""
    waited = 0
    while True:
        d = usb.core.find(idVendor=VID, idProduct=PID)
        if d is not None:
            try:
                d.set_configuration()
            except usb.core.USBError:
                pass
            try:
                usb.util.claim_interface(d, 0)
            except usb.core.USBError:
                pass
            if waited and not quiet:
                print(f"  [reconnected after {waited}s]")
            return d
        if not wait:
            return None
        if waited == 0 and not quiet:
            print("  [device gone - unit powered off? waiting for it to come back;"
                  " press its power button]")
        time.sleep(3); waited += 3
        if waited % 60 == 0:
            print(f"  [still waiting, {waited}s - is the unit switched on?]")


def load_done():
    try:
        return set(json.load(open(STATE))["done"])
    except Exception:
        return set()


def save_done(done):
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump({"done": sorted(done)}, open(STATE, "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="1")
    ap.add_argument("--read-ms", type=int, default=200)
    ap.add_argument("--max-secs", type=int, default=900)
    ap.add_argument("--no-resume", dest="resume", action="store_false")
    a = ap.parse_args()

    ap_resume = getattr(a, "resume", True)
    done = load_done() if ap_resume else set()
    if done:
        print(f"resuming: {len(done)} payloads already tested")

    d = connect()

    def oracle():
        try:
            return bytes(d.ctrl_transfer(0xC0, 0x00, 0, 0, 64, timeout=400))[8:].hex()
        except usb.core.USBError:
            return None          # None = could not read (likely powered off)

    base = oracle()
    print(f"baseline oracle: {(base or 'unavailable')[:40]}...")

    phases = [1, 2, 3, 4] if a.phase == "all" else [int(x) for x in a.phase.split(",")]
    findings, n, t0, powercycles = [], 0, time.time(), 0

    for ph in phases:
        gen = [(l, p) for (l, p) in PHASES[ph]() if p.hex() not in done]
        print(f"\n=== PHASE {ph}: {len(gen)} payloads to test ===")
        for label, payload in gen:
            if time.time() - t0 > a.max_secs:
                print("  [time budget reached]"); break
            n += 1
            rec = {"phase": ph, "label": label, "hex": payload.hex()}
            t1 = time.time()
            try:
                d.write(EP_OUT, payload, timeout=1200)
            except usb.core.USBError as e:
                # Is the device simply gone (idle power-off), or did this payload do it?
                if usb.core.find(idVendor=VID, idProduct=PID) is None:
                    powercycles += 1
                    print(f"  {label:30} [device vanished - power cycle #{powercycles}, not a finding]")
                    d = connect()
                    base = oracle()
                    continue          # retry this payload next run; don't mark done
                rec["write_error"] = str(e)
                findings.append(rec)
                print(f"  {label:30} WRITE ERROR (device still present!): {e}")
                try: d.clear_halt(EP_OUT)
                except Exception: pass
                done.add(payload.hex()); continue
            dt = (time.time() - t1) * 1000
            reply = b""
            try:
                reply = bytes(d.read(EP_IN, 512, timeout=a.read_ms))
            except usb.core.USBError as e:
                if getattr(e, "errno", None) == 32 or "pipe" in str(e).lower():
                    rec["stalled"] = True
                    try: d.clear_halt(EP_IN)
                    except Exception: pass
            now = oracle()
            interesting = False
            if reply:
                rec["reply"] = reply.hex(); interesting = True
                print(f"  {label:30} *** REPLY {len(reply)}B: {reply[:32].hex()} ***")
            if now is None:
                # oracle unreadable => device went away; power cycle, not a signal
                powercycles += 1
                print(f"  {label:30} [oracle lost - power cycle #{powercycles}]")
                d = connect(); base = oracle(); continue
            if now != base:
                rec["oracle_changed"] = now; interesting = True
                print(f"  {label:30} *** STATE CHANGED -> {now[:40]} ***")
                base = now
            if rec.get("stalled"):
                interesting = True
                print(f"  {label:30} [STALL]")
            if dt > 50:
                rec["write_ms"] = round(dt, 1); interesting = True
                print(f"  {label:30} [slow write {dt:.0f}ms]")
            if interesting:
                findings.append(rec)
            done.add(payload.hex())
            if n % 250 == 0:
                save_done(done)
                print(f"  ...{n} probes, {time.time()-t0:.0f}s, {powercycles} power cycles")

    save_done(done)
    try: usb.util.release_interface(d, 0)
    except Exception: pass
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, f"usbbrute-{int(time.time())}.json")
    json.dump({"probes": n, "findings": findings}, open(p, "w"), indent=2)
    print(f"\n{n} probes in {time.time()-t0:.0f}s, {len(findings)} real anomalies, {powercycles} power cycles survived")
    print(f"log -> {p}")


main()
