# VisualDedup 🔍✨

[![CI](https://github.com/visualdedup/visualdedup/actions/workflows/ci.yml/badge.svg)](https://github.com/visualdedup/visualdedup/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

**VisualDedup** is a high-performance Python toolkit designed to find exact and visually similar images in large collections, cluster them into duplicate groups, **explain why they match**, recommend which copy to retain, and **safely clean datasets without destructive surprises**.

Existing libraries such as `imagededup` and `Perception` provide basic perceptual hashing. VisualDedup goes beyond basic hashing to solve the real operational challenges of large-scale dataset management:

1. **Explains Why Images Match:** Classifies transformations (resizing, JPEG recompression, format conversion, and cropping).
2. **Sub-Quadratic Indexing:** Uses **BK-Trees** and **Multi-Index Hamming Hashing** to eliminate the $O(N^2)$ pairwise comparison bottleneck, scaling to hundreds of thousands of images.
3. **Intelligent Keeper Recommendation:** Recommends the optimal file to retain based on resolution, lossless format preservation, compression quality, and original timestamps.
4. **Safe Dataset Cleanup:** Non-destructive by default with strict dry-run modes, quarantine isolation, and full JSON audit logs.
5. **Interactive Visual Reports:** Generates standalone HTML dashboards and image contact sheets with side-by-side previews, difference metrics, and keeper badges.
6. **Incremental SQLite Cache:** Avoids recomputing hashes on subsequent scans by tracking file modification times and byte sizes.

---

## ⚡ Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/your-org/visualdedup.git
cd visualdedup

# Create virtual environment and install
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev]"
```

---

## 💻 Command-Line Interface (CLI)

### Scan a Folder and Generate Reports

```bash
# Scan with pHash (DCT) and export JSON + interactive HTML reports
visualdedup scan ./photos --output report.json --html report.html

# Scan with custom Hamming threshold and contact sheets
visualdedup scan ./dataset --hash phash --threshold 8 --contact-sheet sheet.png

# Fast candidate indexing with Multi-Index Hashing for large collections
visualdedup scan ./large_collection --index multi_index --keeper best_quality
```

### Inspect Two Images Side-by-Side

```bash
visualdedup inspect original.png compressed_downscaled.jpg
```

Outputs a detailed comparison table with SHA-256, dHash, pHash, aHash, wHash distances, resolution differences, and an automated diagnosis (e.g. `Resized copy: downscaled ~2.0x; JPEG recompression`).

### Safe Dataset Cleanup

```bash
# Dry run simulation (default: does not touch files)
visualdedup clean ./dataset --mode quarantine --dry-run

# Execute quarantine move with confirmation
visualdedup clean ./dataset --mode quarantine --target-dir ./quarantine --confirm
```

---

## 🐍 Python Library API

```python
from visualdedup import VisualDedup, KeeperStrategy, CleanMode

# 1. Initialize engine with incremental caching and sub-quadratic indexing
vd = VisualDedup(
    cache_path=".visualdedup_cache.db",
    hash_type="phash",       # "phash", "dhash", "ahash", "whash", "exact"
    threshold=8,             # Max Hamming distance
    index_type="bktree",     # "bktree" or "multi_index"
)

# 2. Scan folders
clusters, summary = vd.scan(["./dataset"], recursive=True)

print(f"Scanned {summary.total_scanned} files.")
print(f"Found {summary.total_clusters} duplicate clusters.")
print(f"Reclaimable space: {summary.reclaimable_bytes / (1024 * 1024):.2f} MB")

# 3. Inspect keeper recommendations
for cluster in clusters:
    print(f"\nCluster {cluster.cluster_id} ({cluster.match_category}):")
    print(f"  Keeper: {cluster.keeper_decision.keeper_path}")
    print(f"  Reason: {cluster.keeper_decision.reason}")
    print(f"  Discards: {cluster.keeper_decision.discard_paths}")

# 4. Export visual reports
vd.export_html(clusters, summary, "report.html")
vd.export_json(clusters, summary, "report.json")

# 5. Execute safe cleanup (e.g. quarantine mode with dry run)
clean_result = vd.clean(
    clusters,
    mode=CleanMode.QUARANTINE,
    target_dir="./quarantine_folder",
    dry_run=True,
    audit_log_path="audit.json"
)
```

---

## 🚀 Performance & Sub-Quadratic Indexing

Naive deduplication compares every image pair ($O(N^2)$ comparisons). For 5,000 images, that requires 12.5 million comparisons.

VisualDedup implements metric **BK-Trees** and **Multi-Index Hamming Hashing** (Pigeonhole block search):

| Dataset Size | Pairwise Checks $N(N-1)/2$ | Naive Linear $O(N^2)$ | BK-Tree $O(N \log N)$ | Multi-Index Hash | Speedup |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **500** | 124,750 | 31 ms | 38 ms | **4 ms** | **7.8x** |
| **1,000** | 499,500 | 116 ms | 124 ms | **8 ms** | **14.5x** |
| **2,500** | 3,123,750 | 697 ms | 619 ms | **20 ms** | **34.8x** |
| **5,000** | 12,497,500 | 3,000 ms | 2,088 ms | **59 ms** | **50.5x** |

Run the benchmarks yourself:
```bash
python benchmarks/benchmark_indexing.py
```

---

## 🛡️ Keeper Selection Strategies

| Strategy | Criteria | Best For |
|---|---|---|
| `best_quality` *(default)* | Resolution > Lossless format (PNG > JPEG) > File size > Original timestamp | General dataset cleaning |
| `highest_resolution` | Maximizes pixel dimensions ($W \times H$) | Upscaled/downscaled collections |
| `smallest_file` | Minimizes storage space | Bandwidth / disk-constrained archives |
| `largest_file` | Preserves least compressed files | Photography & print workflows |
| `oldest` | Retains earliest file by modification date | Digital asset origin preservation |
| `newest` | Retains most recently modified file | Continuous syncing backups |

---

## 🧪 Testing

```bash
pytest -v
```

All 22 unit and integration tests validate hashing invariance, tree search pruning, cluster disjoint sets, transformation explanations, safe deletion guards, and report exports.

---

## 📄 License

VisualDedup is distributed under the [MIT License](LICENSE).
