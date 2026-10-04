#!/usr/bin/env python3
"""
Ant Esports GM333 Hardware Controller CLI for Linux
Control all 16 onboard hardware lighting modes, colors, speed, brightness,
and toggle the native audio-reactive Music Sync visualizer.
"""

import sys
import os
import time
import fcntl
import argparse
import subprocess
import glob
import re

HID_DEVICE_LINK = "/dev/input/by-id/usb-INSTANT_USB_GAMING_MOUSE-if01-hidraw"
HIDIOCSFEATURE_8 = 0xc0084806

MODES = {
    "neon":          (6,  "Neon (Default vibrant multi-color rainbow wave)"),
    "breathing":     (1,  "Cycle Breathing (Smooth multi-color breathing)"),
    "static":        (2,  "Light On (Constant / solid color)"),
    "wave":          (3,  "Flowing Water (Wave stream across mouse)"),
    "mono-wave":     (4,  "Mono Water (Single-color water wave)"),
    "comet":         (5,  "Comet Streak (Comet tail trail)"),
    "ambilight":     (7,  "Ambilight (Ambient dynamic glow)"),
    "flicker":       (8,  "Flicker (Dynamic rhythmic flicker)"),
    "startrek":      (9,  "Star Trek (Moving star pulses)"),
    "ripple":        (10, "Ripple (Water drop ripple pulse)"),
    "enraptured":    (11, "Enraptured (Multi-phase wave effect)"),
    "reactive":      (12, "Button Response (Lights up when clicked)"),
    "off":           (13, "LED Off (Turn off all LEDs)"),
    "dpi-breath":    (0,  "DPI Breathing (Breathes current DPI color)"),
}

NAMED_COLORS = {
    "red":     (15, 0, 0),
    "green":   (0, 15, 0),
    "blue":    (0, 0, 15),
    "cyan":    (0, 15, 15),
    "magenta": (15, 0, 15),
    "purple":  (10, 0, 15),
    "yellow":  (15, 15, 0),
    "orange":  (15, 5, 0),
    "pink":    (15, 2, 8),
    "white":   (15, 15, 15),
}

def parse_color(c_str):
    if not c_str:
        return (0, 15, 15) # Default cyan
    c_str = c_str.lower().strip()
    if c_str in NAMED_COLORS:
        return NAMED_COLORS[c_str]
    # Hex color #RRGGBB or RRGGBB
    m = re.match(r"^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$", c_str)
    if m:
        r = int(m.group(1), 16) >> 4
        g = int(m.group(2), 16) >> 4
        b = int(m.group(3), 16) >> 4
        return (r, g, b)
    # Hex shorthand #RGB
    m = re.match(r"^#?([0-9a-f])([0-9a-f])([0-9a-f])$", c_str)
    if m:
        r = int(m.group(1), 16)
        g = int(m.group(2), 16)
        b = int(m.group(3), 16)
        return (r, g, b)
    return (0, 15, 15)

def get_hid_fd():
    if os.path.exists(HID_DEVICE_LINK):
        try:
            return os.open(HID_DEVICE_LINK, os.O_RDWR)
        except Exception as e:
            print(f"[!] Error opening {HID_DEVICE_LINK}: {e}", file=sys.stderr)

    for hpath in sorted(glob.glob("/dev/hidraw*")):
        num = os.path.basename(hpath).replace("hidraw", "")
        uevent_path = f"/sys/class/hidraw/hidraw{num}/device/uevent"
        if os.path.exists(uevent_path):
            try:
                with open(uevent_path) as f:
                    content = f.read()
                if "30FA" in content and "1440" in content and "input1" in content:
                    return os.open(hpath, os.O_RDWR)
            except Exception:
                pass
    return None

def send_mode_packet(fd, led_type, speed=2, brightness=4):
    is_single_color = led_type in [2, 4, 13]
    b0 = 0x07
    b1 = 0x13
    b2 = 0x80 if is_single_color else 0xff
    b3 = 0x80 | ((led_type & 0x07) << 4) | (speed & 0x07)
    b4 = 0x1b
    b5 = brightness & 0x07
    b6 = 0x80 if led_type >= 8 else 0x00
    b7 = 0x02
    pkt = bytes([b0, b1, b2, b3, b4, b5, b6, b7])
    fcntl.ioctl(fd, HIDIOCSFEATURE_8, pkt)

def send_color(fd, r, g, b):
    for z in range(8):
        # Hardware expects: Byte 2 = (zone << 5) | Green, Byte 3 = (Red << 4) | Blue
        pkt = bytes([0x07, 0x14, (z << 5) | (g & 0xf), ((r & 0xf) << 4) | (b & 0xf), 0, 0, 0, 0])
        fcntl.ioctl(fd, HIDIOCSFEATURE_8, pkt)

