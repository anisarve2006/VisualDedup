"""Test contact sheet generation."""

import os
from pathlib import Path
from PIL import Image

from visualdedup.core.keeper import KeeperStrategy, select_keeper
from visualdedup.core.models import DuplicateCluster, FileRecord, MatchEvidence
from visualdedup.reports.contact_sheet import generate_cluster_contact_sheet


def test_generate_cluster_contact_sheet(sample_images, temp_dir):
    out_sheet = temp_dir / "contact_sheet.png"

    r1 = FileRecord(str(sample_images["original"]), 5000, 1.0, 500, 500, "PNG", "RGB", "sha1")
    r2 = FileRecord(str(sample_images["resized"]), 2000, 1.0, 250, 250, "JPEG", "RGB", "sha2")

    cluster = DuplicateCluster(
        cluster_id="cluster_001",
        records=[r1, r2],
        match_category="near_duplicate",
        pairwise_matches=[(r1.path, r2.path, MatchEvidence("resized", "phash", 2, 8, "Resized"))],
        keeper_decision=select_keeper([r1, r2], strategy=KeeperStrategy.BEST_QUALITY),
    )

    path = generate_cluster_contact_sheet(cluster, out_sheet)
    assert Path(path).exists()

    with Image.open(path) as img:
        assert img.width > 300
        assert img.height > 300
