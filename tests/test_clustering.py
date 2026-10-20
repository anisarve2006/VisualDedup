"""Unit tests for Union-Find clustering and match explanation."""

from visualdedup.core.clustering import UnionFind, cluster_duplicates
from visualdedup.core.explanation import explain_match
from visualdedup.core.models import FileRecord, MatchEvidence


def test_union_find_disjoint_components():
    uf = UnionFind(["A", "B", "C", "D", "E"])
    assert uf.union("A", "B") is True
    assert uf.union("B", "C") is True
    assert uf.union("A", "C") is False  # Already connected

    assert uf.find("A") == uf.find("C")
    assert uf.find("D") != uf.find("A")


def test_cluster_duplicates_categories():
    rec_a = FileRecord("a.jpg", 1000, 1.0, 100, 100, "JPEG", "RGB", "sha_1")
    rec_b = FileRecord("b.jpg", 1000, 1.0, 100, 100, "JPEG", "RGB", "sha_1")
    rec_c = FileRecord("c.jpg", 800, 1.0, 80, 80, "JPEG", "RGB", "sha_2")

    records = {"a.jpg": rec_a, "b.jpg": rec_b, "c.jpg": rec_c}

    # a and b are exact
    ev_ab = MatchEvidence("exact", "sha256", 0, 0, "exact match")
    # b and c are near
    ev_bc = MatchEvidence("near_duplicate", "phash", 3, 8, "phash match")

    clusters = cluster_duplicates(records, [("a.jpg", "b.jpg", ev_ab), ("b.jpg", "c.jpg", ev_bc)])
    assert len(clusters) == 1
    cluster = clusters[0]
    assert len(cluster.records) == 3
    assert cluster.match_category == "mixed"


def test_explanation_exact_match():
    r1 = FileRecord("img1.png", 5000, 1.0, 1000, 1000, "PNG", "RGB", "sha_match")
    r2 = FileRecord("img2.png", 5000, 1.0, 1000, 1000, "PNG", "RGB", "sha_match")

    ev = explain_match(r1, r2, "sha256", 0, 0)
    assert ev.match_type == "exact"
    assert "Identical file content" in ev.details


def test_explanation_resizing_detected():
    r1 = FileRecord("large.png", 50000, 1.0, 2000, 1000, "PNG", "RGB", "sha_1")
    r2 = FileRecord("small.jpg", 12000, 1.0, 1000, 500, "JPEG", "RGB", "sha_2")

    ev = explain_match(r1, r2, "phash", 2, 8)
    assert ev.match_type == "resized"
    assert any("Resized copy" in t for t in ev.transformations)
    assert any("Format conversion" in t for t in ev.transformations)
