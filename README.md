# lmu-dualsense

Adaptive trigger feedback for **Le Mans Ultimate** on Linux using a PS5 DualSense controller.

Reads live telemetry from the game via shared memory and drives the DualSense adaptive triggers in real time:

| Trigger | Behaviour |
|---------|-----------|
| **L2 – Brake** | Resistance proportional to brake input; switches to rapid pulse when ABS activates |
| **R2 – Throttle** | Light resistance at idle; switches to pulse chatter when rear wheels spin |

---

## Requirements

- **OS**: Linux (tested on Bazzite / Fedora)
- **Game**: Le Mans Ultimate via Steam + Proton
- **Controller**: PS5 DualSense (USB or Bluetooth)
- **Python**: 3.11+
- **Game plugin**: [LMU_SharedMemoryMapPlugin](https://github.com/tembob64/LMU_SharedMemoryMapPlugin) (see below)

---

## 1 — Install the game plugin

Le Mans Ultimate does not expose telemetry by default. A plugin DLL must be installed to create the shared memory buffer this tool reads.

### Which plugin

Use **tembob64's LMU_SharedMemoryMapPlugin** — an LMU-specific fork maintained through 2025, with binaries hosted directly on GitHub:

> **Download**: [github.com/tembob64/LMU_SharedMemoryMapPlugin/releases](https://github.com/tembob64/LMU_SharedMemoryMapPlugin/releases)
>
> Get the latest `LMU_SharedMemoryMapPlugin64.zip` and extract `LMU_SharedMemoryMapPlugin64.dll`.

This is the same shared memory format used by [CrewChief V4](https://gitlab.com/mr_belowski/CrewChiefV4), the reference implementation for LMU telemetry.

### Copy the DLL into LMU

```
<Steam library>/steamapps/common/Le Mans Ultimate/Plugins/
```

Typical full path on Bazzite (the game root, **not** a Bin64 subfolder):

```
~/.steam/steam/steamapps/common/Le Mans Ultimate/Plugins/LMU_SharedMemoryMapPlugin64.dll
```

> **Note**: The `Plugins/` folder may not exist yet — create it if needed.

### Enable in CustomPluginVariables.json

Open (or create) `<LeMansUltimate>/UserData/player/CustomPluginVariables.JSON` and add:

```json
"LMU_SharedMemoryMapPlugin64.dll": {
  "Enabled": 1,
  "EnableDirectMemoryAccess": 1
}
```

### Verify

Launch Le Mans Ultimate and load into a session. Check that the shared memory file appears:

```bash
ls /dev/shm/ | grep -i rFactor2
```

You should see an entry containing `rFactor2SMMP_Telemetry`.

---

## 2 — Allow DualSense hidraw access (one-time)

By default, hidraw devices require root. Install the provided udev rule to allow your user:

```bash
sudo cp udev/99-dualsense.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Reconnect or re-pair your controller afterwards.

---

## 3 — Install lmu-dualsense

```bash
git clone https://github.com/nicolas-law/lmu-dualsense.git
cd lmu-dualsense
pip install -e .
```

For development (tests, linter, type checker):

```bash
pip install -e ".[dev]"
```

---

## 4 — Run

Start Le Mans Ultimate and get into a session, then:

```bash
lmu-dualsense
```

The tool will wait (retrying every 5 s) until the shared memory appears, then begin sending trigger effects at 100 Hz. Press **Ctrl-C** to stop cleanly.

---

## Configuration

All tunable values live in `src/lmu_dualsense/config.py`:

```python
@dataclass
class TriggerConfig:
    throttle_base_resistance: int = 25      # idle feel (0–255)
    throttle_max_resistance: int = 70       # full-throttle feel (0–255)
    wheelspin_grip_threshold: float = 0.12  # rear mGripFract → wheelspin pulse

    brake_max_resistance: int = 220         # full-brake feel (0–255)
    abs_grip_threshold: float = 0.15        # front mGripFract → ABS pulse
```

`mGripFract` is the per-wheel sliding fraction: `0.0` = full grip, `~1.0` = full slide.

---

## How it works

```
Le Mans Ultimate (Proton)
  └─ LMU_SharedMemoryMapPlugin64.dll
       └─ /dev/shm/$rFactor2SMMP_Telemetry$   ← Wine exposes this on Linux

lmu-dualsense
  ├─ SharedMemoryProvider   maps the file, deserialises rF2VehicleTelemetry via ctypes
  ├─ compute_effects()      pure functions: TelemetryState → TriggerEffect
  └─ DualSenseController    writes effects via pydualsense; skips redundant HID writes
```

The binary struct layout is mirrored in `telemetry/structs.py` using `ctypes.Structure`
with `_pack_ = 4`, matching the plugin's `#pragma pack(push, 4)` — verified against
CrewChief V4's `[StructLayout(LayoutKind.Sequential, Pack=4)]`.

---

## Development

```bash
pytest           # unit tests (no hardware required)
ruff check src   # linter
mypy src         # type checker
```

The effect calculation layer (`controller/effects.py`) is entirely pure and tested independently of the game and controller.

---

## Troubleshooting

**No shared memory found**
- Confirm the DLL is in `Plugins/`, the JSON config has `"Enabled": 1`, and the game is in an active session (not the main menu).
- Check: `ls /dev/shm/ | grep -i rFactor2`
- Wine 6+ is required for `/dev/shm/` exposure.

**Permission denied on hidraw**
- Re-run the udev steps and reconnect the controller.
- Verify with: `ls -l /dev/hidraw*`

**Wrong trigger feel**
- Adjust the thresholds in `config.py`. Lower `wheelspin_grip_threshold` if wheelspin feedback triggers too late; raise it if it fires on normal cornering.
