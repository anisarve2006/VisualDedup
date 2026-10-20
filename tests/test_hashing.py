"""Unit tests for hashing algorithms and Hamming distance."""

from PIL import Image

from visualdedup.core.hasher import (
    compute_ahash,
    compute_dhash,
    compute_file_sha256,
    compute_phash,
    compute_whash,
    extract_image_hashes,
    hamming_distance,
)


def test_sha256_exact_match(sample_images):
    sha_orig = compute_file_sha256(sample_images["original"])
    sha_exact = compute_file_sha256(sample_images["exact"])
    sha_distinct = compute_file_sha256(sample_images["distinct"])

    assert sha_orig == sha_exact
    assert sha_orig != sha_distinct


def test_perceptual_hash_invariance_under_resizing(sample_images):
    """Test that pHash, dHash, aHash, wHash stay very close under resizing."""
    with Image.open(sample_images["original"]) as img1, Image.open(sample_images["resized"]) as img2:
        phash1 = compute_phash(img1)
        phash2 = compute_phash(img2)
        d_p = hamming_distance(phash1, phash2)
        assert d_p <= 4, f"pHash distance under resizing too high: {d_p}"

        dhash1 = compute_dhash(img1)
        dhash2 = compute_dhash(img2)
        d_d = hamming_distance(dhash1, dhash2)
        assert d_d <= 4, f"dHash distance under resizing too high: {d_d}"

        ahash1 = compute_ahash(img1)
        ahash2 = compute_ahash(img2)
        d_a = hamming_distance(ahash1, ahash2)
        assert d_a <= 4, f"aHash distance under resizing too high: {d_a}"

        whash1 = compute_whash(img1)
        whash2 = compute_whash(img2)
        d_w = hamming_distance(whash1, whash2)
        assert d_w <= 6, f"wHash distance under resizing too high: {d_w}"


def test_perceptual_hash_invariance_under_recompression(sample_images):
    """Test resilience against heavy JPEG compression."""
    with Image.open(sample_images["original"]) as img1, Image.open(sample_images["recompressed"]) as img2:
        phash1 = compute_phash(img1)
        phash2 = compute_phash(img2)
        d_p = hamming_distance(phash1, phash2)
        assert d_p <= 4, f"pHash distance under recompression too high: {d_p}"


def test_perceptual_hash_discrimination_on_distinct(sample_images):
    """Ensure distinct images yield large Hamming distances (> 15)."""
    with Image.open(sample_images["original"]) as img1, Image.open(sample_images["distinct"]) as img2:
        phash1 = compute_phash(img1)
        phash2 = compute_phash(img2)
        d_p = hamming_distance(phash1, phash2)
        assert d_p >= 15, f"pHash failed to distinguish different images: distance was {d_p}"


def test_extract_image_hashes(sample_images):
    res = extract_image_hashes(sample_images["original"])
    w, h, fmt, mode, sha, dh, ph, ah, wh = res
    assert w == 500
    assert h == 500
    assert fmt.upper() == "PNG"
    assert len(dh) == 16
    assert len(ph) == 16
    assert len(ah) == 16
    assert len(wh) == 16
