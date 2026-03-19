#!/usr/bin/env python3

import os
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "src-tauri" / "icons"


def pack_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, size: int) -> bytes:
    radius = size * 0.42
    ring_radius = size * 0.18
    center = (size - 1) / 2.0
    scale = 4
    pixels = bytearray()

    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            r_total = g_total = b_total = a_total = 0
            for sy in range(scale):
                for sx in range(scale):
                    px = x + (sx + 0.5) / scale
                    py = y + (sy + 0.5) / scale
                    dx = px - center
                    dy = py - center
                    dist = (dx * dx + dy * dy) ** 0.5

                    if dist <= radius:
                        if dist <= ring_radius:
                            r, g, b, a = 240, 247, 255, 255
                        else:
                            r, g, b, a = 34, 40, 49, 255
                    elif dist <= radius + 1.0:
                        alpha = max(0.0, radius + 1.0 - dist)
                        r, g, b, a = 34, 40, 49, int(255 * alpha)
                    else:
                        r, g, b, a = 0, 0, 0, 0

                    r_total += r
                    g_total += g
                    b_total += b
                    a_total += a

            samples = scale * scale
            row.extend(
                (
                    r_total // samples,
                    g_total // samples,
                    b_total // samples,
                    a_total // samples,
                )
            )
        pixels.extend(row)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(pack_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)))
    png.extend(pack_chunk(b"IDAT", zlib.compress(bytes(pixels), 9)))
    png.extend(pack_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))
    return bytes(png)


def write_ico(path: Path, png_data: bytes) -> None:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        0,
        0,
        0,
        0,
        1,
        32,
        len(png_data),
        6 + 16,
    )
    path.write_bytes(header + entry + png_data)


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    png_sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 256,
        "Square30x30Logo.png": 30,
        "Square44x44Logo.png": 44,
        "Square71x71Logo.png": 71,
        "Square89x89Logo.png": 89,
        "Square107x107Logo.png": 107,
        "Square142x142Logo.png": 142,
        "Square150x150Logo.png": 150,
        "Square284x284Logo.png": 284,
        "Square310x310Logo.png": 310,
        "StoreLogo.png": 50,
    }

    icon_png = None
    for name, size in png_sizes.items():
        data = write_png(ICONS_DIR / name, size)
        if name == "icon.png":
            icon_png = data

    if icon_png is None:
        raise RuntimeError("icon.png generation failed")

    write_ico(ICONS_DIR / "icon.ico", icon_png)


if __name__ == "__main__":
    main()
