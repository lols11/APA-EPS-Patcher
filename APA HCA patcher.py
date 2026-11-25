#!/usr/bin/env python3
# SPDX-License-Identifier: MIT AND Beerware
"""Interactive HCA patcher for parameter SGO files with a 0x906326 block.

Python 3 standard library only. Keeps the source and all unrelated bytes intact.
Changes decoded parameter words +0x0320 (time, 10 ms task cycles), +0x0322
(torque request limit, nominally 1/2048 Nm) and +0x032C (speed, 0.01 km/h).
Prompts for whole seconds and km/h. The -experimental flag enables the Nm prompt.
Entering 655 selects 655.35 s.
Repairs the parameter CRC and
SGO record checksum, then reopens the output.
Validates container sizes, record checksums and the 0x04DA-byte parameter block
with its CRC. Calibration and RAM-driver fingerprints are not required. Full
firmware packages are rejected. Fixed parameter offsets are used; checksum
validation does not establish field semantics for a different firmware family.
"""
import argparse
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import os
from pathlib import Path
import re
import struct
import sys


COPYRIGHT_NOTICE = "Copyright (c) 2026 lols11 | MIT and Beerware"
LICENSE_TEXT = """APA HCA patcher is licensed under MIT and Beerware. Both sets of terms apply.

MIT License

Copyright (c) 2026 lols11

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

"THE BEER-WARE LICENSE" (Revision 42)

lols11 wrote this software. As long as you retain this notice, you can
do whatever you want with this software. If we meet some day and you
think this software is worth it, you can buy me a beer in return.

lols11
"""


PARAMETER_ADDRESS = 0x906326
TIME_OFFSET = 0x0320
TORQUE_OFFSET = 0x0322
TORQUE_SCALE = 2048
TORQUE_MAX = 0x7FFF
SPEED_OFFSET = 0x032C
CRC_OFFSET = 0x049C
PARAMETER_SIZE = 0x04DA


@dataclass(frozen=True)
class Record:
    address: int
    header: int
    start: int
    payload: bytes


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parameter_crc(payload):
    require(len(payload) % 2 == 0, "CRC requires an even number of bytes.")
    state = 0xFFFF
    for (word,) in struct.iter_unpack("<H", payload):
        for _ in range(16):
            feedback = (state ^ word) & 0x8000
            state = (state << 1) & 0xFFFF
            if feedback:
                state ^= 0x8005
            word = (word << 1) & 0xFFFF
    return state ^ 0xFFFF


def inspect_sgo(data):
    """Validate the whole container before identifying the editable record."""
    require(len(data) >= 0x31 and data[:17] == b"SGML Object File\0",
            "This is not a supported SGO file.")
    u32 = lambda offset: struct.unpack_from("<I", data, offset)[0]
    u24 = lambda offset: int.from_bytes(data[offset:offset+3], "big")
    metadata, footer = u32(0x29), u32(0x2D)
    require(0x31 <= metadata <= footer-4 and footer <= len(data)-4,
            "Invalid SGO metadata or footer boundaries.")
    count = u32(footer)
    require(count > 0 and footer+4+4*count == len(data),
            "Invalid SGO record index length.")
    position = metadata+4+u32(metadata)
    require(position <= footer, "Metadata extends beyond the record area.")
    records = []
    addresses = set()
    for index in range(count):
        header = u32(footer+4+4*index)
        require(header == position and header+25 <= footer,
                "SGO index does not match record boundaries.")
        address, length, stored_length = u24(header), u24(header+4), u32(header+21)
        require(data[header+3] == 0 and length == stored_length,
                "Compression or additional encryption is not supported for this SGO.")
        start = header+25
        position = start+stored_length
        require(length > 0 and position <= footer and address+length <= 0x1000000,
                "Invalid SGO record size.")
        require(address not in addresses, "Duplicate SGO record address.")
        addresses.add(address)
        require((u24(header+7), u24(header+10), u24(header+13), u24(header+16)) ==
                (address, address+length-1, address, address+length-1),
                "Unsupported erase or programming ranges.")
        payload = bytes(value ^ 0xFF for value in data[start:position])
        checksum = int.from_bytes(data[header+19:header+21], "big")
        require(sum(payload) & 0xFFFF == checksum,
                f"Invalid record checksum at 0x{address:06X}.")
        records.append(Record(address, header, start, payload))
    require(position == footer, "Extra data between records and the SGO footer.")
    ordered = sorted(records, key=lambda record: record.address)
    require(all(first.address+len(first.payload) <= second.address
                for first, second in zip(ordered, ordered[1:])),
            "SGO record ranges overlap.")
    require(not any(record.address in (0x004000, 0x804200, 0x60C000) for record in records),
            "This is a full firmware package. Provide a standalone parameter SGO.")
    targets = [record for record in records if record.address == PARAMETER_ADDRESS]
    require(len(targets) == 1, "No unique parameter block at 0x906326.")
    target = targets[0]
    payload = target.payload
    require(len(payload) == PARAMETER_SIZE,
            f"Unsupported parameter block size: 0x{len(payload):04X}; expected 0x{PARAMETER_SIZE:04X}.")
    require(parameter_crc(payload[:CRC_OFFSET]) == struct.unpack_from("<H", payload, CRC_OFFSET)[0],
            "Invalid parameter CRC; the file has not been changed.")
    lower, upper = struct.unpack_from("<H", payload, SPEED_OFFSET)[0], struct.unpack_from("<H", payload, SPEED_OFFSET-2)[0]
    require(lower <= upper <= 0x7FFF, "Invalid HCA speed threshold range.")
    return target


