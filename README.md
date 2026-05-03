# sim-dualsense

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Real-time adaptive trigger and haptic rumble feedback for sim racing on Linux using a PS5 DualSense controller.

Reads live telemetry from the game via shared memory and drives the DualSense at 100 Hz:

| Output | Behaviour |
|--------|-----------|
| **L2 – Brake trigger** | Progressive resistance with configurable bite point; pulses during front wheel lock-up or ABS activation — intensity scales with slip severity |
| **R2 – Throttle trigger** | Light resistance at idle scaling to full throttle; pulses during rear wheelspin — intensity scales with slip severity |
| **Left grip motor** | Rumbles proportional to left-side wheel slip (FL + RL) — fires during lock-up, wheelspin, and slides |
| **Right grip motor** | Same, driven by right-side wheels (FR + RR) — gives directional lock-up and wheelspin feel |

ABS detection works for all car classes: cars **with ABS** (LMGT3) pulse during ABS intervention; cars **without ABS** (LMP2, LMP3, Hypercar) pulse on wheel lock-up. Full lock produces a more violent pulse than ABS-modulated slip because intensity scales with actual grip loss.

---

## Game support

| Game | Status |
|------|--------|
| **Le Mans Ultimate** | Tested and working — requires the shared memory plugin (see Step 1) |
| **Assetto Corsa Competizione** | Should work — ACC exposes shared memory natively, but untested |

---

## Installation

### Download the binary (recommended)

Go to the [Releases](https://github.com/nicolas-law/sim-dualsense/releases) page, download the latest `sim-dualsense` binary, then:

```bash
chmod +x sim-dualsense
./sim-dualsense
```

> **Note:** You still need to complete Steps 1 and 2 below before running.

---

### Step 1 — Install the LMU telemetry plugin (Le Mans Ultimate only)

Le Mans Ultimate does not expose telemetry by default. Skip this step entirely for ACC.

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

**Verify:** Launch Le Mans Ultimate, load into a session, then check:

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

## Running

Start your game and load into a session first, then run:

```bash
./sim-dualsense
```

This opens the live overlay with telemetry display and real-time tuning sliders. The tool retries every 5 seconds until shared memory is found. Press **Ctrl-C** or close the window to stop cleanly — motors and triggers are reset on exit.

---

## Configuration

All defaults are tuned for a good out-of-the-box feel. Everything can be adjusted live via the GUI sliders.

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
       └─ /dev/shm/$rFactor2SMMP_Telemetry$

sim-dualsense (100 Hz loop)
  ├─ SharedMemoryProvider     maps the file, deserialises rF2VehicleTelemetry via ctypes
  ├─ compute_effects()        TelemetryState → (L2 TriggerEffect, R2 TriggerEffect)
  ├─ compute_rumble()         TelemetryState → RumbleEffect (left motor, right motor)
  └─ DualSenseController      writes effects via pydualsense; skips redundant HID writes
```

---

## Install from source (developers)

```bash
git clone https://github.com/nicolas-law/sim-dualsense.git
cd sim-dualsense
pip install -e ".[dev]"
sim-dualsense
```

```bash
pytest           # 30 unit tests — no hardware or game required
ruff check src   # linter
mypy src         # type checker
```

---

## Troubleshooting

**No shared memory found**
- Confirm the DLL is in `Plugins/`, `CustomPluginVariables.JSON` has `"Enabled": 1`, and the game is in an active session (not the main menu).
- Check: `ls /dev/shm/ | grep -i rFactor2`

**Permission denied on hidraw**
- Re-run the udev steps from Step 2 and reconnect the controller.
- Verify with: `ls -l /dev/hidraw*`

**Triggers feel too strong / too weak**
- Open the GUI and adjust sliders live while driving.
- For brakes: lower `brake_threshold` to move the bite point earlier.
- For throttle: raise `wheelspin_grip_threshold` if wheelspin feedback triggers too early on corner exit.

**Grip motors not rumbling**
- Check the "GRIP RUMBLE MOTORS" section in the GUI — confirm `enabled` is checked.
- Lower `grip_threshold` if rumble feels too subtle.

**ACC not working**
- Check that `/dev/shm/acpmf_physics` exists while ACC is in a session.
- ACC support is untested — open an issue if you run into problems.
