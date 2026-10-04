# Ant Esports GM333 Hardware & Lighting Controller for Linux

Comprehensive Linux tool for the **Ant Esports GM333 Gaming Mouse** (Instant Microelectronics `30fa:1440` controller).

Directly control all **16 onboard hardware lighting modes**, customize colors, speeds, brightness, and run the real-time **audio-reactive Music Sync visualizer** for Bluetooth earbuds, headphones, or speakers.

> 🚀 **Desktop GUI Application Available!**
> A full-featured native desktop application is located in [gm333-gui](file:///home/prince/Projects/gm333-gui). You can launch it with `gm333-gui` or open it from your system application menu!

---

## 🌈 Normal Lighting Modes

You can switch between any of the 16 hardware lighting modes directly using `gm333-mode` or `gm333-ctl`:

### Quick Commands
```bash
# 1. Neon rainbow wave (Factory ambient default)
gm333-mode neon

# 2. Smooth multi-color breathing effect
gm333-mode breathing --speed 3

# 3. Flowing water wave
gm333-mode wave

# 4. Comet streak trail
gm333-mode comet

# 5. Static solid color (e.g. cyan, red, blue, purple, #ff007f)
gm333-mode static --color cyan
gm333-mode static --color "#ff00ff"

# 6. Single-color breathing
gm333-mode single-breath --color red

# 7. Turn OFF all mouse LEDs
gm333-mode off

# 8. List all 16 modes
gm333-ctl list
```

*(Note: Whenever you set a normal lighting mode, the tool automatically pauses the background music-sync service so your selected lighting mode stays on.)*

---

### All 16 Built-in Hardware Modes
| Mode Name | ID | Description |
|-----------|----|-------------|
| `neon` | 7 | Neon (Default vibrant multi-color rainbow wave) |
| `breathing` | 2 | Cycle Breathing (Smooth multi-color breathing) |
| `static` | 3 | Light On (Solid constant color) |
| `wave` | 4 | Flowing Water (Continuous wave stream) |
| `mono-wave` | 5 | Mono Water (Single-color water wave) |
| `comet` | 6 | Comet Streak (Comet trail) |
| `ambilight` | 8 | Ambilight (Ambient dynamic glow) |
| `flicker` | 9 | Flicker (Dynamic rhythmic flicker) |
| `startrek` | 10 | Star Trek (Moving star pulses) |
| `ripple` | 11 | Ripple (Water drop ripple pulse) |
| `music` | 12 | Enraptured (Hardware Audio / Music Sync) |
| `reactive` | 13 | Button Response (Lights up when clicked) |
| `off` | 14 | LED Off (Turn off all LEDs) |
| `single-breath` | 15 | Single Breath (Breathes a single custom color) |
| `cycle-color` | 16 | Cycle Color (Step through colors) |
| `dpi-breath` | 1 | DPI Breathing (Breaths current DPI color) |

---

## 🎵 Music Sync (Audio Reactive RGB)

Sync mouse RGB LEDs with desktop audio playback in real time:

### Interactive Terminal Visualizer (with live VU Meter):
```bash
gm333-ctl music

# With different color palettes:
gm333-ctl music -p rainbow
gm333-ctl music -p sunset -s 1.5
```

### Background Service Management
```bash
# Resume background music sync:
gm333-ctl service start

# Pause background music sync:
gm333-ctl service stop

# Check status:
gm333-ctl service status
```

---

## Available Options & Flags
- `--color, -c`: Color name (`red`, `green`, `blue`, `cyan`, `magenta`, `purple`, `yellow`, `orange`, `pink`, `white`) or hex `#RRGGBB`.
- `--speed`: Speed multiplier from `1` (slow) to `7` (fast) (default: `2`).
- `--brightness, -b`: Brightness level from `0` (brightest) to `4` (dimmest).
