#!/usr/bin/env python3
"""
Rapsodo RBB1.0 local-link discovery.

Run this ONCE YOU ARE JOINED to the Rapsodo unit's network (or once the unit
has joined yours). It makes no assumptions about the protocol: it finds hosts,
finds open ports, and characterises whatever is listening.

    python3 tools/discover.py                # auto-detect interface + subnet
    python3 tools/discover.py --host 192.168.1.1   # focus one host
    python3 tools/discover.py --listen-only        # just watch for broadcasts

Everything found is written to findings/discover-<timestamp>.json
"""
import argparse, ipaddress, json, os, re, socket, struct, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "findings")

# Ports worth trying first: HTTP-ish, RTSP/streaming, and the high ports
# embedded sports sensors commonly use for their own binary feeds.
PRIORITY_PORTS = [
    21, 22, 23, 53, 80, 81, 443, 554, 1883, 2000, 3000, 3333, 4000, 4444,
    5000, 5001, 5555, 6000, 6666, 7000, 7777, 8000, 8001, 8080, 8081, 8088,
    8443, 8888, 9000, 9001, 9090, 9999, 10000, 11000, 12345, 20000, 50000,
]
UDP_LISTEN_PORTS = [1900, 5353, 6000, 7000, 8000, 9000, 9999, 10000, 30303]


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=25).stdout
    except Exception:
        return ""


def active_interfaces():
    """Interfaces with an IPv4 address and their subnet + gateway."""
    out, cur, ifaces = sh("ifconfig"), None, []
    for line in out.splitlines():
        m = re.match(r"^(\w+):", line)
        if m:
            cur = m.group(1)
        elif "inet " in line and cur and not cur.startswith(("lo", "utun", "gif", "stf", "awdl", "llw")):
            p = line.split()
            ip = p[1]
            mask = p[3]
            if mask.startswith("0x"):
                bits = bin(int(mask, 16)).count("1")
            else:
                bits = 24
            try:
                net = ipaddress.ip_network(f"{ip}/{bits}", strict=False)
            except ValueError:
                continue
            ifaces.append({"iface": cur, "ip": ip, "cidr": str(net), "hosts": net.num_addresses})
    routes = sh("netstat -rn -f inet")
    for i in ifaces:
        for line in routes.splitlines():
            p = line.split()
            if len(p) >= 4 and p[0] == "default" and p[-1] == i["iface"]:
                i["gateway"] = p[1]
                break
    return ifaces


def read_arp():
    """macOS `arp` returns empty when spawned from python in some sandboxes,
    so verify we got real output and say so loudly if we didn't."""
    out = sh("arp -an")
    entries = {}
    for line in out.splitlines():
        m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-f:]+)", line)
        if m and "incomplete" not in line:
            entries[m.group(1)] = m.group(2)
    if not out.strip():
        print("  !! WARNING: `arp -an` returned nothing from this process.")
        print("     MAC/vendor matching is UNAVAILABLE - do not read a non-match")
        print("     as proof the device is absent. Run `arp -an` in a shell instead.")
        return entries, False
    return entries, True


def ping_sweep(cidr, limit=4096):
    """Liveness comes from ping itself, not the ARP cache, so a broken
    `arp` degrades MAC enrichment rather than silently reporting zero hosts."""
    net = ipaddress.ip_network(cidr, strict=False)
    addrs = [str(h) for h in net.hosts()][:limit]
    alive = []

    def ping(a):
        r = subprocess.run(["ping", "-c", "1", "-W", "400", "-n", a],
                           capture_output=True, timeout=4)
        return a if r.returncode == 0 else None

    with ThreadPoolExecutor(max_workers=192) as ex:
        for r in ex.map(ping, addrs):
            if r:
                alive.append(r)

    arp_map, arp_ok = read_arp()
    hosts = {ip: arp_map.get(ip, "?") for ip in alive}
    # ARP can also reveal hosts that ignore ICMP
    for ip, mac in arp_map.items():
        if ipaddress.ip_address(ip) in net:
            hosts.setdefault(ip, mac)
    if arp_ok:
        inventek = {ip: m for ip, m in hosts.items() if m.lower().startswith("c4:7f:51")}
        if inventek:
            print(f"  *** INVENTEK RADIO (Rapsodo Wi-Fi module) FOUND: {inventek}")
    return hosts


def scan_ports(host, ports, timeout=0.6):
    open_ports = []
    def probe(p):
        s = socket.socket()
        s.settimeout(timeout)
        try:
            if s.connect_ex((host, p)) == 0:
                return p
        except OSError:
            pass
        finally:
            s.close()
        return None
    with ThreadPoolExecutor(max_workers=200) as ex:
        for r in ex.map(probe, ports):
            if r:
                open_ports.append(r)
    return sorted(open_ports)


def characterise(host, port):
    """What is this? Try HTTP, then just listen for an unsolicited banner."""
    info = {"port": port}
    # 1. HTTP
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: rapsodo-discover\r\nConnection: close\r\n\r\n".encode())
        data = b""
        s.settimeout(3)
        while len(data) < 8192:
            try:
                c = s.recv(4096)
            except socket.timeout:
                break
            if not c:
                break
            data += c
        s.close()
        if data:
            info["http_response"] = data[:2048].decode("utf-8", "replace")
            info["looks_http"] = data.startswith(b"HTTP/")
    except OSError as e:
        info["http_error"] = str(e)
    # 2. Unsolicited banner / push feed (many sensors stream on connect)
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.settimeout(4)
        chunks = b""
        try:
            while len(chunks) < 4096:
                c = s.recv(2048)
                if not c:
                    break
                chunks += c
        except socket.timeout:
            pass
        s.close()
        if chunks:
            info["banner_hex"] = chunks[:512].hex()
            info["banner_ascii"] = re.sub(rb"[^\x20-\x7e]", b".", chunks[:512]).decode()
            info["pushes_unsolicited"] = True
    except OSError:
        pass
    return info


