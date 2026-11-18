"""Rapsodo RIPE SDK bridge — talks to the unit through Rapsodo's own PlatformLib.dll.

WHY THIS EXISTS
    PlatformLib.dll (shipped in the free 1.0-era Windows app, at
    C:\\Rapsodo\\RapsodoPitching\\RapsodoPitching_Data\\Plugins\\) is Rapsodo's
    device SDK: 123 exported C functions, all prefixed RIPE*. Calling it is far
    better than reverse-engineering the USB bulk protocol, which resisted 4,295
    blind probes.

HARD REQUIREMENT
    PlatformLib.dll is a 32-bit x86 PE. It can ONLY be loaded by a 32-bit host
    process, on Windows. Use 32-bit Python (python -c "import struct;
    print(struct.calcsize('P')*8)" must print 32).

DESIGN
    This runs on the Windows box next to the hardware. It posts each shot to the
    viewer's HTTP API, so the viewer itself can run anywhere - same machine, or
    the Mac across the LAN. The viewer is pure stdlib and runs on Windows too.

STATUS
    Call sequence is modelled on the SDK's own export names. Exact argtypes and
    the flight-data struct layout are pending from the decompiled P/Invoke
    declarations in Assembly-CSharp.dll - see SIGNATURES_PENDING below.
"""
import ctypes, json, os, sys, time, urllib.request
from ctypes import c_int, c_char_p, c_void_p, c_float, c_double, c_uint, POINTER

DEFAULT_DLL = r"C:\Rapsodo\RapsodoPitching\RapsodoPitching_Data\Plugins\PlatformLib.dll"
VIEWER = os.environ.get("RAPSODO_VIEWER", "http://127.0.0.1:8777")

SIGNATURES_PENDING = """
Fill these from the [DllImport] declarations decompiled out of Assembly-CSharp.dll.
Until then every call uses ctypes' default (int-ish) marshalling, which is WRONG
for anything taking a struct, a float, or an out-parameter, and will silently
return garbage rather than fail loudly. Do not trust readings until this is done.
"""


class RipeError(RuntimeError):
    pass


class RipeSDK:
    def __init__(self, dll_path=DEFAULT_DLL):
        if sys.platform != "win32":
            raise RipeError(
                "PlatformLib.dll is a Windows x86 DLL; this bridge must run on Windows.")
        if ctypes.sizeof(ctypes.c_void_p) != 4:
            raise RipeError(
                "PlatformLib.dll is 32-bit. Run this under 32-bit Python "
                "(sys.maxsize must be 2**31-1, got %d)." % sys.maxsize)
        if not os.path.exists(dll_path):
            raise RipeError(f"PlatformLib.dll not found at {dll_path}")
        # The SDK is a C API; cdecl unless the decompile shows stdcall.
        self.lib = ctypes.CDLL(dll_path)
        self._bound = False

    # ---- error text -------------------------------------------------
    def sdk_status(self):
        try:
            self.lib.RIPEGetSDKStatusStr.restype = c_char_p
            return (self.lib.RIPEGetSDKStatusStr() or b"").decode("utf-8", "replace")
        except Exception as e:
            return f"<no status: {e}>"

    def box_status(self):
        try:
            self.lib.RIPEGetBOXStatusStr.restype = c_char_p
            return (self.lib.RIPEGetBOXStatusStr() or b"").decode("utf-8", "replace")
        except Exception as e:
            return f"<no status: {e}>"

    def _check(self, name, rc):
        if rc not in (0, 1):     # SDK convention unconfirmed; log rather than assume
            print(f"  {name} -> rc={rc}  sdk={self.sdk_status()}  box={self.box_status()}")
        return rc

    # ---- lifecycle --------------------------------------------------
    def init(self):
        return self._check("RIPEInit", self.lib.RIPEInit())

    def deinit(self):
        try:
            return self.lib.RIPEDeInit()
        except Exception:
            return None

    def discover(self):
        """Populate the SDK's internal box list. Returns raw rc."""
        return self._check("RIPEDiscover", self.lib.RIPEDiscover())

    def connect(self):
        return self._check("RIPEBoxConnect", self.lib.RIPEBoxConnect())

    def disconnect(self):
        try:
            return self.lib.RIPEBoxDisconnect()
        except Exception:
            return None

    # ---- identity (read-only; safe) ---------------------------------
    def identity(self):
        """Every read-only identity query the SDK exposes. Never writes."""
        out = {}
        for fn, label in [
            ("RIPEGetConnectedBoxInterfaceType", "interface_type"),
            ("RIPEGetBoxProductType",            "product_type"),
            ("RIPEGetBoxBallType",               "ball_type"),
            ("RIPEGetBoxSerialNumber",           "serial"),
            ("RIPEGetBoxFirmwareVersion",        "firmware"),
            ("RIPEGetBoxCPUID",                  "cpuid"),
            ("RIPEGetBoxMACID",                  "macid"),
            ("RIPEGetBOXStatus",                 "box_status"),
            ("RIPEGetSDKState",                  "sdk_state"),
        ]:
            try:
                f = getattr(self.lib, fn)
                v = f()
                # string-returning entry points need restype set; try both reads
                if label in ("serial", "firmware", "cpuid", "macid"):
                    f.restype = c_char_p
                    v = f()
                    v = v.decode("utf-8", "replace") if isinstance(v, bytes) else v
                out[label] = v
            except AttributeError:
                out[label] = "<export missing>"
            except Exception as e:
                out[label] = f"<error: {e}>"
        return out


# ---- viewer plumbing -------------------------------------------------
def post_shot(session_id, rec, viewer=VIEWER):
    body = json.dumps({"session_id": session_id, "shot": rec}).encode()
    req = urllib.request.Request(f"{viewer}/api/shot", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def new_session(name, viewer=VIEWER, player=None):
    body = json.dumps({"name": name, "source": "live", "player": player}).encode()
    req = urllib.request.Request(f"{viewer}/api/session", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)["id"]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Rapsodo RIPE SDK bridge")
    ap.add_argument("--dll", default=DEFAULT_DLL)
    ap.add_argument("--identity-only", action="store_true",
                    help="connect, print identity, disconnect. Writes nothing.")
    a = ap.parse_args()

    sdk = RipeSDK(a.dll)
    print("RIPEInit    ->", sdk.init())
    print("RIPEDiscover->", sdk.discover())
    print("RIPEBoxConnect ->", sdk.connect())
    print("\nidentity:")
    for k, v in sdk.identity().items():
        print(f"  {k:16} {v!r}")
    print("\nsdk status:", sdk.sdk_status())
    print("box status:", sdk.box_status())
    sdk.disconnect(); sdk.deinit()


if __name__ == "__main__":
    main()
