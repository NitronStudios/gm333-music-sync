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

# GM333 Native Protocol Packets (Report ID 0x07, 8 bytes)
# Mode 3 = Direct Static Color control (zero autonomous firmware animation)
_B3_MODE3 = ((1 << 7) + (3 << 4) + 2) & 0xff
_B6_MODE3 = (((3 >> 3) << 7) + ((0x4002 >> 8) & 3)) & 0xff
PKT_INIT_DIRECT_SYNC = bytes([0x07, 0x13, 0x80, _B3_MODE3, 0x1b, 0, _B6_MODE3, 0x4002 & 0xff])
# Mode 14 = Hardware LED Off (Completely off in silence)
_B3_MODE14 = ((1 << 7) + (14 << 4) + 2) & 0xff
_B6_MODE14 = (((14 >> 3) << 7) + ((0x4002 >> 8) & 3)) & 0xff
PKT_MODE_OFF = bytes([0x07, 0x13, 0x80, _B3_MODE14, 0x1b, 0, _B6_MODE14, 0x4002 & 0xff])
# Mode 7 = Neon (Default factory ambient effect)
PKT_RESTORE_NEON   = bytes([0x07, 0x13, 0x80, 0xf2, 0x1b, 0x00, 0x00, 0x02])

# Volume-to-code mapping: quiet/silence = 7, loudest peak = 0
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

def get_current_monitor_target():
    """Detect current active default audio sink monitor in PipeWire/PulseAudio."""
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"], stderr=subprocess.DEVNULL).decode().strip()
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

    hid_fd = get_hid_fd()
    if hid_fd is None:
        print("\033[1;31m[!] Could not open Ant Esports GM333 mouse.\033[0m", file=sys.stderr)
        print("    Ensure permissions: /dev/input/by-id/usb-INSTANT_USB_GAMING_MOUSE-if01-hidraw", file=sys.stderr)
        sys.exit(1)

    print("\033[1;32m[+] Mouse hardware linked:\033[0m GM333 Controller (30fa:1440 Interface 1)")
    print(f"\033[1;32m[+] Palette:\033[0m {args.palette} | \033[1;32mSensitivity:\033[0m {args.sensitivity}x | \033[1;32mFPS:\033[0m {args.fps}")

    # Start in Mode 14 (Completely Off)
    is_hardware_off = True
    send_feature_report(hid_fd, PKT_MODE_OFF)
    time.sleep(0.04)

    palette_colors = PALETTES[args.palette]
    color_idx = 0
    min_interval = 1.0 / max(10, min(args.fps, 40))

    # Adaptive Audio Tracking variables
    noise_floor = 150.0
    peak_ceiling = 2500.0
    last_send_time = 0
    last_beat_time = 0
    last_ui_time = 0
    prev_rms = 0.0

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
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            # Fallback to standard parec without latency param if older version
            cmd = ["parec", "-d", monitor, "--format=s16le", "--channels=1", "--rate=22050"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        chunk_samples = 512
        chunk_bytes = chunk_samples * 2
        no_sound_ticks = 0

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

                # Advanced Beat Detection & Energy tracking with strict silence gate
                delta = rms - prev_rms
                energy_fast = (locals().get('energy_fast', 0.0) * 0.55) + (rms * 0.45)
                energy_slow = (locals().get('energy_slow', 0.0) * 0.95) + (rms * 0.05)

                beat_thresh = 1.25 / args.sensitivity
                delta_thresh = 200.0 / args.sensitivity
                is_beat = False
                # NEVER trigger beat if in silence or below threshold
                if rms > 140.0 and norm > 0.30:
                    if (now - last_beat_time) > 0.18:
                        if (energy_fast > (energy_slow * beat_thresh) and delta > delta_thresh) or (norm > 0.82 and delta > 240.0):
                            is_beat = True
                            last_beat_time = now
                            color_idx = (color_idx + 1) % len(palette_colors)
                            smooth_norm = max(locals().get('smooth_norm', 0.0), min(1.0, norm + 0.30))

                prev_rms = rms

                # Smooth loudness tracking for Brightness (fast attack, smooth musical decay)
                cur_smooth = locals().get('smooth_norm', 0.0)
                if norm <= 0.01:
                    smooth_norm = cur_smooth * 0.75
                    if smooth_norm < 0.01:
                        smooth_norm = 0.0
                elif norm > cur_smooth:
                    smooth_norm = (cur_smooth * 0.20) + (norm * 0.80)
                else:
                    smooth_norm = (cur_smooth * 0.85) + (norm * 0.15)

                # Perceptual human brightness curve
                is_silent = (smooth_norm <= 0.005)

                if not is_silent:
                    perceptual = smooth_norm ** 0.85
                    brightness = max(0.0, min(1.0, perceptual))
                    r_base, g_base, b_base = palette_colors[color_idx % len(palette_colors)]
                    r_out = max(1 if r_base > 0 else 0, min(15, int(round(r_base * brightness))))
                    g_out = max(1 if g_base > 0 else 0, min(15, int(round(g_base * brightness))))
                    b_out = max(1 if b_base > 0 else 0, min(15, int(round(b_base * brightness))))

                # Throttled LED updates to maintain smooth frame rate
                if (now - last_send_time) >= min_interval:
                    last_send_time = now

                    if is_silent:
                        if not is_hardware_off:
                            send_feature_report(hid_fd, PKT_MODE_OFF)
                            is_hardware_off = True
                    else:
                        if is_hardware_off:
                            send_feature_report(hid_fd, PKT_INIT_DIRECT_SYNC)
                            is_hardware_off = False
                            time.sleep(0.01)

                        # Direct RGB color & brightness to all 8 mouse LED zones (no white fallback)
                        for zone in range(8):
                            pkt_rgb = bytes([0x07, 0x14, (zone << 5) | (r_out & 0x0f), ((g_out & 0x0f) << 4) | (b_out & 0x0f), 0x00, 0x00, 0x00, 0x00])
                            send_feature_report(hid_fd, pkt_rgb)

                # Terminal VU Meter display update (~16 FPS, only if running in a terminal)
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
    os.close(hid_fd)
    print("\033[1;32m[*] Exited cleanly.\033[0m")

if __name__ == "__main__":
    main()
