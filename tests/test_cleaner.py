"""Integration tests for safe cleanup, reports, and end-to-end API/CLI."""

import json
import os
import shutil
from pathlib import Path

from visualdedup.actions.cleaner import CleanMode, execute_cleanup
from visualdedup.api import VisualDedup
from visualdedup.cli import main
from visualdedup.core.keeper import KeeperStrategy
from visualdedup.core.models import DuplicateCluster, FileRecord, KeeperDecision


def test_safe_cleaner_dry_run_does_not_delete(temp_dir):
    f1 = temp_dir / "keep.png"
    f2 = temp_dir / "discard.png"
    f1.write_bytes(b"content1")
    f2.write_bytes(b"content2")

    r1 = FileRecord(str(f1), 8, 1.0, 10, 10, "PNG", "RGB", "sha1")
    r2 = FileRecord(str(f2), 8, 1.0, 10, 10, "PNG", "RGB", "sha2")

    cluster = DuplicateCluster(
        cluster_id="cluster_001",
        records=[r1, r2],
        match_category="near_duplicate",
        keeper_decision=KeeperDecision(str(f1), [str(f2)], "Test reason", "best_quality"),
    )

    # Dry run
    res = execute_cleanup([cluster], mode=CleanMode.DELETE, dry_run=True)
    assert res.dry_run is True
    assert f2.exists(), "Dry run must NOT delete files!"


def test_safe_cleaner_quarantine(temp_dir):
    f1 = temp_dir / "keep.png"
    f2 = temp_dir / "discard.png"
    quarantine_dir = temp_dir / "quarantine"
    f1.write_bytes(b"content1")
    f2.write_bytes(b"content2")

    r1 = FileRecord(str(f1), 8, 1.0, 10, 10, "PNG", "RGB", "sha1")
    r2 = FileRecord(str(f2), 8, 1.0, 10, 10, "PNG", "RGB", "sha2")

    cluster = DuplicateCluster(
        cluster_id="cluster_001",
        records=[r1, r2],
        match_category="near_duplicate",
        keeper_decision=KeeperDecision(str(f1), [str(f2)], "Test reason", "best_quality"),
    )

    res = execute_cleanup(
        [cluster], mode=CleanMode.QUARANTINE, target_dir=quarantine_dir, dry_run=False
    )
    assert not f2.exists()
    assert f1.exists()
    # Check moved into quarantine
    quarantined_files = list(quarantine_dir.glob("*"))
    assert len(quarantined_files) == 1
    assert "discard.png" in quarantined_files[0].name


def test_store_duplicates_organized_by_cluster(temp_dir):
    f1 = temp_dir / "orig.png"
    f2 = temp_dir / "dup.png"
    out_dir = temp_dir / "duplicates_out"
    f1.write_bytes(b"image_content_1")
    f2.write_bytes(b"image_content_2")

    r1 = FileRecord(str(f1), 15, 1.0, 100, 100, "PNG", "RGB", "sha1")
    r2 = FileRecord(str(f2), 15, 1.0, 50, 50, "PNG", "RGB", "sha2")

    cluster = DuplicateCluster(
        cluster_id="cluster_0042",
        records=[r1, r2],
        match_category="near_duplicate",
        keeper_decision=KeeperDecision(str(f1), [str(f2)], "Higher res", "best_quality"),
    )

    vd = VisualDedup(cache_path=None)
    res = vd.store_duplicates([cluster], output_dir=out_dir, action="copy", organize_by_cluster=True)

    assert res.total_files_affected == 2
    assert (out_dir / "cluster_0042").exists()
    assert (out_dir / "cluster_0042" / "KEEPER_orig.png").exists()
    assert (out_dir / "cluster_0042" / "DISCARD_dup.png").exists()
    assert (out_dir / "duplicates_manifest.json").exists()
    # Originals must remain untouched in copy mode
    assert f1.exists()
    assert f2.exists()


def test_end_to_end_api_scan_and_reports(sample_images, temp_dir):
    json_out = temp_dir / "report.json"
    html_out = temp_dir / "report.html"

    vd = VisualDedup(
        cache_path=temp_dir / "cache.db",
        hash_type="phash",
        threshold=8,
    )

    clusters, summary = vd.scan([sample_images["dir"]])
    assert summary.total_scanned >= 5
    assert len(clusters) >= 1

    # Check keeper was recommended
    for c in clusters:
        assert c.keeper_decision is not None
        assert c.keeper_decision.keeper_path

    # Export JSON
    vd.export_json(clusters, summary, json_out)
    assert json_out.exists()
    with open(json_out, "r") as f:
        data = json.load(f)
        assert data["visualdedup_version"] == "0.2.0"
        assert len(data["clusters"]) == len(clusters)

    # Export HTML
    vd.export_html(clusters, summary, html_out)
    assert html_out.exists()
    html_content = html_out.read_text(encoding="utf-8")
    assert "VisualDedup Inspection Report" in html_content
    assert "RECOMMENDED KEEPER" in html_content


def test_cli_scan_command(sample_images, temp_dir):
    report_json = temp_dir / "cli_report.json"
    report_html = temp_dir / "cli_report.html"

    ret = main([
        "scan",
        str(sample_images["dir"]),
        "--output", str(report_json),
        "--html", str(report_html),
        "--threshold", "8",
        "--cache", str(temp_dir / "cli_cache.db"),
    ])

    assert ret == 0
    assert report_json.exists()
    assert report_html.exists()


def test_cli_scan_csv_and_json(sample_images, temp_dir):
    report_csv = temp_dir / "cli_report.csv"

    ret = main([
        "scan",
        str(sample_images["dir"]),
        "--csv", str(report_csv),
        "--threshold", "8",
        "--cache", str(temp_dir / "cli_cache_csv.db"),
    ])

    assert ret == 0
    assert report_csv.exists()
    content = report_csv.read_text(encoding="utf-8")
    assert "cluster_id,match_category,role" in content
    assert "KEEPER" in content


def test_cli_inspect_command(sample_images):
    ret = main([
        "inspect",
        str(sample_images["original"]),
        str(sample_images["resized"]),
    ])
    assert ret == 0

    ret_json = main([
        "inspect",
        str(sample_images["original"]),
        str(sample_images["resized"]),
        "--json",
    ])
    assert ret_json == 0
