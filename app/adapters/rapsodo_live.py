"""Live adapter for the Rapsodo RBB1.0.

SUPERSEDED BY ripe_sdk.py — read this for why.

The original plan was to reverse-engineer the unit's USB bulk protocol. That
failed: 4,295 blind probes produced zero responses. We now know exactly why,
and it was never a framing problem.

From the SDK's own RIPEBoxStateType state machine:

    BOX_STATE_INIT -> WAIT_FOR_CONNECTION -> WAIT_FOR_SYS_CONFIG
    -> DISARMED -> ARMED -> TRIGGERED -> TRANSFER

The box sits in **WAIT_FOR_SYS_CONFIG** until the host pushes it the sysConfig
struct (read from BB1Config.ini), and even once configured it will not trigger
until it is ARMED. An unconfigured, disarmed box correctly ignores everything.
No amount of guessing at packet framing could ever have worked.

The right way in is Rapsodo's own SDK, PlatformLib.dll, which does the config
push and arming for us. See adapters/ripe_sdk.py.

This module stays as a stub so nothing imports a half-built USB path by
accident, and so the failure mode is loud rather than silent.
"""
from .base import ShotSource


class RapsodoLive(ShotSource):
    name = "rapsodo-live-usb"

    def connect(self):
        raise NotImplementedError(
            "Direct USB capture is not the path. The unit waits in "
            "BOX_STATE_WAIT_FOR_SYS_CONFIG until a host pushes its config, so raw "
            "bulk probing cannot work.\n"
            "Use the SDK bridge instead: app/adapters/ripe_sdk.py, which calls "
            "Rapsodo's own PlatformLib.dll (32-bit Windows process, next to the "
            "hardware) and posts shots to this viewer's /api/shot endpoint."
        )

    def shots(self):
        raise NotImplementedError
