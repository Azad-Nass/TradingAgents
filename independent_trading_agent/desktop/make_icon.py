"""Draws the app icon (Persian-blue tile, rising chart line) into icon.ico.

Pure numpy + zlib: each size is rendered with 4x4 supersampling, encoded as
PNG, and the PNGs are packed into one .ico (Windows Vista and later).

    python independent_trading_agent/desktop/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

BG = (0x1C, 0x39, 0xBB)
FG = (0xFF, 0xFF, 0xFF)
LINE = [(5.0, 22.5), (11.5, 15.0), (16.5, 18.5), (23.0, 9.5), (27.5, 13.0)]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _segment_distance(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy), 0, 1)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size: int, ss: int = 4) -> np.ndarray:
    n = size * ss
    coords = (np.arange(n) + 0.5) / n * 32.0
    px, py = np.meshgrid(coords, coords)
    radius = 7.0
    qx = np.clip(px, radius, 32 - radius)
    qy = np.clip(py, radius, 32 - radius)
    tile = np.hypot(px - qx, py - qy) <= radius
    width = 2.8 if size >= 32 else 3.4  # thicker strokes keep small sizes legible
    line = np.zeros_like(tile)
    for a, b in zip(LINE, LINE[1:], strict=False):
        line |= _segment_distance(px, py, a, b) <= width / 2
    dot = np.hypot(px - LINE[3][0], py - LINE[3][1]) <= (3.0 if size >= 32 else 3.4)
    fg = (line | dot) & tile
    rgba = np.zeros((n, n, 4), dtype=float)
    rgba[tile] = (*BG, 255)
    rgba[fg] = (*FG, 255)
    small = rgba.reshape(size, ss, size, ss, 4).mean(axis=(1, 3))
    alpha = small[..., 3:4]
    color = np.where(alpha > 0, small[..., :3] * 255 / np.maximum(alpha, 1e-9), 0)  # un-premultiply
    return np.concatenate([color, alpha], axis=-1).round().clip(0, 255).astype(np.uint8)


def png_bytes(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico_bytes(images: list[np.ndarray]) -> bytes:
    pngs = [png_bytes(i) for i in images]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for img, data in zip(images, pngs, strict=True):
        s = img.shape[0]
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return header + entries + blobs


def main() -> Path:
    out = Path(__file__).resolve().parent / "icon.ico"
    out.write_bytes(ico_bytes([render(s) for s in SIZES]))
    (out.parent / "icon-256.png").write_bytes(png_bytes(render(256)))
    return out


if __name__ == "__main__":
    print(main())
