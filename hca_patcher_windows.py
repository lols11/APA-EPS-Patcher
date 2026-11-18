#!/usr/bin/env python3
"""APA HCA patcher for Windows, with GUI and text modes."""

import argparse
from importlib import import_module
import math
from pathlib import Path
import struct
import sys
import time

APP_NAME = "APA HCA patcher"
sgo = import_module(APP_NAME)


STARTUP_SECONDS = 5
STARTUP_NOTICE = (
    'This software is provided "AS IS" without warranty of any kind. '
    'I accept no responsibility for its use or for any consequences.\n\n'
    'Vehicles with edited parameters should not be driven on public roads.'
)


class Package:
    def __init__(self, path, *, experimental):
        self.path = path.expanduser()
        self.experimental = experimental
        self.original = self.path.read_bytes()
        payload = sgo.inspect_sgo(self.original).payload
        self.timer = struct.unpack_from("<H", payload, sgo.TIME_OFFSET)[0]
        self.torque = struct.unpack_from("<H", payload, sgo.TORQUE_OFFSET)[0]
        self.maximum, self.speed = struct.unpack_from("<HH", payload, sgo.SPEED_OFFSET - 2)

    def parse_speed(self, value):
        return sgo.parse_speed(value, self.maximum)

    def output_path(self, speed, timer, torque):
        speed_kph = speed // 100
        time_seconds = timer // 100
        suffix = "" if torque is None else f"_q{torque}"
        return self.path.with_name(f"{self.path.stem}_HCA_{speed_kph}kph_T{time_seconds}s{suffix}.sgo")

    def save(self, destination, speed, timer, torque):
        sgo.require(torque is None or self.experimental,
                    "Torque editing requires -experimental.")
        result = sgo.edit_sgo(self.original, speed, timer, torque)
        sgo.write_output(self.path, destination, self.original, result)
        return result

    def torque_summary(self, torque=None):
        return sgo.format_torque(self.torque if torque is None else torque)


def run_cli(args):
    try:
        print(f"Disclaimer\n\n{STARTUP_NOTICE}\n", file=sys.stderr, flush=True)
        time.sleep(STARTUP_SECONDS)
        name = args.sgo or input("SGO file: ").strip()
        sgo.require(bool(name), "No SGO file specified.")
        if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
            name = name[1:-1]
        package = Package(Path(name), experimental=args.experimental)
        print(f"Valid package. Threshold: {package.speed / 100:.2f} km/h; "
              f"time: {sgo.format_time(package.timer)}.")
        if package.experimental:
            print(f"Torque request limit (nominal): {package.torque_summary()}.")
        print("Press Enter to keep the current value.")
        speed = sgo.prompt_value(
            f"HCA lower speed threshold [km/h, 0..{package.maximum / 100:.2f}]: ",
            package.parse_speed, package.speed)
        timer = sgo.prompt_value("HCA time limit [whole seconds, 0..655]: ",
                                 sgo.parse_time, package.timer)
        torque = None
        if package.experimental:
            torque = sgo.prompt_value("HCA torque request limit [Nm, 0..15.99951171875]: ",
                                      sgo.parse_torque, None)
        destination = args.output or package.output_path(speed, timer, torque)
        result = package.save(destination, speed, timer, torque)
        checked = sgo.inspect_sgo(result)
        crc = struct.unpack_from("<H", checked.payload, sgo.CRC_OFFSET)[0]
        checksum = int.from_bytes(result[checked.header + 19:checked.header + 21], "big")
        print(f"Saved: {destination.resolve()}")
        print(f"HCA: {speed / 100:.2f} km/h; time: {sgo.format_time(timer)}; "
              f"CRC: 0x{crc:04X}; record checksum: 0x{checksum:04X}.")
        if package.experimental:
            print(f"Torque request limit (nominal): {package.torque_summary(torque)}.")
        print("Readback verification: OK. Original unchanged.")
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no output file was created.", file=sys.stderr)
    return 1


