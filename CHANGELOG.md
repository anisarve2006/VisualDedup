# Changelog

All notable changes to **VisualDedup** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-21

### Added
- **BK-Tree & Pigeonhole Multi-Index**: Sub-quadratic indexing algorithms providing 50x faster candidate search than naive $O(N^2)$ comparisons.
- **Explainable Match Engine**: Automatically diagnoses why images match (JPEG recompression, aspect ratio / cropping suspect, resolution downscaling, format conversion).
- **Automated Keeper Engine**: 6 deterministic preservation strategies (`best_quality`, `highest_resolution`, `smallest_file`, `largest_file`, `oldest`, `newest`) plus custom scoring hooks.
- **Safe Cleanup Actions**: Non-destructive quarantine, safe deletion, and `--store-duplicates` directory organization with full JSON manifest export.
- **Reports & Visual Dashboard**: Self-contained HTML dashboard with embedded thumbnails, structured JSON & CSV exports, and visual contact sheets.
- **Multithreading**: Thread-pool decoding scaling to 150+ images/sec on multicore CPUs.
- **CLI Suite**: Full CLI commands (`scan`, `inspect`, `clean`) with Rich terminal formatting.
- **Test Suite**: 24 automated unit and integration tests across perceptual hashing, indexing, clustering, and reporting.

## [0.1.0] - Initial Prototype
- Basic perceptual hashing (dHash, pHash, aHash, wHash).
- Exact file hash matching (SHA-256).
- Disjoint-Set union-find clustering.
