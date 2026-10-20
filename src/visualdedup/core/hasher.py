"""Image hashing algorithms: SHA-256, dHash, pHash, aHash, and wHash.

Provides exact cryptographic hashing and perceptual visual hashing with fast Hamming
distance computation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
from PIL import Image


def compute_file_sha256(filepath: Union[str, Path], chunk_size: int = 65536) -> str:
    """Compute the SHA-256 cryptographic hash of a file efficiently in chunks."""
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
    # Pack 64 bits into 8 bytes
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


def compute_ahash(image: Image.Image, hash_size: int = 8) -> str:
    """Compute Average Hash (aHash).

    Steps:
    1. Grayscale conversion.
    2. Resize to hash_size x hash_size (8x8) using high-quality box/lanczos resampling.
    3. Compare each pixel to the mean pixel intensity.
    """
    img = image.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)
    avg = np.mean(pixels)
    diff = pixels > avg
    return _binary_array_to_hex(diff)


def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
    """Compute Difference Hash (dHash).

    Tracks relative horizontal brightness gradients.
    Steps:
    1. Grayscale conversion.
    2. Resize to (hash_size + 1, hash_size) -> (9x8).
    3. Compare adjacent horizontal pixels (col[i+1] > col[i]).
    """
    img = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)
    # Compare adjacent columns: shape (8, 8)
    diff = pixels[:, 1:] > pixels[:, :-1]
    return _binary_array_to_hex(diff)


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


def compute_phash(
    image: Image.Image, hash_size: int = 8, highfreq_factor: int = 4
) -> str:
    """Compute Perceptual Hash (pHash) using 2D Discrete Cosine Transform (DCT).

    Steps:
    1. Grayscale conversion.
    2. Resize to 32x32 (highfreq_factor * hash_size).
    3. Compute 2D DCT-II.
    4. Extract low-frequency 8x8 submatrix (excluding DC term or median comparison).
    5. Compute median of low-frequency coefficients.
    6. Form 64-bit boolean hash where coeff > median.
    """
    img_size = hash_size * highfreq_factor  # 32
    img = image.convert("L").resize((img_size, img_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)

    # 2D DCT: D * pixels * D.T
    d_mat = _dct_matrix(img_size)
    dct = np.dot(d_mat, np.dot(pixels, d_mat.T))

    # Extract lowest frequencies (hash_size x hash_size)
    low_freq = dct[:hash_size, :hash_size]

    # Use median excluding the DC component at (0, 0)
    med = np.median(low_freq.flatten()[1:])
    diff = low_freq > med
    return _binary_array_to_hex(diff)


def _haar_2d_level2(pixels: np.ndarray) -> np.ndarray:
    """Perform a 2-level 2D Haar Wavelet transform using numpy.

    Decomposes an N x N matrix (where N is a power of 2, e.g. 16x16 or 32x32) into
    sub-bands, returning the LL approximation band.
    """
    current = pixels.copy()
    for _ in range(2):
        h, w = current.shape
        # Transform rows: (a + b)/sqrt(2), (a - b)/sqrt(2)
        row_avg = (current[:, 0::2] + current[:, 1::2]) * 0.70710678
        row_diff = (current[:, 0::2] - current[:, 1::2]) * 0.70710678
        current = np.hstack([row_avg, row_diff])

        # Transform columns
        col_avg = (current[0::2, :] + current[1::2, :]) * 0.70710678
        col_diff = (current[0::2, :] - current[1::2, :]) * 0.70710678
        current = np.vstack([col_avg, col_diff])

    return current


def compute_whash(image: Image.Image, hash_size: int = 8) -> str:
    """Compute Wavelet Hash (wHash) using 2D Haar Wavelet Transform.

    Provides exceptional resilience against compression artifacts and gamma shifts.
    Steps:
    1. Grayscale conversion.
    2. Resize to 32x32.
    3. 2-level 2D Haar wavelet decomposition.
    4. Extract LL (low-low) 8x8 approximation sub-band.
    5. Threshold coefficients against median.
    """
    scale = 32
    img = image.convert("L").resize((scale, scale), Image.Resampling.LANCZOS)
    pixels = np.asarray(img, dtype=np.float32)

    wavelet_coeffs = _haar_2d_level2(pixels)
    ll_band = wavelet_coeffs[:hash_size, :hash_size]

    med = np.median(ll_band.flatten()[1:])
    diff = ll_band > med
    return _binary_array_to_hex(diff)


def extract_image_hashes(
    filepath: Union[str, Path]
) -> Tuple[int, int, str, str, str, str, str, str, str]:
    """Open an image file, inspect its dimensions and formats, and compute all hashes.

    Returns:
        (width, height, format, mode, sha256, dhash, phash, ahash, whash)
    """
    path_str = str(filepath)
    sha256_hash = compute_file_sha256(path_str)

    with Image.open(path_str) as img:
        width, height = img.size
        img_format = img.format or "UNKNOWN"
        img_mode = img.mode

        # Ensure image is in a mode suitable for processing
        dhash = compute_dhash(img)
        phash = compute_phash(img)
        ahash = compute_ahash(img)
        whash = compute_whash(img)

    return width, height, img_format, img_mode, sha256_hash, dhash, phash, ahash, whash
