#!/usr/bin/env python3
"""
Ant Esports GM333 Native Linux Music Sync Visualizer
Reverse-engineered for Instant Microelectronics / Ant Esports GM333 controller (30fa:1440).
Captures desktop audio in real time via PipeWire/PulseAudio monitor sinks
and drives mouse RGB lighting via USB HID Feature Reports (Report ID 0x07).
"""

import sys
import os
import time
import math
import struct
import signal
import fcntl
import argparse
import subprocess
import glob

HID_DEVICE_LINK = "/dev/input/by-id/usb-INSTANT_USB_GAMING_MOUSE-if01-hidraw"
HIDIOCSFEATURE_8 = 0xc0084806

def get_user_audio_env():
    """When running as root (sudo), pactl/parec can't connect to the user's PipeWire
    session because XDG_RUNTIME_DIR is unset or wrong. Detect the real user's runtime
    directory from /run/user/* and inject it into the subprocess environment."""
    env = os.environ.copy()
    if os.geteuid() == 0 and ("XDG_RUNTIME_DIR" not in env or not os.path.isdir(env.get("XDG_RUNTIME_DIR", ""))):
        # Find the first valid user runtime dir (e.g. /run/user/1000)
        for uid_dir in sorted(glob.glob("/run/user/[0-9]*")):
            pulse_sock = os.path.join(uid_dir, "pulse", "native")
            pipewire_sock = os.path.join(uid_dir, "pipewire-0")
            if os.path.exists(pulse_sock) or os.path.exists(pipewire_sock):
                env["XDG_RUNTIME_DIR"] = uid_dir
                uid = os.path.basename(uid_dir)
                env["PULSE_RUNTIME_PATH"] = os.path.join(uid_dir, "pulse")
                # DBUS address for PipeWire
                dbus_addr = f"unix:path={uid_dir}/bus"
                if os.path.exists(f"{uid_dir}/bus"):
                    env["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
                break
    return env

USER_AUDIO_ENV = get_user_audio_env()

# Mode 3 = Direct Static Sync (firmware-native music sync mode)
# B3 = 0x80 | (3<<4) | speed_bits = 0xb2; B6 = 0x00 (mode 3 < 8)
PKT_INIT_SYNC   = bytes([0x07, 0x13, 0x80, 0xb2, 0x1b, 0x00, 0x00, 0x02])

# Mode 14 = Turn LEDs Off (hardware kill, no zone registers needed)
# B3 = 0x80 | (14<<4) & 0xff = 0xe2 truncated... actually B3=0x62 from original
# B6 = 0x80 (mode 14 >= 8)
PKT_MODE_OFF    = bytes([0x07, 0x13, 0x80, 0x62, 0x1b, 0x00, 0x80, 0x02])

# Mode 6: Neon Wave (ambient restore on shutdown)
PKT_RESTORE_NEON = bytes([0x07, 0x13, 0xff, 0xe2, 0x1b, 0x04, 0x00, 0x02])

# Volume-to-firmware-level table: 0=loudest, 7=quietest
# Maps normalized volume (0..1) to firmware sound level code
LEVEL_CODES = [7, 5, 5, 4, 4, 3, 3, 2, 2, 0]

# Predefined Color Palettes (R, G, B in 4-bit nibbles: 0..15)
PALETTES = {
    "cyberpunk": [(15, 0, 15), (0, 15, 15), (15, 0, 4), (0, 8, 15)],
    "rainbow":   [(15, 0, 0), (15, 8, 0), (15, 15, 0), (0, 15, 0), (0, 15, 15), (0, 0, 15), (15, 0, 15)],
    "sunset":    [(15, 1, 0), (15, 6, 0), (15, 12, 0), (12, 0, 8), (6, 0, 12)],
    "ocean":     [(0, 4, 15), (0, 12, 15), (0, 15, 10), (0, 15, 15)],
    "fire":      [(15, 0, 0), (15, 4, 0), (15, 10, 0), (15, 15, 2)],
    "emerald":   [(0, 15, 2), (0, 15, 8), (4, 15, 0), (0, 12, 4)],
    "red":       [(15, 0, 0)],
    "blue":      [(0, 2, 15)],
    "cyan":      [(0, 15, 15)],
    "purple":    [(12, 0, 15)],
    "green":     [(0, 15, 0)],
    "white":     [(15, 15, 15)],
}

running = True

def handle_signal(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def get_hid_fd():
    """Locate and open the GM333 Interface 1 hidraw device with read/write permissions."""
    if os.path.exists(HID_DEVICE_LINK):
        try:
            return os.open(HID_DEVICE_LINK, os.O_RDWR)
        except Exception as e:
            print(f"[!] Error opening {HID_DEVICE_LINK}: {e}", file=sys.stderr)

    # Fallback scan across all hidraw devices
    for hpath in sorted(glob.glob("/dev/hidraw*")):
        num = os.path.basename(hpath).replace("hidraw", "")
        uevent_path = f"/sys/class/hidraw/hidraw{num}/device/uevent"
        if os.path.exists(uevent_path):
            try:
                with open(uevent_path) as f:
                    content = f.read()
                # 30FA:1440 interface 1 (input1)
                if "30FA" in content and "1440" in content and "input1" in content:
                    return os.open(hpath, os.O_RDWR)
            except Exception:
                pass
    return None

def send_feature_report(fd, pkt):
    if fd is None:
        return
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE_8, pkt)
    except Exception:
        pass

def commit_config(fd):
    """Sends Report 0x18 hardware commit trigger to apply registers.
    IMPORTANT: Only call this during initialization / shutdown.
    Calling 0x18 in the per-frame audio loop causes the firmware to
    re-latch from the stored profile register, reverting to neon wave
    or triggering the DPI blue indicator flash.
    """
    if fd is None:
        return
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE_8, bytes([0x07, 0x18, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]))
        time.sleep(0.005)
        fcntl.ioctl(fd, HIDIOCSFEATURE_8, bytes([0x07, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
    except Exception:
        pass

def get_current_monitor_target():
    """Detect current active default audio sink monitor in PipeWire/PulseAudio."""
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"],
                                       stderr=subprocess.DEVNULL,
                                       env=USER_AUDIO_ENV).decode().strip()
        if sink:
            return f"{sink}.monitor"
    except Exception:
        pass
    return None

def render_meter(rms, norm, is_beat, width=28):
    filled = int(norm * width)
    bar = "█" * filled + "░" * (width - filled)
    beat_str = " \033[1;31m⚡ [BEAT]\033[0m" if is_beat else "         "
    return f"\033[1;36m[\033[0m{bar}\033[1;36m]\033[0m RMS: {rms:5.0f} ({norm*100:3.0f}%){beat_str}"

def main():
    parser = argparse.ArgumentParser(description="Ant Esports GM333 Linux Music Sync Visualizer")
    parser.add_argument("--palette", "-p", choices=list(PALETTES.keys()), default="cyberpunk",
                        help="Color theme (default: cyberpunk)")
    parser.add_argument("--sensitivity", "-s", type=float, default=1.0,
                        help="Audio sensitivity multiplier (default: 1.0, higher = reactive to softer audio)")
    parser.add_argument("--fps", type=int, default=24,
                        help="Target update frequency in FPS (default: 24)")
    args = parser.parse_args()

    print("\033[1;35m========================================================\033[0m")
    print("\033[1;37m     Ant Esports GM333 Native Linux Music Sync          \033[0m")
    print("\033[1;35m========================================================\033[0m")

    # NEVER run as root: sudo breaks PipeWire/PulseAudio socket ownership
    # (/run/user/1000/pulse gets chowned to root, breaking all user audio)
    # The udev rule (MODE="0666") already grants HID access without sudo.
    if os.geteuid() == 0:
        print("\033[1;31m[!] ERROR: Do NOT run this script with sudo!\033[0m", file=sys.stderr)
        print("    Running as root corrupts PipeWire socket permissions.", file=sys.stderr)
        print("    The udev rule already grants HID access. Just run:", file=sys.stderr)
        print("    python3 gm333-music-sync.py", file=sys.stderr)
        sys.exit(1)

    hid_fd = get_hid_fd()
    if hid_fd is None:
        print("\033[1;31m[!] Could not open Ant Esports GM333 mouse.\033[0m", file=sys.stderr)
        print("    Ensure permissions: /dev/input/by-id/usb-INSTANT_USB_GAMING_MOUSE-if01-hidraw", file=sys.stderr)
        sys.exit(1)


    # Enter Mode 3 (firmware-native music sync engine) — no commit needed
    send_feature_report(hid_fd, PKT_INIT_SYNC)
    time.sleep(0.04)

    palette_colors = PALETTES[args.palette]
    color_idx = 0

    # Send initial color to all 8 zones
    init_r, init_g, init_b = palette_colors[0]
    for z in range(8):
        send_feature_report(hid_fd, bytes([0x07, 0x14,
                                           (z << 5) | (init_r & 0x0f),
                                           ((init_g & 0x0f) << 4) | (init_b & 0x0f),
                                           0, 0, 0, 0]))

    # Adaptive Audio Tracking variables
    noise_floor = 150.0
    peak_ceiling = 12000.0
    last_send_time = 0
    last_beat_time = 0
    last_ui_time = 0
    prev_rms = 0.0
    energy_fast = 0.0
    energy_slow = 0.0
    smooth_norm = 0.0

    print("\033[1;33m[*] Listening to active desktop audio (earbuds, headphones, speakers)...\033[0m\n")

    while running:
        monitor = get_current_monitor_target()
        if not monitor:
            sys.stdout.write("\r\033[2K[...] Waiting for active audio sink (earbuds/speakers)...")
            sys.stdout.flush()
            time.sleep(1.0)
            continue

        print(f"\033[1;34m[+] Connected Audio Sink:\033[0m {monitor}")

        # Start low-latency parec process on monitor sink
        cmd = ["parec", "-d", monitor, "--format=s16le", "--channels=1", "--rate=22050", "--latency-msec=25"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=USER_AUDIO_ENV)
        except FileNotFoundError:
            # Fallback to standard parec without latency param if older version
            cmd = ["parec", "-d", monitor, "--format=s16le", "--channels=1", "--rate=22050"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=USER_AUDIO_ENV)

        chunk_samples = 512
        chunk_bytes = chunk_samples * 2
        no_sound_ticks = 0
        is_hardware_off = False  # Mode 3 is active from startup

        try:
            while running:
                raw = proc.stdout.read(chunk_bytes)
                if not raw or len(raw) < chunk_bytes:
                    time.sleep(0.01)
                    new_monitor = get_current_monitor_target()
                    if new_monitor != monitor:
                        print(f"\n[*] Audio output device changed -> {new_monitor}")
                        break
                    continue

                samples = struct.unpack(f"<{chunk_samples}h", raw)
                sum_sq = sum(s * s for s in samples)
                rms = math.sqrt(sum_sq / chunk_samples)

                now = time.time()

                # Dynamic Automatic Gain Control (AGC)
                if rms > 50:
                    no_sound_ticks = 0
                    noise_floor = (noise_floor * 0.98) + (min(rms, noise_floor) * 0.02)
                    if rms > peak_ceiling:
                        peak_ceiling = (peak_ceiling * 0.70) + (rms * 0.30)
                    else:
                        peak_ceiling = max(800.0, peak_ceiling * 0.999)
                else:
                    no_sound_ticks += 1

                # Calculate normalized intensity (0.0 to 1.0)
                eff_floor = max(80.0, noise_floor / args.sensitivity)
                eff_ceiling = max(eff_floor + 400.0, peak_ceiling / args.sensitivity)
                norm = max(0.0, min(1.0, (rms - eff_floor) / (eff_ceiling - eff_floor)))

                # Beat Detection & Energy tracking
                delta = rms - prev_rms
                energy_fast = (energy_fast * 0.55) + (rms * 0.45)
                energy_slow = (energy_slow * 0.95) + (rms * 0.05)

                # Beat detection — tight thresholds to avoid false triggers
                beat_thresh = 1.40 / args.sensitivity
                delta_thresh = 300.0 / args.sensitivity
                is_beat = False
                if rms > 200.0 and norm > 0.40:
                    if (now - last_beat_time) > 0.25:
                        if (energy_fast > (energy_slow * beat_thresh) and delta > delta_thresh) or (norm > 0.85 and delta > 350.0):
                            is_beat = True
                            last_beat_time = now
                            color_idx = (color_idx + 1) % len(palette_colors)

                prev_rms = rms

                # Smooth loudness tracking
                if norm <= 0.01:
                    smooth_norm = smooth_norm * 0.75
                    if smooth_norm < 0.01:
                        smooth_norm = 0.0
                elif norm > smooth_norm:
                    smooth_norm = (smooth_norm * 0.20) + (norm * 0.80)
                else:
                    smooth_norm = (smooth_norm * 0.85) + (norm * 0.15)

                # Throttled LED updates to maintain smooth frame rate
                min_interval = 1.0 / max(10, min(args.fps, 40))
                if (now - last_send_time) >= min_interval:
                    last_send_time = now

                    if no_sound_ticks > 40:
                        # SILENCE: Mode 14 hardware LED off (sent once on transition)
                        if not is_hardware_off:
                            send_feature_report(hid_fd, PKT_MODE_OFF)
                            is_hardware_off = True
                    else:
                        # ACTIVE: direct brightness-scaled color streaming
                        if is_hardware_off:
                            # Wake up: re-enter Mode 3 sync mode
                            send_feature_report(hid_fd, PKT_INIT_SYNC)
                            time.sleep(0.03)
                            is_hardware_off = False

                        # Get current palette color (changes only on beat)
                        r_base, g_base, b_base = palette_colors[color_idx % len(palette_colors)]

                        # Scale brightness 0..15 by smooth_norm (perceptual curve)
                        eff = min(1.0, smooth_norm ** 0.75)
                        r_s = max(0, min(15, int(round(r_base * eff))))
                        g_s = max(0, min(15, int(round(g_base * eff))))
                        b_s = max(0, min(15, int(round(b_base * eff))))
                        # Keep dim-but-visible minimum on any active channel
                        if r_base > 0 and r_s == 0 and eff > 0.02: r_s = 1
                        if g_base > 0 and g_s == 0 and eff > 0.02: g_s = 1
                        if b_base > 0 and b_s == 0 and eff > 0.02: b_s = 1

                        # Send scaled color to all 8 zones every frame (smooth dim/bright)
                        for z in range(8):
                            send_feature_report(hid_fd, bytes([0x07, 0x14,
                                                                (z << 5) | (r_s & 0x0f),
                                                                ((g_s & 0x0f) << 4) | (b_s & 0x0f),
                                                                0, 0, 0, 0]))

                        # Hint firmware sound level (0=loud, 7=quiet) — keeps Mode 3 active
                        lvl_idx = min(9, int(smooth_norm * 9.99))
                        lvl_code = LEVEL_CODES[lvl_idx]
                        pkt_sound = bytes([0x07, 0x13, 0x80, 0xa1, 0x1b, lvl_code, 0x03, 0xff])
                        send_feature_report(hid_fd, pkt_sound)

                # Terminal VU Meter display (~16 FPS)
                if sys.stdout.isatty() and (now - last_ui_time > 0.06):
                    last_ui_time = now
                    if no_sound_ticks > 35:
                        sys.stdout.write("\r\033[2K[░░░░░░░░░░░░░░░░░░░░░░░░░░░░]   --  Waiting for sound to play...      ")
                    else:
                        meter = render_meter(rms, norm, is_beat)
                        sys.stdout.write(f"\r\033[2K{meter} ")
                    sys.stdout.flush()

        except KeyboardInterrupt:
            break
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except Exception:
                proc.kill()

    # Clean shutdown: restore standard mouse lighting
    print("\n\n[*] Restoring standard mouse ambient lighting...", flush=True)
    send_feature_report(hid_fd, PKT_RESTORE_NEON)
    time.sleep(0.01)
    commit_config(hid_fd)
    os.close(hid_fd)
    print("\033[1;32m[*] Exited cleanly.\033[0m")

if __name__ == "__main__":
    main()
