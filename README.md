# lmu-dualsense

Real-time adaptive trigger and haptic rumble feedback for **Le Mans Ultimate** (and Assetto Corsa Competizione) on Linux using a PS5 DualSense controller.

Reads live telemetry from the game via shared memory and drives the DualSense at 100 Hz:

| Output | Behaviour |
|--------|-----------|
| **L2 – Brake trigger** | Progressive resistance with configurable bite point; pulses during front wheel lock-up or ABS activation — pulse intensity scales with slip severity |
| **R2 – Throttle trigger** | Light resistance at idle scaling to full throttle; pulses during rear wheelspin — pulse intensity scales with slip severity |
| **Left grip motor** | Rumbles proportional to left-side wheel slip (FL + RL) — fires during lock-up, wheelspin, and slides; adds subtle engine RPM drone |
| **Right grip motor** | Same as left, driven by right-side wheels (FR + RR) — gives directional lock-up and wheelspin feel |

ABS detection works for all car classes: cars **with ABS** (LMGT3) fire the pulse when ABS intervenes; cars **without ABS** (LMP2, LMP3, Hypercar) fire the pulse on wheel lock-up. Full-lock produces a more violent pulse than ABS-modulated slip because forces scale with actual grip loss.

Both games are auto-detected at startup. Assetto Corsa Competizione is fully supported alongside LMU.

---

## Requirements