def stop_music_service_if_running():
    try:
        res = subprocess.run(["systemctl", "--user", "is-active", "gm333-music-sync.service"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if res.stdout.strip() == "active":
            print("\033[1;33m[*] Pausing background music-sync service so your selected lighting mode stays active...\033[0m")
            subprocess.run(["systemctl", "--user", "stop", "gm333-music-sync.service"], check=True)
    except Exception:
        pass

def cmd_list(args):
    print("\033[1;35m============================================================\033[0m")
    print("\033[1;37m        Ant Esports GM333 Hardware Lighting Modes           \033[0m")
    print("\033[1;35m============================================================\033[0m")
    print(f"{'Mode Name':<16} {'ID':<4} {'Description'}")
    print("-" * 60)
    for name, (mid, desc) in MODES.items():
        print(f"\033[1;36m{name:<16}\033[0m {mid:<4} {desc}")
    print("\n\033[1;33mUsage examples:\033[0m")
    print("  gm333-ctl mode neon")
    print("  gm333-ctl mode breathing --speed 3")
    print("  gm333-ctl mode static --color cyan")
    print("  gm333-ctl mode static --color '#ff00ff'")
    print("  gm333-ctl mode single-breath --color red")
    print("  gm333-ctl mode off")
    print("  gm333-ctl music\n")

def cmd_mode(args):
    target_mode = args.mode.lower()
    if target_mode not in MODES:
        # Check if integer ID given
        found = False
        try:
            val = int(target_mode)
            for k, (mid, desc) in MODES.items():
                if mid == val:
                    target_mode = k
                    found = True
                    break
        except ValueError:
            pass
        if not found:
            print(f"\033[1;31m[!] Unknown mode '{args.mode}'.\033[0m Run 'gm333-ctl list' to see available modes.")
            sys.exit(1)

    led_id, desc = MODES[target_mode]

    # If setting any mode other than music, stop background music sync so it doesn't overwrite
    if target_mode != "music":
        stop_music_service_if_running()

    fd = get_hid_fd()
    if fd is None:
        print("\033[1;31m[!] Could not open GM333 mouse device.\033[0m", file=sys.stderr)
        sys.exit(1)

    speed = max(1, min(7, args.speed))
    brightness = max(0, min(4, args.brightness))

    send_mode_packet(fd, led_id, speed=speed, brightness=brightness)

    # If static or single-breath, also send the color packet
    if target_mode in ["static", "single-breath"] or args.color is not None:
        r, g, b = parse_color(args.color)
        time.sleep(0.04)
        send_color(fd, r, g, b)
        color_info = f" | Color: ({r*17}, {g*17}, {b*17})"
    else:
        color_info = ""

    os.close(fd)
    print(f"\033[1;32m[✓] Lighting Mode set to:\033[0m \033[1;36m{target_mode.upper()}\033[0m (ID {led_id})")
    print(f"    {desc}{color_info} | Speed: {speed} | Brightness: {brightness}")

def cmd_service(args):
    action = args.action.lower()
    if action not in ["start", "stop", "restart", "status"]:
        print(f"[!] Invalid service action: {action}. Use start, stop, restart, or status.")
        sys.exit(1)
    if action == "status":
        subprocess.run(["systemctl", "--user", "status", "gm333-music-sync.service", "--no-pager"])
    else:
        subprocess.run(["systemctl", "--user", action, "gm333-music-sync.service"], check=True)
        print(f"\033[1;32m[✓] gm333-music-sync.service {action}ed successfully.\033[0m")

def cmd_music(args):
    # Delegate to gm333-music-sync
    stop_music_service_if_running()
    script = "/home/prince/Projects/gm333-music-sync/gm333-music-sync.py"
    cmd = [sys.executable, script]
    if args.palette:
        cmd += ["-p", args.palette]
    if args.sensitivity:
        cmd += ["-s", str(args.sensitivity)]
    if args.fps:
        cmd += ["--fps", str(args.fps)]
    try:
        os.execv(sys.executable, cmd)
    except Exception as e:
        print(f"[!] Error launching music sync: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Ant Esports GM333 Mouse Hardware Lighting Controller")
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # mode subcommand
    p_mode = subparsers.add_parser("mode", help="Set mouse lighting mode")
    p_mode.add_argument("mode", help="Mode name (e.g. neon, breathing, static, wave, off)")
    p_mode.add_argument("--color", "-c", default=None, help="Color name (red, blue, cyan, etc.) or #hex")
    p_mode.add_argument("--speed", type=int, default=2, help="Effect speed (1-7, default: 2)")
    p_mode.add_argument("--brightness", "-b", type=int, default=0, help="Brightness (0-4, default: 0)")
    p_mode.set_defaults(func=cmd_mode)

    # list subcommand
    p_list = subparsers.add_parser("list", help="List all 16 hardware lighting modes")
    p_list.set_defaults(func=cmd_list)

    # music subcommand
    p_music = subparsers.add_parser("music", help="Launch interactive Music Sync visualizer")
    p_music.add_argument("--palette", "-p", default="cyberpunk", help="Color palette")
    p_music.add_argument("--sensitivity", "-s", type=float, default=1.0, help="Audio sensitivity")
    p_music.add_argument("--fps", type=int, default=24, help="FPS update rate")
    p_music.set_defaults(func=cmd_music)

    # service subcommand
    p_srv = subparsers.add_parser("service", help="Manage background music-sync systemd service")
    p_srv.add_argument("action", choices=["start", "stop", "restart", "status"], help="Service action")
    p_srv.set_defaults(func=cmd_service)

    # If first argument matches a mode name directly (convenience shorthand like `gm333-ctl neon`)
    if len(sys.argv) > 1 and sys.argv[1].lower() in MODES:
        sys.argv.insert(1, "mode")
    elif len(sys.argv) == 1:
        parser.print_help()
        print("\nRun \033[1;36mgm333-ctl list\033[0m to see all 16 supported lighting modes.")
        sys.exit(0)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