def probe_http_paths(host, port, scheme="http"):
    """Common endpoint names on embedded sports devices."""
    import urllib.request, urllib.error
    paths = ["/", "/index.html", "/api", "/api/v1", "/status", "/info", "/device",
             "/config", "/data", "/session", "/shots", "/pitches", "/live",
             "/version", "/health", "/description.xml", "/cgi-bin/", "/settings"]
    hits = []
    for p in paths:
        url = f"{scheme}://{host}:{port}{p}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rapsodo-discover"})
            with urllib.request.urlopen(req, timeout=3) as r:
                body = r.read(4096)
                hits.append({"path": p, "status": r.status,
                             "content_type": r.headers.get("Content-Type"),
                             "len": len(body),
                             "preview": body[:600].decode("utf-8", "replace")})
        except urllib.error.HTTPError as e:
            if e.code not in (404,):
                hits.append({"path": p, "status": e.code})
        except Exception:
            pass
    return hits


def listen_broadcasts(seconds=25):
    """Many units announce themselves by UDP broadcast before any app talks."""
    socks = []
    for p in UDP_LISTEN_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
            s.bind(("", p))
            s.setblocking(False)
            socks.append((p, s))
        except OSError:
            pass
    print(f"  listening on UDP {[p for p, _ in socks]} for {seconds}s ...")
    import select
    seen, end = [], time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([s for _, s in socks], [], [], 1.0)
        for s in r:
            try:
                data, addr = s.recvfrom(65535)
            except OSError:
                continue
            seen.append({"from": addr[0], "sport": addr[1],
                         "local_port": s.getsockname()[1],
                         "len": len(data), "hex": data[:256].hex(),
                         "ascii": re.sub(rb"[^\x20-\x7e]", b".", data[:256]).decode()})
            print(f"    UDP {addr[0]}:{addr[1]} -> :{s.getsockname()[1]}  {len(data)}B")
    for _, s in socks:
        s.close()
    return seen


def ssdp_probe():
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n').encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(4)
    replies = []
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
        while True:
            try:
                data, addr = s.recvfrom(65535)
            except socket.timeout:
                break
            replies.append({"from": addr[0], "body": data[:800].decode("utf-8", "replace")})
    except OSError:
        pass
    s.close()
    return replies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", help="probe only this IP")
    ap.add_argument("--iface", help="restrict to this interface")
    ap.add_argument("--all-ports", action="store_true", help="sweep 1-65535 (slow)")
    ap.add_argument("--listen-only", action="store_true")
    ap.add_argument("--listen-secs", type=int, default=25)
    a = ap.parse_args()

    report = {"run_at": datetime.now(timezone.utc).isoformat(), "findings": {}}
    print("== interfaces ==")
    ifaces = active_interfaces()
    for i in ifaces:
        print(f"  {i['iface']:8} {i['ip']:15} {i['cidr']:20} gw={i.get('gateway','-')}")
    report["findings"]["interfaces"] = ifaces

    print("\n== UDP broadcast listen ==")
    report["findings"]["broadcasts"] = listen_broadcasts(a.listen_secs)
    print("\n== SSDP/UPnP ==")
    ssdp = ssdp_probe()
    print(f"  {len(ssdp)} replies")
    report["findings"]["ssdp"] = ssdp

    if not a.listen_only:
        targets = []
        if a.host:
            targets = [a.host]
        else:
            for i in ifaces:
                if a.iface and i["iface"] != a.iface:
                    continue
                gw = i.get("gateway")
                if gw:
                    targets.append(gw)
                if i["hosts"] <= 1024:
                    print(f"\n== sweeping {i['cidr']} on {i['iface']} ==")
                    live = ping_sweep(i["cidr"])
                    print(f"  {len(live)} live hosts")
                    report["findings"].setdefault("live_hosts", {}).update(live)
                    targets += list(live.keys())
                else:
                    print(f"\n  {i['cidr']} too large to sweep; probing gateway only")
        targets = sorted(set(targets))

        ports = list(range(1, 65536)) if a.all_ports else PRIORITY_PORTS
        print(f"\n== port scan: {len(targets)} host(s), {len(ports)} port(s) ==")
        for t in targets:
            op = scan_ports(t, ports)
            if not op:
                continue
            print(f"  {t}: open {op}")
            h = {"open_ports": op, "services": []}
            for p in op:
                c = characterise(t, p)
                if c.get("looks_http") or p in (80, 81, 443, 8000, 8080, 8443, 8888):
                    c["paths"] = probe_http_paths(t, p, "https" if p == 443 else "http")
                h["services"].append(c)
                tag = "HTTP" if c.get("looks_http") else ("PUSH" if c.get("pushes_unsolicited") else "open")
                print(f"     :{p} {tag}")
            report["findings"].setdefault("hosts", {})[t] = h

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"discover-{int(time.time())}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
