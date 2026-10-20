"""Transformation classifier and match explanation engine.

Explains *why* two images match:
- Exact byte-level duplicate (SHA-256)
- Resizing / resolution change (identical aspect ratio, different resolution)
- Format conversion / recompression (e.g. PNG to JPEG, compression artifacts)
- Cropping / aspect ratio alteration
- Color/mode transformation (RGB vs grayscale, color shift)
"""

from __future__ import annotations

import os
from typing import List

from visualdedup.core.models import FileRecord, MatchEvidence


def explain_match(
    rec_a: FileRecord,
    rec_b: FileRecord,
    hash_type: str,
    distance: int,
    threshold: int,
) -> MatchEvidence:
    """Analyze two matching image records and produce an evidence explanation."""
    transformations: List[str] = []

    # 1. Exact byte match
    if rec_a.exact_hash == rec_b.exact_hash:
        return MatchEvidence(
            match_type="exact",
            hash_type="sha256",
            distance=0,
            threshold=0,
            details="Identical file content (SHA-256 bit-for-bit duplicate)",
            transformations=["Bit-for-bit identical binary content"],
        )

    # 2. Perceptual match analysis
    ar_a = rec_a.aspect_ratio
    ar_b = rec_b.aspect_ratio
    ar_diff = abs(ar_a - ar_b)

    res_a = f"{rec_a.width}x{rec_a.height}"
    res_b = f"{rec_b.width}x{rec_b.height}"

    is_same_resolution = (rec_a.width == rec_b.width) and (rec_a.height == rec_b.height)

    # Resolution and resizing analysis
    if not is_same_resolution:
        if ar_diff <= 0.03:
            larger = rec_a if (rec_a.width * rec_a.height) > (rec_b.width * rec_b.height) else rec_b
            smaller = rec_b if larger is rec_a else rec_a
            scale_ratio = round(larger.width / max(smaller.width, 1), 2)
            transformations.append(
                f"Resized copy: {smaller.filename} ({smaller.width}x{smaller.height}) is downscaled ~{scale_ratio}x from {larger.filename} ({larger.width}x{larger.height})"
            )
            match_type = "resized"
        else:
            transformations.append(
                f"Aspect ratio difference / possible crop ({res_a} [AR: {ar_a}] vs {res_b} [AR: {ar_b}])"
            )
            match_type = "cropped"
    else:
        match_type = "near_duplicate"

    # Format conversion analysis
    if rec_a.format.upper() != rec_b.format.upper():
        transformations.append(
            f"Format conversion: {rec_a.format.upper()} vs {rec_b.format.upper()}"
        )
        if match_type == "near_duplicate":
            match_type = "recompressed"

    # File size and compression discrepancy
    size_ratio = max(rec_a.size_bytes, rec_b.size_bytes) / max(min(rec_a.size_bytes, rec_b.size_bytes), 1)
    if is_same_resolution and size_ratio > 1.25:
        larger_file = rec_a if rec_a.size_bytes > rec_b.size_bytes else rec_b
        smaller_file = rec_b if larger_file is rec_a else rec_a
        transformations.append(
            f"Recompression / quality difference: {larger_file.filename} ({larger_file.size_bytes // 1024} KB) vs {smaller_file.filename} ({smaller_file.size_bytes // 1024} KB)"
        )
        if match_type == "near_duplicate":
            match_type = "recompressed"

    # Color mode difference
    if rec_a.mode != rec_b.mode:
        transformations.append(
            f"Color mode difference ({rec_a.mode} vs {rec_b.mode})"
        )

    # If no specific transformation identified, standard visual match
    if not transformations:
        transformations.append("Visually identical or minor pixel compression variation")

    details = (
        f"{hash_type} Hamming distance = {distance} (threshold <= {threshold}). "
        + "; ".join(transformations)
    )

    return MatchEvidence(
        match_type=match_type,
        hash_type=hash_type,
        distance=distance,
        threshold=threshold,
        details=details,
        transformations=transformations,
    )