def run_gui(args):
    import tkinter as tk
    import webbrowser
    from tkinter import filedialog, font, messagebox, ttk

    root = tk.Tk()
    root.title(APP_NAME)
    root.minsize(620, 0)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    content = ttk.Frame(root, padding=16)
    content.columnconfigure(0, weight=1)
    content.rowconfigure(4, weight=1)
    browser = ttk.Frame(content)
    browser.grid(row=0, column=0, sticky="ew")
    browser.columnconfigure(0, weight=1)
    source = tk.StringVar(value="Select an SGO parameter package")
    ttk.Entry(browser, textvariable=source, state="readonly").grid(row=0, column=0, sticky="ew")

    fields = ttk.Labelframe(content, text="HCA Parameters", padding=12)
    fields.grid(row=1, column=0, sticky="ew", pady=(12, 10))
    fields.columnconfigure(2, weight=1)
    ttk.Label(fields, text="New value").grid(row=0, column=1, sticky="w")
    ttk.Label(fields, text="Current value").grid(row=0, column=2, sticky="w")

    def add_field(row, title):
        ttk.Label(fields, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12))
        entry = ttk.Entry(fields, width=16, state="disabled")
        entry.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=4)
        current = ttk.Label(fields, text="–")
        current.grid(row=row, column=2, sticky="w")
        return entry, current

    speed, speed_current = add_field(1, "Lower speed threshold [km/h]")
    timer, timer_current = add_field(2, "Time limit [whole seconds]")
    if args.experimental:
        torque, torque_current = add_field(3, "Torque request limit [Nm]")
    ttk.Label(content, text="Leave a field blank to keep its current value. Enter 655 for 655.35 s.").grid(
        row=2, column=0, sticky="w")

    actions = ttk.Frame(content)
    actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
    actions.columnconfigure(0, weight=1)
    status = ttk.Label(actions, wraplength=445)
    status.grid(row=0, column=0, sticky="w", padx=(0, 12))
    filetypes = [("SGO packages", "*.sgo"), ("All files", "*.*")]
    package = None

    def open_package(path):
        nonlocal package
        try:
            candidate = Package(Path(path), experimental=args.experimental)
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot Open SGO", str(error), parent=root)
            return
        package = candidate
        source.set(str(package.path.resolve()))
        speed_current.configure(text=f"{package.speed / 100:.2f} km/h "
                                     f"(range 0–{package.maximum / 100:.2f})")
        timer_current.configure(text=sgo.format_time(package.timer))
        entries = [speed, timer]
        if package.experimental:
            torque_current.configure(text=package.torque_summary())
            entries.append(torque)
        for entry in entries:
            entry.state(["!disabled"])
            entry.delete(0, "end")
        save_button.state(["!disabled"])
        status.configure(text="")
        speed.focus_set()

    def browse():
        path = filedialog.askopenfilename(parent=root, title="Open SGO Parameter Package",
                                          filetypes=filetypes)
        if path:
            open_package(path)

    def save_as():
        try:
            speed_text, timer_text = speed.get().strip(), timer.get().strip()
            new_speed = package.parse_speed(speed_text) if speed_text else package.speed
            new_timer = sgo.parse_time(timer_text) if timer_text else package.timer
            torque_text = torque.get().strip() if package.experimental else ""
            new_torque = sgo.parse_torque(torque_text) if torque_text else None
            suggested = args.output or package.output_path(new_speed, new_timer, new_torque)
            path = filedialog.asksaveasfilename(
                parent=root, title="Save New SGO Package", filetypes=filetypes,
                initialdir=suggested.resolve().parent, initialfile=suggested.name,
                defaultextension=".sgo", confirmoverwrite=False)
            if not path:
                return
            destination = Path(path)
            package.save(destination, new_speed, new_timer, new_torque)
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot Save SGO", str(error), parent=root)
            return
        status.configure(text=f"Saved and verified {destination.name}")
        summary = f"{destination}\n\n{new_speed / 100:.2f} km/h · {sgo.format_time(new_timer)}"
        if package.experimental:
            summary += f"\nTorque request limit · {package.torque_summary(new_torque)}"
        messagebox.showinfo("SGO Saved and Verified", summary, parent=root)

    open_button = ttk.Button(browser, text="Open SGO…", command=browse)
    open_button.grid(row=0, column=1, padx=(8, 0))
    save_button = ttk.Button(actions, text="Save As…", command=save_as, state="disabled")
    save_button.grid(row=0, column=1, sticky="e")

    footer = ttk.Frame(content)
    footer.grid(row=4, column=0, sticky="sw", pady=(16, 0))
    default_font = font.nametofont("TkDefaultFont")
    free_font = default_font.copy()
    size = int(default_font.cget("size"))
    free_font.configure(size=size + (4 if size > 0 else -4), weight="bold")
    ttk.Label(footer, text="FREE FOR ALL.", foreground="#b00020", font=free_font).grid(
        row=0, column=0, sticky="w")
    ttk.Label(footer, text="BY LOLS11   v1.0").grid(row=0, column=1, sticky="w", padx=(4, 0))
    link_font = default_font.copy()
    link_font.configure(underline=True)
    support_link = ttk.Label(footer, text="If you want to support me or check out my work",
                             foreground="#005a9c", font=link_font, cursor="hand2", takefocus=True)
    support_link.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def open_support(_event):
        webbrowser.open("https://linktr.ee/lols11")

    for event in ("<Button-1>", "<Return>", "<space>"):
        support_link.bind(event, open_support)

    warning = ttk.Frame(root, padding=24)
    warning.grid(row=0, column=0, sticky="nsew")
    ttk.Label(warning, text="Disclaimer", font="TkHeadingFont").grid(sticky="w")
    ttk.Label(warning, text=STARTUP_NOTICE, wraplength=565, justify="left").grid(
        sticky="w", pady=(12, 0))

    def show_editor():
        warning.destroy()
        content.grid(row=0, column=0, sticky="nsew")
        open_button.focus_set()
        if args.sgo:
            open_package(args.sgo)

    buttons = ttk.Frame(warning)
    buttons.grid(row=2, column=0, sticky="e", pady=(16, 0))
    accept = ttk.Button(buttons, text=f"OK ({STARTUP_SECONDS} s)", width=11,
                        command=show_editor, state="disabled")
    accept.grid(row=0, column=0, padx=(0, 8))
    cancel = ttk.Button(buttons, text="Cancel", command=root.destroy)
    cancel.grid(row=0, column=1)
    cancel.focus_set()

    def update_countdown(deadline):
        remaining = deadline - time.monotonic()
        seconds = math.ceil(remaining)
        if seconds <= 0:
            accept.configure(text="OK")
            accept.state(["!disabled"])
            return
        accept.configure(text=f"OK ({seconds} s)")
        delay = math.ceil((remaining - seconds + 1) * 1000)
        root.after(delay, update_countdown, deadline)

    def start_warning_timer(_event):
        warning.unbind("<Map>")
        update_countdown(time.monotonic() + STARTUP_SECONDS)

    warning.bind("<Map>", start_warning_timer)
    root.mainloop()
    return 0


