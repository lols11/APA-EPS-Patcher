# APA-EPS-Patcher

[![License: MIT](https://img.shields.io/static/v1?label=License&message=MIT&color=green)](LICENSE)

> [!CAUTION]
> This software is intended for **OFF-ROAD USE ONLY**.
> Tested only on EPS software **`5N1909144S_1501`**.
>
> The software is provided as is, without warranty. The author accepts no responsibility for its use or any consequences.

Edits the HCA lower speed threshold and time limit in standalone VW APA EPS parameter `.sgo` files.

**Factory defaults in the checked calibrations:** 50 km/h lower threshold and a 360 s (6 min) time limit.

**Maximum time limit:** 655.35 s (10 min 55.35 s). Enter `655` to select it.

**Timer reset after timeout:** This procedure applies only after HCA reaches the configured maximum time limit. Return HCA to ready status (`0x03`) for at least 1 s (100 cycles at 10 ms), then start a new active request. This transition reloads the configured HCA time limit. A zero torque value while the request remains active (status `0x05` or `0x07`) does not reset the timer. The reset delay is fixed in firmware. A firmware patch to change it is planned.

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
