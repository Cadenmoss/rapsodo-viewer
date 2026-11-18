"""SQLite storage for Rapsodo RBB1.0 data. Stdlib only, fully local.

SCHEMA PROVENANCE
    Field names and units follow Rapsodo's own SDK structs, recovered from the
    P/Invoke declarations in the 1.0-era Windows app (PlatformLib.dll / RIPE*):

      RIPESpeedParamsType  totalSpeed, totalSpeedConfidence, launchAngle,
                           launchAngleConfidence, horizontalAngle,
                           horizontalAngleConfidence, startBallPositionStatus
      RIPESpinParamsType   totalSpin, backSpin, sideSpin, spinAxis,
                           measurementConfidence
      RIPEFlightParamsType carry, side, maxHeight, flightDuration,
                           validPointCount, pts[2010]
      FlightModelData      vX/vY/vZ, pX/pY/pZ, sX/sY/sZ, x/y/z[4000],
                           length, ballType, pitching

    Earlier versions of this file used invented names (exit_velocity, direction,
    distance, spin_rate, hit_type). Those were inferred from marketing copy.
    This schema is the real thing; the CSV importer still accepts the old names
    as aliases so third-party exports keep working.

    NOTE: hit_type has no SDK equivalent - it is derived locally from
    launch_angle, and flagged as derived rather than measured.
"""
import json, os, sqlite3, time
from contextlib import contextmanager

# ---------------------------------------------------------------------------
# UNITS: this database stores SI, because that is what the SDK emits.
#
#   speed     metres/second   (RIPESpeedParamsType.totalSpeed is m/s -- the app
#                              multiplies by 2.2369363 only for display, and
#                              Rapsodo's own Shot.speed column is raw m/s too)
#   distance  metres          (carry, side, maxHeight, release*, trajectory xyz;
#                              confirmed by baseballRadiusFeet = 0.036378f * 3.28084f,
#                              0.036378 m being the real baseball radius)
#   spin      rpm             (ALREADY rpm -- displayed raw, do NOT apply 9.549)
#   angles    degrees         (strong inference: no multiplier anywhere, but no
#                              explicit conversion was found proving it)
#   flightDuration  UNKNOWN   (the Pitching UI never renders it, so there is no
#                              formatting code to read the unit off. Seconds is
#                              likely given everything else is SI -- unverified.)
#
# Converting at the boundaries keeps one source of truth. Importers convert in,
# the UI converts out.
# ---------------------------------------------------------------------------
MS_TO_MPH = 2.2369363
MS_TO_KMH = 3.6
M_TO_FT   = 3.28084

# Strike zone geometry, metres, from the app's own constants.
# ORIGIN IS THE GROUND AT THE MIDDLE OF THE PLATE -- (0,0) is NOT the zone centre.
STRIKE_ZONE = {
    "half_width":       0.225,   # +/- from plate centre
    "top":              1.0668,  # exactly 3.5 ft above ground
    "outer_half_width": 0.45,    # 0.9 m full = 17.7 in = 17" plate + a ball
    "outer_top":        1.4,
}