| | |
|---|---|
| **OS** | Linux (tested on Bazzite / Fedora Atomic) |
| **Game** | Le Mans Ultimate or Assetto Corsa Competizione via Steam + Proton |
| **Controller** | PS5 DualSense (USB recommended; Bluetooth works) |
| **Python** | 3.11 or newer |
| **LMU only** | [LMU_SharedMemoryMapPlugin](https://github.com/tembob64/LMU_SharedMemoryMapPlugin) DLL (see Step 1) |

---

## Installation

### Step 1 — Install the game telemetry plugin (LMU only)

Le Mans Ultimate does not expose telemetry by default. A plugin DLL must be installed to create the shared memory buffer this tool reads. Skip this step for ACC — it exposes shared memory natively.

**Download** the latest `LMU_SharedMemoryMapPlugin64.zip` from:

> [github.com/tembob64/LMU_SharedMemoryMapPlugin/releases](https://github.com/tembob64/LMU_SharedMemoryMapPlugin/releases)

Extract `LMU_SharedMemoryMapPlugin64.dll` and copy it into the game's `Plugins/` folder:

```
~/.steam/steam/steamapps/common/Le Mans Ultimate/Plugins/LMU_SharedMemoryMapPlugin64.dll
```

> The `Plugins/` folder may not exist yet — create it if needed.

Then open (or create) `<LeMansUltimate>/UserData/player/CustomPluginVariables.JSON` and add:

```json
"LMU_SharedMemoryMapPlugin64.dll": {
  "Enabled": 1,
  "EnableDirectMemoryAccess": 1
}
```

**Verify:** Launch Le Mans Ultimate and load into a session, then check:

```bash
ls /dev/shm/ | grep -i rFactor2
```

You should see an entry containing `rFactor2SMMP_Telemetry`.

---

### Step 2 — Allow DualSense hidraw access (one-time)

By default, hidraw devices require root. Install the provided udev rule to grant your user access:

```bash
sudo cp udev/99-dualsense.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Reconnect or re-pair your controller afterwards.

---

### Step 3 — Install lmu-dualsense

```bash
git clone https://github.com/nicolas-law/lmu-dualsense.git
cd lmu-dualsense
pip install -e .
```

For development (tests, linter, type checker):

```bash
pip install -e ".[dev]"
```

> **Tip:** Use a virtual environment (`python -m venv .venv && source .venv/bin/activate`) to keep dependencies isolated.

---

### Step 4 — Steam launch options (optional but recommended)

Run lmu-dualsense automatically with the game. In Steam → Le Mans Ultimate → Properties → **Launch Options**:

```
WINEDLLOVERRIDES="LMU_SharedMemoryMapPlugin64=n,b;rFactor2SharedMemoryMapPlugin64_Wine=n,b" bash -c '/path/to/lmu-dualsense & PID1=$!; lmu-dualsense-gui & PID2=$!; %command%; kill $PID1 $PID2'
```

Replace `/path/to/lmu-dualsense` with the output of `which lmu-dualsense`.

---

## Running

Start your game and load into a session, then:

```bash
# Headless — trigger and rumble effects only
lmu-dualsense

# With live GUI — telemetry display and real-time tuning sliders
lmu-dualsense-gui
```

The tool retries every 5 seconds until shared memory is found. Press **Ctrl-C** to stop cleanly — motors and triggers are reset on exit.

---

## Configuration

All defaults are tuned for a good out-of-the-box feel. Everything can be adjusted live via the GUI or by editing `src/lmu_dualsense/config.py`.

### Trigger config (L2 / R2)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `brake_threshold` | `0.50` | Brake input % where resistance shifts from easy to hard zone (the "bite point") |
| `brake_easy_resistance` | `0` | Resistance in the easy zone (0 = natural spring feel) |
| `brake_max_resistance` | `255` | Resistance at 100% brake input |
| `abs_grip_threshold` | `0.10` | Front wheel slip above this during braking triggers the ABS/lock-up pulse |
| `throttle_base_resistance` | `5` | Trigger weight at idle |
| `throttle_max_resistance` | `70` | Trigger weight at full throttle |
| `wheelspin_grip_threshold` | `0.12` | Rear wheel slip above this during acceleration triggers the wheelspin pulse |

`wheel_grip` values are the raw `mGripFract` field from the game: `0.0` = full grip, `~1.0` = full slide.

### Rumble config (grip motors)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `True` | Master toggle for grip motor rumble |
| `grip_max_intensity` | `180` | Motor intensity (0–255) at full wheel slide |
| `grip_threshold` | `0.08` | Wheel slip below this produces no grip rumble |
| `engine_max_intensity` | `20` | Max intensity of the background engine RPM drone (keep low) |

---

## How it works

```
Le Mans Ultimate (Proton / Wine)
  └─ LMU_SharedMemoryMapPlugin64.dll
       └─ /dev/shm/$rFactor2SMMP_Telemetry$   ← Wine exposes named shm here

lmu-dualsense (100 Hz loop)
  ├─ SharedMemoryProvider     maps the file, deserialises rF2VehicleTelemetry via ctypes
  ├─ compute_effects()        pure function: TelemetryState → (L2 TriggerEffect, R2 TriggerEffect)
  ├─ compute_rumble()         pure function: TelemetryState → RumbleEffect (left, right motors)
  └─ DualSenseController      writes effects via pydualsense; skips redundant HID writes
```

The binary struct layout is mirrored in `telemetry/structs.py` using `ctypes.Structure` with `_pack_ = 4`, matching the plugin's `#pragma pack(push, 4)` — verified against CrewChief V4's reference implementation.

---

## Development

```bash
pytest           # 30 unit tests — no hardware or game required
ruff check src   # linter
mypy src         # type checker
```

The effect calculation layer (`controller/effects.py`) is entirely pure and tested independently of the game and controller hardware.

---

## Troubleshooting

**No shared memory found**
- Confirm the DLL is in `Plugins/`, `CustomPluginVariables.JSON` has `"Enabled": 1`, and the game is in an active session (not the main menu).
- Check: `ls /dev/shm/ | grep -i rFactor2`
- Wine 6+ is required for `/dev/shm/` exposure.

**Permission denied on hidraw**
- Re-run the udev steps from Step 2 and reconnect the controller.
- Verify with: `ls -l /dev/hidraw*`

**Triggers feel too strong / too weak**
- Open the GUI (`lmu-dualsense-gui`) and adjust sliders live while driving.
- For brakes: lower `brake_threshold` to move the bite point earlier; raise `brake_max_resistance` for a heavier pedal feel.
- For throttle: raise `wheelspin_grip_threshold` if wheelspin feedback triggers too early on corner exit.

**Grip motors not rumbling**
- Check the "GRIP RUMBLE MOTORS" section in the GUI — confirm `enabled` is checked.
- Lower `grip_threshold` if rumble feels too subtle; raise `grip_max_intensity` for stronger feedback.

**Game not detected**
- For LMU: ensure the shared memory plugin is installed and the game is in an active session.
- For ACC: the `acpmf_physics` shared memory file should appear in `/dev/shm/` automatically when ACC is in a session.
