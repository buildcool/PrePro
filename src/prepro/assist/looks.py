"""Mood-based colour looks generated as .cube 3D LUTs (licence-free, made here)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import models_dir

PRESETS = ["natural", "warm", "teal_orange", "pastel", "punchy", "moody", "vintage", "bw"]


def _apply(name: str, rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    out = rgb.copy()
    if name == "warm":
        out = np.stack([r * 1.06 + 0.015, g * 1.01 + 0.005, b * 0.92], -1)
    elif name == "teal_orange":
        sh = np.clip(1 - luma * 1.6, 0, 1)[..., None]           # shadows → teal
        hi = np.clip((luma - 0.45) * 1.8, 0, 1)[..., None]      # highlights/skin → orange
        out = rgb + sh * np.array([-0.04, 0.02, 0.05]) + hi * np.array([0.06, 0.02, -0.05])
        out = (out - 0.5) * 1.06 + 0.5
    elif name == "pastel":
        out = luma[..., None] + (rgb - luma[..., None]) * 0.8
        out = out * 0.9 + 0.08
        out = out + np.array([0.01, 0.0, 0.015])
    elif name == "punchy":
        out = luma[..., None] + (rgb - luma[..., None]) * 1.25
        out = (out - 0.5) * 1.12 + 0.5
    elif name == "moody":
        out = luma[..., None] + (rgb - luma[..., None]) * 0.75
        out = (out - 0.5) * 1.1 + 0.46 + np.array([-0.01, 0.0, 0.02])
    elif name == "vintage":
        out = np.stack([r * 0.95 + 0.06, g * 0.92 + 0.05, b * 0.82 + 0.06], -1)
        out = luma[..., None] * 0.25 + out * 0.75
    elif name == "bw":
        out = np.repeat(((luma - 0.5) * 1.1 + 0.5)[..., None], 3, -1)
    return np.clip(out, 0, 1)


def lut_path(name: str, size: int = 17) -> Path | None:
    if not name or name not in PRESETS or name == "natural":
        return None
    d = models_dir() / "luts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.cube"
    if p.exists():
        return p
    grid = np.linspace(0, 1, size)
    lines = [f'TITLE "PrePro {name}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    # .cube order: red changes fastest
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")
    rgb = np.stack([r, g, b], -1).reshape(-1, 3)
    out = _apply(name, rgb)
    lines += [f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in out]
    p.write_text("\n".join(lines) + "\n")
    return p