def ensure_text_console():
    if sys.platform != "win32" or all(
        stream is not None for stream in (sys.stdin, sys.stdout, sys.stderr)
    ):
        return False

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # The GUI executable has no console unless the user requests text mode.
    opened_console = not kernel32.GetConsoleCP()
    if opened_console:
        if not kernel32.AllocConsole():
            raise ctypes.WinError(ctypes.get_last_error())
        kernel32.SetConsoleTitleW(ctypes.c_wchar_p(f"{APP_NAME} - Text Mode"))
    for name, device, mode in (("stdin", "CONIN$", "r"),
                               ("stdout", "CONOUT$", "w"),
                               ("stderr", "CONOUT$", "w")):
        if getattr(sys, name) is None:
            setattr(sys, name, open(device, mode, encoding="utf-8", buffering=1))
    return opened_console


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("sgo", nargs="?", help="Path to a standalone SGO parameter package.")
    parser.add_argument("-o", "--output", type=lambda name: Path(name).expanduser(),
                        help="New output file in text mode, suggested path in GUI mode.")
    parser.add_argument("-nogui", action="store_true", help="Run only in text mode.")
    parser.add_argument("-experimental", action="store_true", help="Enable torque limit editing.")
    argv = sys.argv[1:]
    # argparse still abbreviates single-dash options with allow_abbrev=False.
    options = argv[:argv.index("--")] if "--" in argv else argv
    text_requested = any(flag in options for flag in ("-nogui", "-h", "--help"))
    opened_console = text_requested and ensure_text_console()
    try:
        args = parser.parse_args(argv)
        for flag in ("nogui", "experimental"):
            if getattr(args, flag) and f"-{flag}" not in options:
                parser.error(f"Pass -{flag} in full.")
        if args.nogui:
            return run_cli(args)
        return run_gui(args)
    finally:
        if opened_console and sys.stdin.isatty() and sys.stdout.isatty():
            try:
                input("Press Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
