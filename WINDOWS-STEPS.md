# Windows steps — do these today (the unit is only available today)

## Priority

| Step | Needs the unit? | When |
|---|---|---|
| 1. Install the app | no | today (enables 2 & 3) |
| 2. Copy out `Assembly-CSharp.dll` | no | any time |
| 3. **Capture USB traffic** | **YES** | **TODAY — deadline-bound** |

Step 3 is the only one that expires. If time runs short, do 1 and 3, and get
the DLL later.

---

## 1. Get and install the app

Download (Rapsodo's own binary, preserved by the Internet Archive):

    https://web.archive.org/web/20180823052624if_/http://rapsodo.com/assets/apps/RapsodoBaseball_V1.1.exe

Verify before running:

    size    57,193,368 bytes
    sha256  1dd04887453361e7c097e0352a0f836ac48bb9fd45fcd32c6c255d8e94f8ccd6

In PowerShell:

    Get-FileHash .\RapsodoBaseball_V1.1.exe -Algorithm SHA256

It is a 2018 executable. Scan it (Defender, or virustotal.com) before running —
that is the user's call, not mine.

Install it. Default location is likely:

    C:\Program Files (x86)\Rapsodo\RapsodoPitching\
    C:\Program Files\Rapsodo\RapsodoPitching\

NOTE: this is the **Pitching** app; this unit is a HITTING unit. It may refuse
the device. That is expected and does not waste the exercise — see step 3.

## 2. Copy out the Unity assembly

Find, in the install folder:

    RapsodoPitching_Data\Managed\Assembly-CSharp.dll

Copy it somewhere shareable. This is .NET IL and decompiles to readable C#;
if the USB protocol is implemented there we can read it as source instead of
inferring it from captured bytes. Grab the whole `Managed\` folder if easy —
sibling DLLs may hold the transport layer.

Also worth copying if present: anything in `Plugins\` (native USB code often
lives there), and any `.inf` / `.sys` driver files in the install folder.

## 3. Capture the USB traffic  ← TIME-CRITICAL

1. Install **Wireshark** from https://www.wireshark.org/download.html
   During setup, TICK THE **USBPcap** COMPONENT. It is not selected by default.
2. **Reboot** (USBPcap installs a driver).
3. Plug the Rapsodo into the PC **directly, not through a hub**, using the
   data cable that worked on the Mac.
4. Open Wireshark. In the interface list you will see `USBPcap1`, `USBPcap2`, ...
   Each is one root hub. Pick the one the unit is on — if unsure, start a
   capture on each in turn and watch for traffic when you unplug/replug.
5. Start capturing, THEN launch the Rapsodo app, and let it try to connect.
6. Let it run ~60 s. Do whatever the app offers: connect, pair, start session.
   Even an error like "wrong device" is useful — the handshake happens first.
7. Stop the capture, File → Save As → `rapsodo-usb.pcapng`.

Send that file back. It contains every byte written to EP 0x01 and read from
EP 0x81 — the command vocabulary that 4,295 blind probes could not find.

### If the app will not start or demands registration
Capture anyway. Enumeration and the initial handshake normally happen before
any login gate, so the capture is likely still worth having.

### If USBPcap shows nothing
The unit may be on a different root hub. Try each `USBPcapN` interface.
Unplugging and replugging the unit while capturing produces obvious traffic
and identifies the right one.
