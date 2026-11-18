# APA-EPS-Patcher

[![License: MIT](https://img.shields.io/static/v1?label=License&message=MIT&color=green)](LICENSE)

> [!CAUTION]
> This software is intended for **OFF-ROAD USE ONLY**.
>
> The software is provided as is, without warranty. The author accepts no responsibility for its use or any consequences.

Edits the HCA lower speed threshold and time limit in standalone VW APA EPS parameter `.sgo` files.

**Factory defaults in the checked calibrations:** 50 km/h lower threshold and a 360 s (6 min) time limit.

**Maximum time limit:** 655.35 s (10 min 55.35 s). Enter `655` to select it.

**Timer reset on 5N1909144S/1501:** After the HCA torque request goes inactive, wait at least 1 s before sending a new request. The next request reloads the timer. A firmware patch to change this delay is planned.

- **Python CLI** ([`APA.HCA.patcher.py`](https://github.com/lols11/APA-EPS-Patcher/releases/latest/download/APA.HCA.patcher.py)): run `python3 APA.HCA.patcher.py parameters.sgo` with Python 3.8 or newer. Press Enter to keep the current value. The source file is [`APA HCA patcher.py`](APA%20HCA%20patcher.py).
- **Windows x64** ([`APA.HCA.patcher.exe`](https://github.com/lols11/APA-EPS-Patcher/releases/latest/download/APA.HCA.patcher.exe)): open the `.sgo` in the GUI, edit the values, and select **Save As…**. Use `-nogui` for text mode.

Both versions save a new `.sgo`, recalculate the parameter CRC and record checksum, and leave the input file intact.

## HCA parameter addresses

Both fields are stored as little-endian 16-bit values in the decoded SGO parameter block.

| Parameter | SGO block offset |
| --- | --- |
| HCA lower speed threshold | `+0x032C` |
| HCA time threshold | `+0x0320` |

## License

Released under the [MIT License](LICENSE).

[Support my work and explore my other projects](https://linktr.ee/lols11).

## Acknowledgments

Huge thanks to Willem Melching for his excellent articles on hacking the ZF Gen 3 EPS. [Read part 1](https://icanhack.nl/blog/vw-part1/).
