"""Contact sheet generator for visual inspection of duplicate clusters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image, ImageDraw, ImageFont

from visualdedup.core.models import DuplicateCluster


def generate_cluster_contact_sheet(
    cluster: DuplicateCluster,
    output_path: Union[str, Path],
    thumb_width: int = 300,
    thumb_height: int = 300,
    padding: int = 20,
    header_height: int = 50,
) -> str:
    """Generate a single contact sheet image for a duplicate cluster."""
    num_images = len(cluster.records)
    if num_images == 0:
        raise ValueError("Cannot generate contact sheet for empty cluster.")

    # Layout: Horizontal strip or grid
    cols = min(num_images, 4)
    rows = (num_images + cols - 1) // cols

    card_width = thumb_width + padding
    card_height = thumb_height + 80  # Extra for metadata labels

    sheet_width = cols * card_width + padding
    sheet_height = rows * card_height + header_height + padding

    # Create sheet canvas
    sheet = Image.new("RGB", (sheet_width, sheet_height), color=(24, 28, 36))
    draw = ImageDraw.Draw(sheet)

    # Header
    title = f"{cluster.cluster_id.upper()} ({cluster.match_category.upper()}) - {num_images} Images"
    draw.text((padding, padding), title, fill=(56, 189, 248))

    keeper_path = (
        cluster.keeper_decision.keeper_path if cluster.keeper_decision else None
    )

    for idx, rec in enumerate(cluster.records):
        col = idx % cols
        row = idx // cols

        x0 = padding + col * card_width
        y0 = header_height + padding + row * card_height

        is_keeper = (rec.path == keeper_path)

        # Draw card border
        border_color = (16, 185, 129) if is_keeper else (75, 85, 99)
        draw.rectangle(
            [x0, y0, x0 + thumb_width, y0 + thumb_height],
            outline=border_color,
            width=2 if is_keeper else 1,
        )

        # Load and fit image
        try:
            with Image.open(rec.path) as img:
                img = img.convert("RGB")
                img.thumbnail((thumb_width - 8, thumb_height - 8), Image.Resampling.LANCZOS)
                w, h = img.size
                paste_x = x0 + (thumb_width - w) // 2
                paste_y = y0 + (thumb_height - h) // 2
                sheet.paste(img, (paste_x, paste_y))
        except Exception:
            # Draw placeholder error box
            draw.text(
                (x0 + 10, y0 + thumb_height // 2),
                "Error loading image",
                fill=(239, 68, 68),
            )

        # Draw badge and metadata
        badge_text = "★ KEEPER" if is_keeper else "DISCARD"
        badge_color = (16, 185, 129) if is_keeper else (239, 68, 68)
        draw.text((x0, y0 + thumb_height + 6), badge_text, fill=badge_color)

        filename = rec.filename
        if len(filename) > 30:
            filename = filename[:27] + "..."
        draw.text((x0, y0 + thumb_height + 24), filename, fill=(240, 240, 240))

        info_line = f"{rec.width}x{rec.height} ({rec.megapixels}MP) | {rec.format} | {rec.size_bytes // 1024}KB"
        draw.text((x0, y0 + thumb_height + 42), info_line, fill=(156, 163, 175))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out), "PNG")
    return str(out)
