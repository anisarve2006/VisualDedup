"""Pytest fixtures for VisualDedup test suite."""

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw


@pytest.fixture
def temp_dir():
    """Create a temporary directory cleaned up after test."""
    temp_path = Path(tempfile.mkdtemp(prefix="visualdedup_test_"))
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def sample_images(temp_dir):
    """Generate a controlled suite of test images:
    - original.png (500x500 high-res geometric artwork)
    - exact_copy.png (bit-for-bit identical to original.png)
    - resized_half.jpg (250x250 downscaled version of original)
    - compressed.jpg (500x500 JPEG recompressed at quality 40)
    - distinct.png (500x500 completely different visual content)
    - cropped.png (500x250 cropped version)
    """
    img_dir = temp_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 1. Base Image: High-res artwork with distinct gradient and shapes
    base = Image.new("RGB", (500, 500), color=(30, 60, 120))
    draw = ImageDraw.Draw(base)
    draw.rectangle([50, 50, 200, 200], fill=(220, 80, 50), outline=(255, 255, 255), width=3)
    draw.ellipse([250, 250, 450, 450], fill=(50, 180, 90), outline=(255, 255, 255), width=3)
    draw.line([0, 500, 500, 0], fill=(240, 220, 50), width=6)

    orig_path = img_dir / "original.png"
    base.save(orig_path, "PNG")

    # 2. Exact bit-for-bit copy
    exact_path = img_dir / "exact_copy.png"
    shutil.copyfile(orig_path, exact_path)

    # 3. Resized copy (250x250)
    resized = base.resize((250, 250), Image.Resampling.LANCZOS)
    resized_path = img_dir / "resized_half.jpg"
    resized.save(resized_path, "JPEG", quality=90)

    # 4. Recompressed copy (500x500 JPEG quality 35)
    recompressed_path = img_dir / "recompressed.jpg"
    base.save(recompressed_path, "JPEG", quality=35)

    # 5. Distinct image (noise/checkerboard pattern)
    distinct = Image.new("RGB", (500, 500), color=(200, 200, 200))
    d_draw = ImageDraw.Draw(distinct)
    for x in range(0, 500, 50):
        for y in range(0, 500, 50):
            if (x + y) % 100 == 0:
                d_draw.rectangle([x, y, x + 50, y + 50], fill=(10, 10, 10))
    distinct_path = img_dir / "distinct.png"
    distinct.save(distinct_path, "PNG")

    # 6. Cropped version (500x250)
    cropped = base.crop((0, 0, 500, 250))
    cropped_path = img_dir / "cropped.png"
    cropped.save(cropped_path, "PNG")

    return {
        "dir": img_dir,
        "original": orig_path,
        "exact": exact_path,
        "resized": resized_path,
        "recompressed": recompressed_path,
        "distinct": distinct_path,
        "cropped": cropped_path,
    }
