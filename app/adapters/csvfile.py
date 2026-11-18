"""Import a CSV exported from Rapsodo (or any tool) by fuzzy-matching headers."""
import csv, re
from .base import ShotSource

ALIASES = {
    "exit_velocity": ["exit velocity","exitvelocity","exit velo","exitvelo","velo","ev","velocity",
                      "exit speed","exitspeed","ballspeed","ball speed","batted ball speed","speed","mph"],
    "launch_angle":  ["launch angle","launchangle","la","vertical angle","vert angle","vangle",
                      "launch","va","elevation"],
    "direction":     ["direction","horizontal angle","horiz angle","hor angle","hangle","spray",
                      "spray angle","azimuth","dir","side angle","ha"],
    "distance":      ["distance","carry","carry distance","dist","total distance","carrydistance"],
    "spin_rate":     ["spin rate","spinrate","spin","total spin","rpm","backspin"],
    "spin_axis":     ["spin axis","spinaxis","axis","tilt","spin direction"],
    "hit_type":      ["hit type","hittype","type","result","classification","outcome","batted ball type"],
}


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").strip().lower())


def map_headers(headers):
    out = {}
    for h in headers:
        n = _norm(h)
        for field, alts in ALIASES.items():
            if field in out:
                continue
            if n == _norm(field) or n in [_norm(a) for a in alts]:
                out[field] = h
                break
    return out


def _num(v):
    if v is None:
        return None
    m = re.search(r"-?\d+(\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


# The database stores SI (see store.py). Third-party exports are almost always
# imperial - Rapsodo/HitTrax/TrackMan all publish mph and feet - so convert on
# the way in. Pass units="SI" if a file really is metric.
MPH_TO_MS = 1.0 / 2.2369363
FT_TO_M   = 1.0 / 3.28084
IMPERIAL_SPEED = ["total_speed"]
IMPERIAL_DIST  = ["carry", "side", "max_height"]


class CsvSource(ShotSource):
    name = "csv"

    def __init__(self, path, units="imperial"):
        self.path, self._rows, self.mapping = path, [], {}
        self.units = units

    def connect(self):
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            # tolerate junk preamble rows above the real header
            lines = f.readlines()
        best_i, best_map = None, {}
        for i in range(min(15, len(lines))):
            try:
                hdr = next(csv.reader([lines[i]]))
            except Exception:
                continue
            m = map_headers(hdr)
            if len(m) > len(best_map):
                best_i, best_map, best_hdr = i, m, hdr
        if not best_map:
            raise ValueError(
                f"No recognisable metric columns in {self.path}. "
                f"Expected something like: exit velocity, launch angle, direction, distance.")
        self.mapping = best_map
        rdr = csv.DictReader(lines[best_i:])
        self._rows = [r for r in rdr if any((r.get(c) or "").strip() for c in best_map.values())]
        return self

    def shots(self):
        for r in self._rows:
            rec = {}
            for field, col in self.mapping.items():
                v = r.get(col)
                rec[field] = v if field == "hit_type" else _num(v)
            # map legacy/aliased names onto the SI-canonical column names
            for old, new in (("exit_velocity","total_speed"), ("direction","horizontal_angle"),
                             ("distance","carry"), ("spin_rate","total_spin")):
                if old in rec and rec.get(new) is None:
                    rec[new] = rec.pop(old)
            if self.units == "imperial":
                for f in IMPERIAL_SPEED:
                    if rec.get(f) is not None: rec[f] = rec[f] * MPH_TO_MS
                for f in IMPERIAL_DIST:
                    if rec.get(f) is not None: rec[f] = rec[f] * FT_TO_M
            rec["_source_row"] = {k: v for k, v in r.items() if v not in (None, "")}
            rec["_source_units"] = self.units
            yield rec
