#!/usr/bin/env python3
"""Local Rapsodo viewer. Stdlib only. Binds to 127.0.0.1 -- nothing leaves the machine.

    python3 app/server.py                 # start on http://127.0.0.1:8777
    python3 app/server.py --import f.csv  # import a CSV, then start
"""
import argparse, json, os, sys, threading, webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store
from adapters.csvfile import CsvSource

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/sessions":
                return self._json(store.sessions())
            if u.path == "/api/shots":
                sid = int(q["session"][0])
                after = int(q.get("after", [-1])[0])
                rows = store.shots_since(sid, after) if after >= 0 else store.shots(sid)
                return self._json(rows)
            if u.path == "/api/status":
                live = {"available": False, "reason": ""}
                try:
                    from adapters.rapsodo_live import RapsodoLive
                    RapsodoLive().connect()
                    live["available"] = True
                except NotImplementedError as e:
                    live["reason"] = str(e)
                except Exception as e:
                    live["reason"] = f"{type(e).__name__}: {e}"
                return self._json({"live": live, "db": store.DB_PATH})
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/shot":                    # live adapters push here
                sid = int(body["session_id"])
                return self._json({"seq": store.add_shot(sid, body.get("shot", {}))})
            if u.path == "/api/session":
                return self._json({"id": store.create_session(
                    body.get("name", "Session"), body.get("source", "manual"),
                    body.get("player"), body.get("notes"))})
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        return self._json({"error": "unknown endpoint"}, 404)


def import_csv(path, name=None, player=None):
    src = CsvSource(path).connect()
    sid = store.create_session(name or os.path.basename(path), "import", player,
                               notes=f"imported from {path}")
    n = 0
    for rec in src.shots():
        store.add_shot(sid, rec)
        n += 1
    print(f"imported {n} shots from {path} -> session {sid}")
    print(f"  columns matched: {src.mapping}")
    return sid, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind address. Default 127.0.0.1 (this machine only). "
                         "Use 0.0.0.0 to open the viewer on your phone or another "
                         "device on the same network.")
    ap.add_argument("--import", dest="imp", help="CSV file to import before starting")
    ap.add_argument("--player")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    if a.imp:
        import_csv(a.imp, player=a.player)

    srv = HTTPServer((a.host, a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    if a.host not in ("127.0.0.1", "localhost"):
        import socket as _s
        try:
            _p = _s.socket(_s.AF_INET, _s.SOCK_DGRAM); _p.connect(("8.8.8.8", 80))
            lan = _p.getsockname()[0]; _p.close()
        except Exception:
            lan = a.host
        print("!" * 70)
        print("Serving on the NETWORK, not just this machine.")
        print(f"  On your phone, open:  http://{lan}:{a.port}/")
        print("  This viewer has NO password. Anyone on the same network can read")
        print("  your data and POST shots to it. Fine at home; think twice on a")
        print("  shared or public network.")
        print("!" * 70)
    print(f"Rapsodo viewer  ->  {url}")
    print(f"database        ->  {store.DB_PATH}")
    print("Ctrl-C to stop.")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
