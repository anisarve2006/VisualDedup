"""Image hashing algorithms: SHA-256, dHash, pHash, aHash, and wHash.

Provides exact cryptographic hashing and perceptual visual hashing with fast Hamming
distance computation and optimized single-pass image processing.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
from PIL import Image


def compute_file_sha256(filepath: Union[str, Path], chunk_size: int = 131072) -> str:
    """Compute the SHA-256 cryptographic hash of a file efficiently in 128KB chunks."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _binary_array_to_hex(arr: np.ndarray) -> str:
    """Convert a 1D boolean numpy array (length 64) to a 16-character hexadecimal string."""
    flat = arr.flatten().astype(np.uint8)
    byte_vals = np.packbits(flat)
    return byte_vals.tobytes().hex()


def hex_to_int(hex_str: str) -> int:
    """Convert hexadecimal hash string to 64-bit integer."""
    return int(hex_str, 16)


def hamming_distance(hash1: Union[str, int], hash2: Union[str, int]) -> int:
    """Compute the Hamming distance (number of bit differences) between two 64-bit hashes.

    Uses hardware popcount via int.bit_count() in Python 3.10+.
    """
    if isinstance(hash1, str):
        val1 = int(hash1, 16)
    else:
        val1 = hash1

    if isinstance(hash2, str):
        val2 = int(hash2, 16)
    else:
        val2 = hash2

    xor_val = val1 ^ val2
    return xor_val.bit_count()


def _dct_matrix(n: int) -> np.ndarray:
    """Precompute the orthogonal DCT-II transformation matrix of size n x n."""
    matrix = np.zeros((n, n), dtype=np.float32)
    for k in range(n):
        for i in range(n):
            if k == 0:
                matrix[k, i] = 1.0 / np.sqrt(n)
            else:
                matrix[k, i] = np.sqrt(2.0 / n) * np.cos(np.pi * (2 * i + 1) * k / (2.0 * n))
    return matrix


# Precomputed static DCT matrix for 32x32 to avoid runtime reallocation
_DCT_MATRIX_32 = _dct_matrix(32)


def compute_ahash(image: Image.Image, hash_size: int = 8) -> str:
    """Compute Average Hash (aHash)."""
    img = image.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)
    avg = np.mean(pixels)
    diff = pixels > avg
    return _binary_array_to_hex(diff)


def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
    """Compute Difference Hash (dHash)."""
    img = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)
    diff = pixels[:, 1:] > pixels[:, :-1]
    return _binary_array_to_hex(diff)


def compute_phash(
    image: Image.Image, hash_size: int = 8, highfreq_factor: int = 4
) -> str:
    """Compute Perceptual Hash (pHash) using 2D Discrete Cosine Transform (DCT)."""
    img_size = hash_size * highfreq_factor  # 32
    img = image.convert("L").resize((img_size, img_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)

    # Use precomputed 32x32 DCT matrix if available
    d_mat = _DCT_MATRIX_32 if img_size == 32 else _dct_matrix(img_size)
    dct = np.dot(d_mat, np.dot(pixels, d_mat.T))

    low_freq = dct[:hash_size, :hash_size]
    med = np.median(low_freq.flatten()[1:])
    diff = low_freq > med
    return _binary_array_to_hex(diff)


def _haar_2d_level2(pixels: np.ndarray) -> np.ndarray:
    """Perform a 2-level 2D Haar Wavelet transform using vectorized numpy."""
    current = pixels.copy()
    for _ in range(2):
        row_avg = (current[:, 0::2] + current[:, 1::2]) * 0.70710678
        row_diff = (current[:, 0::2] - current[:, 1::2]) * 0.70710678
        current = np.hstack([row_avg, row_diff])

        col_avg = (current[0::2, :] + current[1::2, :]) * 0.70710678
        col_diff = (current[0::2, :] - current[1::2, :]) * 0.70710678
        current = np.vstack([col_avg, col_diff])

    return current


def compute_whash(image: Image.Image, hash_size: int = 8) -> str:
    """Compute Wavelet Hash (wHash) using 2D Haar Wavelet Transform."""
    scale = 32
    img = image.convert("L").resize((scale, scale), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)

    wavelet_coeffs = _haar_2d_level2(pixels)
    ll_band = wavelet_coeffs[:hash_size, :hash_size]

    med = np.median(ll_band.flatten()[1:])
    diff = ll_band > med
    return _binary_array_to_hex(diff)


def extract_image_hashes(
    filepath: Union[str, Path],
    primary_only: Optional[str] = None,
) -> Tuple[int, int, str, str, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Open an image file once, inspect dimensions, and compute hashes with minimal decode overhead.

    Args:
        filepath: Path to the image file.
        primary_only: If specified (e.g. 'phash', 'dhash'), only compute that perceptual hash
                      for maximum throughput during massive scans.

    Returns:
        (width, height, format, mode, sha256, dhash, phash, ahash, whash)
    """
    path_str = str(filepath)
    sha256_hash = compute_file_sha256(path_str)

    with Image.open(path_str) as img:
        width, height = img.size
        img_format = img.format or "UNKNOWN"
        img_mode = img.mode

        # Fast path: Single grayscale conversion
        gray = img.convert("L")

        # Compute perceptual hashes efficiently from the shared grayscale image
        if primary_only == "dhash":
            d_img = gray.resize((9, 8), Image.Resampling.BILINEAR)
            d_pix = np.asarray(d_img, dtype=np.float32)
            dhash = _binary_array_to_hex(d_pix[:, 1:] > d_pix[:, :-1])
            return width, height, img_format, img_mode, sha256_hash, dhash, None, None, None

        if primary_only == "phash":
            p_img = gray.resize((32, 32), Image.Resampling.BILINEAR)
            p_pix = np.asarray(p_img, dtype=np.float32)
            dct = np.dot(_DCT_MATRIX_32, np.dot(p_pix, _DCT_MATRIX_32.T))
            low_freq = dct[:8, :8]
            med = np.median(low_freq.flatten()[1:])
            phash = _binary_array_to_hex(low_freq > med)
            return width, height, img_format, img_mode, sha256_hash, None, phash, None, None

        # Compute full suite of hashes sharing resized representations
        # 1. 32x32 representation for pHash and wHash
        p_img = gray.resize((32, 32), Image.Resampling.LANCZOS)
        p_pix = np.asarray(p_img, dtype=np.float32)

        # pHash
        dct = np.dot(_DCT_MATRIX_32, np.dot(p_pix, _DCT_MATRIX_32.T))
        low_freq = dct[:8, :8]
        med_p = np.median(low_freq.flatten()[1:])
        phash = _binary_array_to_hex(low_freq > med_p)

        # wHash
        w_coeffs = _haar_2d_level2(p_pix)
        ll_band = w_coeffs[:8, :8]
        med_w = np.median(ll_band.flatten()[1:])
        whash = _binary_array_to_hex(ll_band > med_w)

        # aHash: 8x8 resize
        a_img = gray.resize((8, 8), Image.Resampling.LANCZOS)
        a_pix = np.asarray(a_img, dtype=np.float32)
        ahash = _binary_array_to_hex(a_pix > np.mean(a_pix))

        # dHash: 9x8 resize
        d_img = gray.resize((9, 8), Image.Resampling.LANCZOS)
        d_pix = np.asarray(d_img, dtype=np.float32)
        dhash = _binary_array_to_hex(d_pix[:, 1:] > d_pix[:, :-1])

    return width, height, img_format, img_mode, sha256_hash, dhash, phash, ahash, whash
