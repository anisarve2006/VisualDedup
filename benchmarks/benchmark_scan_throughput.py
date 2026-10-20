"""Benchmark measuring image processing and hashing throughput."""

import shutil
import tempfile
import time
from pathlib import Path
from PIL import Image, ImageDraw

from visualdedup import VisualDedup


def create_test_images(dest_dir: Path, count: int = 100):
    dest_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        # 1000x1000 images with varied shapes
        img = Image.new("RGB", (1000, 1000), color=(i * 2 % 255, (i * 5) % 255, (i * 7) % 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse([100, 100, 900, 900], fill=((i * 11) % 255, 128, 200))
        draw.rectangle([200, 200, 800, 800], outline=(255, 255, 255), width=5)
        # Mix PNG and JPEG
        ext = "jpg" if i % 2 == 0 else "png"
        img.save(dest_dir / f"img_{i:04d}.{ext}")


def main():
    tmp_path = Path(tempfile.mkdtemp(prefix="vd_bench_"))
    try:
        print("Generating 100 benchmark images (1000x1000)...")
        create_test_images(tmp_path, count=100)

        vd = VisualDedup(cache_path=tmp_path / "cache.db", hash_type="phash")

        print("Running cold scan (no cache)...")
        start = time.perf_counter()
        clusters, summary = vd.scan([tmp_path])
        duration = time.perf_counter() - start

        fps = summary.total_scanned / duration
        print(f"Cold scan: {summary.total_scanned} images in {duration:.2f}s ({fps:.1f} images/sec)")

        print("Running warm scan (with SQLite cache)...")
        start = time.perf_counter()
        clusters_warm, summary_warm = vd.scan([tmp_path])
        duration_warm = time.perf_counter() - start
        fps_warm = summary_warm.total_scanned / max(duration_warm, 0.0001)
        print(f"Warm scan: {summary_warm.total_scanned} images in {duration_warm:.4f}s ({fps_warm:.1f} images/sec, {summary_warm.cache_hits} cache hits!)")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


if __name__ == "__main__":
    main()
