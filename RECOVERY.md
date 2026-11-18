# Recovery attempts without opening the case

No prior art exists — nobody has published reverse-engineering or repair work on
a Rapsodo baseball unit. So this is reasoned from the hardware, not copied.

**The goal is not to make the app work. It is to make the unit enumerate as
something other than `0x4003:0x0002`.** Specifically ST's ROM DFU bootloader,
`0x0483:0xDF11`. That bootloader is burned into the STM32's silicon, cannot be
erased or corrupted, and does not care that the application firmware is dead.
If it ever appears, we flash `BB1.bin` with the free `dfu-util` and the unit is
repaired — no case, no soldering, no cost.

## Run the watcher first

```bash
python3 tools/usbwatch.py
```

Leave it running for everything below. It timestamps every USB appearance,
disappearance and VID/PID change, so you can tell exactly which action caused
what. It flags `0x0483:0xDF11` loudly if it ever shows up.

## 1. Deep-discharge reset  (free, do this first, zero risk)

Unplug everything and leave the unit until the battery is completely flat —
overnight is ideal, and this unit self-discharges quickly anyway. Then charge it
from dead on the 1 A wall charger for an hour before reconnecting.

Why: this is the only true cold reset available from outside. It clears latched
hardware state, drains every rail and rail-capacitor, and wipes SRAM completely,
including any corrupt state a watchdog keeps rebooting into. On embedded devices
this recovers weird states surprisingly often, and it is the single most likely
free fix.

## 2. Button-at-power-on combinations  (free, the real hope)

Many devices expose a recovery or DFU mode via the power button held during
boot. This unit has exactly one button, so the search space is small: run
through it systematically with the watcher running, pausing ~10 s between
attempts so changes are attributable.

| # | Sequence |
|---|---|
| 1 | Hold power, THEN plug USB in, keep holding 10 s |
| 2 | Same, hold 20 s |
| 3 | Same, hold 30 s |
| 4 | Plug USB in first, then hold power 10 / 20 / 30 s |
| 5 | Double-tap power quickly, then hold |
| 6 | Hold power while plugging in, release the moment it enumerates |
| 7 | With it running, hold power through the auto-power-off and past it |

Watch for ANY new VID:PID. A vendor recovery mode would also be a win even if
it is not ST DFU.

## 3. Case flex  (free, zero risk — the sane version of the Xbox oven trick)

With the watcher running and the unit plugged in, apply gentle, even pressure to
the case — twist slightly, press the corners, press around the USB port — and
watch for the device appearing or dropping.

Why: the Xbox 360 reflow worked because it briefly remelted cracked BGA solder
joints. The same fault class — a cracked or cold joint on the USB PHY, the
STM32, or the FPGA — would show here as enumeration that changes under
mechanical stress. If pressing a specific spot makes it appear or vanish, that
is a diagnosis: it is a physical joint, not firmware, and no software will ever
fix it.

## 4. Cold start  (free, low risk)

Leave it somewhere cool (not a freezer — condensation) for an hour, then plug it
in and watch the first 60 s. Marginal silicon and cracked joints are often
temperature-sensitive, and behaviour that changes with temperature points at
hardware rather than firmware.

## NOT the oven. Seriously.

The Xbox reflow trick does not transfer here, and it is the one idea on this
page that could hurt you. This unit has a **lithium-polymer battery sealed
inside**, and it is already a failing one. Heating a sealed LiPo is how you get
a fire. Doing it safely would mean removing the battery first — which means
opening the case, which is what you are trying to avoid.

The heat-gun/reflow family of fixes is off the table until the case is open and
the battery is out.

## If `0x0483:0xDF11` ever appears

Stop and report it. Then:

```bash
brew install dfu-util
dfu-util -l                     # confirm the device
# BB1.bin is linked at 0x08020000 — flashing at the wrong offset would
# destroy the bootloader below it, so we verify the offset before writing.
```

`BB1.bin` (377,328 bytes) is on the Windows box at
`C:\Rapsodo\RapsodoPitching\RapsodoPitching_Data\StreamingAssets\`.

**Do not run a flash command without checking in first.** The write offset is
the one detail that turns a repair into a brick, and the bootloader is the only
thing keeping this recoverable.