DB_PATH = os.environ.get("RAPSODO_DB") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rapsodo.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  player      TEXT,
  started_at  REAL NOT NULL,
  ended_at    REAL,
  source      TEXT NOT NULL,        -- 'live' | 'import' | 'rif'
  source_units TEXT,                -- units the SOURCE used, before conversion to SI
  box_serial  TEXT,
  product_type TEXT,                -- PITCHING | HITTING, from RIPEGetBoxStaticData
  notes       TEXT
);
CREATE TABLE IF NOT EXISTS shots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq           INTEGER,
  ts            REAL NOT NULL,

  -- RIPESpeedParamsType
  total_speed              REAL,   -- METRES/SECOND (SI, as the SDK emits)
  total_speed_confidence   REAL,
  launch_angle             REAL,   -- degrees
  launch_angle_confidence  REAL,
  horizontal_angle         REAL,   -- degrees, -pull / +oppo
  horizontal_angle_confidence REAL,
  ball_position_status     TEXT,   -- OK | NEAR | FAR | UNKNOWN

  -- RIPESpinParamsType
  total_spin        REAL,          -- rpm
  back_spin         REAL,
  side_spin         REAL,
  spin_axis         REAL,          -- degrees
  spin_confidence   REAL,

  -- RIPEFlightParamsType
  carry             REAL,          -- METRES
  side              REAL,
  max_height        REAL,
  flight_duration   REAL,          -- unit UNVERIFIED (likely seconds)
  valid_point_count INTEGER,

  -- FlightModelData scalars
  vel_x REAL, vel_y REAL, vel_z REAL,
  pos_x REAL, pos_y REAL, pos_z REAL,
  spin_x REAL, spin_y REAL, spin_z REAL,
  ball_type   INTEGER,
  is_pitching INTEGER,

  -- break / location (RIPEPitchParamsType, also in Rapsodo's own Shot table)
  horizontal_break REAL,
  vertical_break   REAL,
  strike_zone_x    REAL,
  strike_zone_y    REAL,
  spin_efficiency  REAL,
  effective_spin   REAL,
  spin_clock_tilt_hour   REAL,
  spin_clock_tilt_minute REAL,

  -- per-shot provenance: makes every recording self-describing, so shots from
  -- different boxes or firmware revisions can never be silently conflated.
  -- Rapsodo's own Shot table stores these per row; worth copying.
  box_serial   TEXT,
  fw_version   TEXT,
  hw_version   TEXT,

  -- RIPEDebugMetricsType. num_ball_ipe vs num_ball_fw is a built-in sanity
  -- check: image-pipeline ball count disagreeing with firmware ball count
  -- flags a suspect measurement.
  radar_true_spin  REAL,
  num_ball_ipe     REAL,
  num_ball_fw      REAL,
  trig_start_speed REAL,
  trig_end_speed   REAL,
  transfer_time    REAL,

  -- derived locally, NOT measured
  hit_type      TEXT,

  trajectory    TEXT,   -- JSON [[x,y,z],...] up to 4000 points
  raw           TEXT,   -- verbatim source record; nothing is ever lost
  UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_shots_session ON shots(session_id, ts);
"""

FIELDS = [
    "total_speed","total_speed_confidence","launch_angle","launch_angle_confidence",
    "horizontal_angle","horizontal_angle_confidence","ball_position_status",
    "total_spin","back_spin","side_spin","spin_axis","spin_confidence",
    "carry","side","max_height","flight_duration","valid_point_count",
    "vel_x","vel_y","vel_z","pos_x","pos_y","pos_z","spin_x","spin_y","spin_z",
    "ball_type","is_pitching",
    "horizontal_break","vertical_break","strike_zone_x","strike_zone_y",
    "spin_efficiency","effective_spin","spin_clock_tilt_hour","spin_clock_tilt_minute",
    "box_serial","fw_version","hw_version",
    "radar_true_spin","num_ball_ipe","num_ball_fw",
    "trig_start_speed","trig_end_speed","transfer_time",
    "hit_type",
]

def suspect(rec):
    """True when the image pipeline and firmware disagree on how many balls they
    saw - Rapsodo tracks both, and a mismatch means the measurement is doubtful."""
    a, b = rec.get("num_ball_ipe"), rec.get("num_ball_fw")
    return a is not None and b is not None and a != b

# Old invented names -> real SDK-aligned columns, so existing callers/CSVs work.
LEGACY = {"exit_velocity":"total_speed", "direction":"horizontal_angle",
          "distance":"carry", "spin_rate":"total_spin"}


@contextmanager
def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def classify(launch_angle):
    """Derived locally. Rapsodo's SDK has no hit_type field."""
    if launch_angle is None: return None
    if launch_angle < 10:  return "GroundBall"
    if launch_angle < 25:  return "LineDrive"
    if launch_angle < 50:  return "FlyBall"
    return "PopUp"


def normalise(rec):
    out = dict(rec)
    for old, new in LEGACY.items():
        if old in out and out.get(new) is None:
            out[new] = out.pop(old)
    return out


def create_session(name, source, player=None, notes=None,
                   box_serial=None, product_type=None, source_units="SI"):
    with db() as c:
        return c.execute(
            "INSERT INTO sessions(name,player,started_at,source,source_units,"
            "box_serial,product_type,notes) VALUES(?,?,?,?,?,?,?,?)",
            (name, player, time.time(), source, source_units,
             box_serial, product_type, notes)).lastrowid


def add_shot(session_id, rec, seq=None, ts=None, trajectory=None):
    rec = normalise(rec)
    vals = {k: rec.get(k) for k in FIELDS}
    if vals["hit_type"] is None:
        vals["hit_type"] = classify(vals["launch_angle"])
    with db() as c:
        if seq is None:
            seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 s FROM shots WHERE session_id=?",
                            (session_id,)).fetchone()["s"]
        cols = ",".join(FIELDS)
        qs = ",".join("?" * len(FIELDS))
        c.execute(
            f"INSERT OR REPLACE INTO shots(session_id,seq,ts,{cols},trajectory,raw)"
            f" VALUES(?,?,?,{qs},?,?)",
            (session_id, seq, ts or time.time(), *[vals[k] for k in FIELDS],
             json.dumps(trajectory) if trajectory else None, json.dumps(rec, default=str)))
        return seq


def sessions():
    with db() as c:
        return [dict(r) for r in c.execute("""
            SELECT s.*, COUNT(sh.id) shot_count,
                   ROUND(AVG(sh.total_speed),1) avg_ev,
                   ROUND(MAX(sh.total_speed),1) max_ev,
                   ROUND(AVG(sh.launch_angle),1) avg_la
            FROM sessions s LEFT JOIN shots sh ON sh.session_id=s.id
            GROUP BY s.id ORDER BY s.started_at DESC""")]


def shots(session_id):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM shots WHERE session_id=? ORDER BY seq", (session_id,))]


def shots_since(session_id, after_seq):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM shots WHERE session_id=? AND seq>? ORDER BY seq",
            (session_id, after_seq))]