def parse_speed(text, maximum):
    require(re.fullmatch(r"[0-9]{1,3}(?:[.,][0-9]{1,2})?", text) is not None,
            "Enter km/h with up to two decimal places, e.g. 30 or 30.50.")
    raw = int(Decimal(text.replace(",", "."))*100)
    require(0 <= raw <= maximum, f"The threshold must be between 0 and {maximum/100:.2f} km/h.")
    return raw


def parse_time(text):
    require(re.fullmatch(r"[0-9]{1,3}", text) is not None,
            "Enter whole seconds from 0 to 655.")
    seconds = int(text)
    require(0 <= seconds <= 655, "The time limit must be between 0 and 655 seconds.")
    return 65535 if seconds == 655 else seconds * 100


def format_time(cycles):
    minutes, remainder = divmod(cycles, 6000)
    total_seconds = f"{cycles/100:.2f}".rstrip("0").rstrip(".")
    seconds = f"{remainder/100:.2f}".rstrip("0").rstrip(".")
    return f"{total_seconds} s = {minutes} min {seconds} s"


def parse_torque(text):
    require(re.fullmatch(r"[0-9]{1,2}(?:[.,][0-9]{1,12})?", text) is not None,
            "Enter Nm with up to twelve decimal places, e.g. 3 or 4.50.")
    value = Decimal(text.replace(",", "."))
    maximum = Decimal(TORQUE_MAX) / TORQUE_SCALE
    require(0 <= value <= maximum,
            f"The torque request limit must be between 0 and {maximum} Nm.")
    return int((value * TORQUE_SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def format_torque(raw):
    # Firmware interprets the word as signed and clamps negative limits to zero.
    effective = raw if raw <= TORQUE_MAX else 0
    return f"{Decimal(effective) / TORQUE_SCALE} Nm ({raw} raw, 0x{raw:04X})"


def prompt_value(prompt, parser, current):
    while True:
        value = input(prompt).strip()
        if not value:
            return current
        try:
            return parser(value)
        except ValueError as error:
            print(f"Error: {error}")


def edit_sgo(original, speed, timer, torque=None):
    target = inspect_sgo(original)
    maximum = struct.unpack_from("<H", target.payload, SPEED_OFFSET-2)[0]
    require(isinstance(speed, int) and 0 <= speed <= maximum, "Invalid raw speed.")
    require(isinstance(timer, int) and 0 <= timer <= 65535, "Invalid raw time limit.")
    require(torque is None or isinstance(torque, int) and 0 <= torque <= TORQUE_MAX,
            "Invalid raw torque request limit.")
    payload = bytearray(target.payload)
    struct.pack_into("<H", payload, SPEED_OFFSET, speed)
    struct.pack_into("<H", payload, TIME_OFFSET, timer)
    if torque is not None:
        struct.pack_into("<H", payload, TORQUE_OFFSET, torque)
    struct.pack_into("<H", payload, CRC_OFFSET, parameter_crc(payload[:CRC_OFFSET]))
    output = bytearray(original)
    output[target.start:target.start+len(payload)] = bytes(value ^ 0xFF for value in payload)
    output[target.header+19:target.header+21] = (sum(payload) & 0xFFFF).to_bytes(2, "big")
    result = bytes(output)
    checked = inspect_sgo(result)
    require(struct.unpack_from("<H", checked.payload, SPEED_OFFSET)[0] == speed and
            struct.unpack_from("<H", checked.payload, TIME_OFFSET)[0] == timer,
            "Edited value verification failed.")
    expected_torque = (struct.unpack_from("<H", target.payload, TORQUE_OFFSET)[0]
                       if torque is None else torque)
    require(struct.unpack_from("<H", checked.payload, TORQUE_OFFSET)[0] == expected_torque,
            "Edited torque request limit verification failed.")
    allowed = set(range(target.header+19, target.header+21))
    for offset in (TIME_OFFSET, SPEED_OFFSET, CRC_OFFSET):
        allowed.update(range(target.start+offset, target.start+offset+2))
    if torque is not None:
        allowed.update(range(target.start+TORQUE_OFFSET, target.start+TORQUE_OFFSET+2))
    require(len(result) == len(original) and
            all(a == b or index in allowed for index, (a, b) in enumerate(zip(original, result))),
            "Unexpected byte changes outside HCA fields and their checksums.")
    return result


def write_output(source, destination, original, result, *, numbered=False):
    if not numbered:
        require(source.resolve() != destination.resolve(), "Output must have a different name from the original.")
    require(source.read_bytes() == original, "Source file changed during editing.")
    # Exclusive creation prevents overwriting originals, existing variants and
    # symlinks. A failed write/readback removes only the file created here.
    candidate = destination
    number = 2
    created = False
    try:
        while True:
            try:
                stream = candidate.open("xb")
            except FileExistsError:
                if not numbered:
                    raise
                candidate = destination.with_name(f"{destination.stem}_{number}{destination.suffix}")
                number += 1
            else:
                created = True
                break
        with stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        readback = candidate.read_bytes()
        require(readback == result, "Saved file readback differs from the expected output.")
        inspect_sgo(readback)
        require(source.read_bytes() == original, "Original file changed during writing.")
    except BaseException:
        if created:
            candidate.unlink()
        raise
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sgo", nargs="?", help="Path to a standalone SGO parameter package.")
    parser.add_argument("-o", "--output", type=Path, help="New output file; existing files are never overwritten.")
    parser.add_argument("-experimental", action="store_true", help="Enable torque limit editing.")
    parser.add_argument("--license", action="store_true", help="Print the MIT and Beerware license texts.")
    argv = sys.argv[1:]
    args = parser.parse_args(argv)
    # argparse still abbreviates single-dash options with allow_abbrev=False.
    options = argv[:argv.index("--")] if "--" in argv else argv
    if args.experimental and "-experimental" not in options:
        parser.error("Pass -experimental in full.")
    if args.license:
        print(LICENSE_TEXT, end="")
        return 0
    try:
        print(COPYRIGHT_NOTICE, file=sys.stderr, flush=True)
        name = args.sgo or input("SGO file: ").strip()
        require(bool(name), "No SGO file specified.")
        if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
            name = name[1:-1]
        source = Path(name).expanduser()
        original = source.read_bytes()
        target = inspect_sgo(original)
        current_speed = struct.unpack_from("<H", target.payload, SPEED_OFFSET)[0]
        current_time = struct.unpack_from("<H", target.payload, TIME_OFFSET)[0]
        maximum = struct.unpack_from("<H", target.payload, SPEED_OFFSET-2)[0]
        print(f"Valid package. Threshold: {current_speed/100:.2f} km/h; time: {format_time(current_time)}.")
        if args.experimental:
            current_torque = struct.unpack_from("<H", target.payload, TORQUE_OFFSET)[0]
            print(f"Torque request limit (nominal): {format_torque(current_torque)}.")
        print("Press Enter to keep the current value. Enter time in whole seconds.")
        speed = prompt_value(f"HCA lower speed threshold [km/h, 0..{maximum/100:.2f}]: ",
                             lambda value: parse_speed(value, maximum), current_speed)
        timer = prompt_value("HCA time limit [whole seconds, 0..655]: ", parse_time, current_time)
        torque = None
        if args.experimental:
            torque = prompt_value("HCA torque request limit [Nm, 0..15.99951171875]: ",
                                  parse_torque, None)
        result = edit_sgo(original, speed, timer, torque)
        torque_suffix = "" if torque is None else f"_q{torque}"
        destination = args.output or source.with_name(
            f"{source.stem}_HCA_{speed // 100}kph_T{timer // 100}s{torque_suffix}.sgo")
        destination = write_output(source, destination.expanduser(), original, result,
                                   numbered=args.output is None)
        checked = inspect_sgo(result)
        crc = struct.unpack_from("<H", checked.payload, CRC_OFFSET)[0]
        checksum = int.from_bytes(result[checked.header+19:checked.header+21], "big")
        print(f"Saved: {destination.resolve()}")
        print(f"HCA: {speed/100:.2f} km/h; time: {format_time(timer)}; CRC: 0x{crc:04X}; record checksum: 0x{checksum:04X}.")
        if args.experimental:
            saved_torque = struct.unpack_from("<H", checked.payload, TORQUE_OFFSET)[0]
            print(f"Torque request limit (nominal): {format_torque(saved_torque)}.")
        print("Readback verification: OK. Original unchanged.")
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no output file was created.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
