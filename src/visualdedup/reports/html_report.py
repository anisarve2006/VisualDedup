"""Self-contained interactive HTML visual report for duplicate inspection."""

from __future__ import annotations

import base64
import html
import io
import os
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image

from visualdedup.core.models import DuplicateCluster, ScanSummary


def _make_thumbnail_data_uri(image_path: str, max_size: int = 240) -> str:
    """Generate a lightweight base64 JPEG thumbnail data URI for the HTML report."""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        # Fallback SVG placeholder if image cannot be read
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{max_size}" height="{max_size}" viewBox="0 0 {max_size} {max_size}"><rect width="100%" height="100%" fill="#262626"/><text x="50%" y="50%" fill="#888" font-size="12" text-anchor="middle" dy=".3em">Preview Unavailable</text></svg>'
        b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"


def format_bytes(num_bytes: int) -> str:
    """Format bytes into human readable KB, MB, GB."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def generate_html_report(
    clusters: List[DuplicateCluster],
    summary: ScanSummary,
    output_path: Optional[Union[str, Path]] = None,
    embed_thumbnails: bool = True,
) -> str:
    """Generate a modern, self-contained HTML visual report with thumbnails and keeper recommendations."""
    clusters_html = []

    for cluster in clusters:
        keeper_path = (
            cluster.keeper_decision.keeper_path if cluster.keeper_decision else None
        )
        keeper_reason = (
            html.escape(cluster.keeper_decision.reason)
            if cluster.keeper_decision
            else "No keeper recommendation"
        )

        category_badge_class = (
            "badge-exact" if cluster.match_category == "exact" else "badge-near"
        )
        category_label = (
            "Exact Duplicates"
            if cluster.match_category == "exact"
            else "Near-Duplicates / Visually Similar"
        )

        # Collect pairwise explanations
        evidence_items = []
        for a, b, ev in cluster.pairwise_matches:
            evidence_items.append(
                f"""
                <div class="evidence-item">
                    <span class="evidence-pill">{html.escape(ev.hash_type.upper())} Dist: {ev.distance}</span>
                    <span class="evidence-text">{html.escape(ev.details)}</span>
                </div>
                """
            )
        evidence_html = "\n".join(evidence_items)

        # File cards
        records_html = []
        for r in cluster.records:
            is_keeper = (r.path == keeper_path)
            card_class = "file-card keeper-card" if is_keeper else "file-card discard-card"
            badge = (
                '<span class="badge keeper-badge">★ RECOMMENDED KEEPER</span>'
                if is_keeper
                else '<span class="badge discard-badge">CANDIDATE FOR REMOVAL</span>'
            )

            thumb_src = (
                _make_thumbnail_data_uri(r.path)
                if embed_thumbnails
                else f"file:///{r.path.replace(os.sep, '/')}"
            )

            records_html.append(
                f"""
                <div class="{card_class}">
                    <div class="card-badge-header">{badge}</div>
                    <div class="thumb-container">
                        <img src="{thumb_src}" alt="{html.escape(r.filename)}" loading="lazy" />
                    </div>
                    <div class="file-info">
                        <div class="file-name" title="{html.escape(r.path)}">{html.escape(r.filename)}</div>
                        <div class="file-meta">
                            <span><strong>Res:</strong> {r.width} &times; {r.height} ({r.megapixels} MP)</span>
                            <span><strong>Format:</strong> {r.format} ({r.mode})</span>
                            <span><strong>Size:</strong> {format_bytes(r.size_bytes)}</span>
                        </div>
                        <div class="file-path" title="{html.escape(r.path)}">{html.escape(r.path)}</div>
                    </div>
                </div>
                """
            )

        records_grid = "\n".join(records_html)

        cluster_card = f"""
        <div class="cluster-card" data-category="{cluster.match_category}">
            <div class="cluster-header">
                <div class="cluster-title">
                    <span class="cluster-id">{html.escape(cluster.cluster_id)}</span>
                    <span class="badge {category_badge_class}">{category_label}</span>
                    <span class="cluster-count">{len(cluster.records)} images</span>
                </div>
                <div class="cluster-savings">
                    Potential Savings: <strong>{format_bytes(cluster.potential_savings_bytes)}</strong>
                </div>
            </div>
            
            <div class="keeper-banner">
                <div class="keeper-icon">💡</div>
                <div class="keeper-text">
                    <strong>Keeper Recommendation:</strong> {keeper_reason}
                </div>
            </div>

            <div class="records-grid">
                {records_grid}
            </div>

            {f'<div class="evidence-box"><h4>Match Evidence & Provenance:</h4>{evidence_html}</div>' if evidence_html else ''}
        </div>
        """
        clusters_html.append(cluster_card)

    rendered_clusters = "\n".join(clusters_html) if clusters_html else """
    <div class="empty-state">
        <h3>🎉 No Duplicates Found!</h3>
        <p>All scanned images in the collection appear to be unique.</p>
    </div>
    """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VisualDedup Inspection Report</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --border: #334155;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --primary-bg: rgba(56, 189, 248, 0.12);
            --success: #10b981;
            --success-bg: rgba(16, 185, 129, 0.15);
            --danger: #ef4444;
            --danger-bg: rgba(239, 68, 68, 0.15);
            --warning: #f59e0b;
            --warning-bg: rgba(245, 158, 11, 0.15);
            --radius: 10px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 2rem 1.5rem;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 2rem;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .brand h1 {{
            font-size: 1.85rem;
            font-weight: 700;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .brand p {{ color: var(--text-muted); font-size: 0.9rem; margin-top: 0.25rem; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: var(--surface);
            padding: 1.25rem;
            border-radius: var(--radius);
            border: 1px solid var(--border);
        }}
        .stat-card .label {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); }}
        .stat-card .value {{ font-size: 1.6rem; font-weight: 700; margin-top: 0.25rem; color: var(--primary); }}
        .stat-card.highlight .value {{ color: var(--success); }}

        .controls {{
            display: flex;
            gap: 0.75rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
            align-items: center;
        }}
        .btn {{
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--border);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn:hover, .btn.active {{
            background: var(--primary);
            color: #0f172a;
            border-color: var(--primary);
            font-weight: 600;
        }}
        .search-box {{
            margin-left: auto;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.5rem 1rem;
            color: var(--text);
            font-size: 0.85rem;
            min-width: 250px;
        }}

        .cluster-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        .cluster-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}
        .cluster-title {{ display: flex; align-items: center; gap: 0.75rem; }}
        .cluster-id {{ font-size: 1.1rem; font-weight: 700; }}
        .cluster-count {{ color: var(--text-muted); font-size: 0.85rem; }}
        .cluster-savings {{ font-size: 0.9rem; color: var(--text-muted); }}
        .cluster-savings strong {{ color: var(--success); }}

        .badge {{
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            text-transform: uppercase;
        }}
        .badge-exact {{ background: var(--primary-bg); color: var(--primary); }}
        .badge-near {{ background: var(--warning-bg); color: var(--warning); }}
        .keeper-badge {{ background: var(--success-bg); color: var(--success); border: 1px solid var(--success); }}
        .discard-badge {{ background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger); }}

        .keeper-banner {{
            background: rgba(16, 185, 129, 0.08);
            border-left: 4px solid var(--success);
            padding: 0.75rem 1rem;
            border-radius: 4px;
            margin-bottom: 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 0.9rem;
        }}

        .records-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.25rem;
            margin-bottom: 1.25rem;
        }}
        .file-card {{
            background: #151e2e;
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: transform 0.2s;
        }}
        .file-card:hover {{ transform: translateY(-2px); }}
        .keeper-card {{ border: 2px solid var(--success); }}
        .discard-card {{ border: 1px solid var(--border); opacity: 0.9; }}
        .card-badge-header {{
            padding: 0.5rem 0.75rem;
            background: rgba(0, 0, 0, 0.2);
            display: flex;
            justify-content: flex-start;
        }}
        .thumb-container {{
            width: 100%;
            height: 180px;
            background: #090d16;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }}
        .thumb-container img {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }}
        .file-info {{
            padding: 0.75rem;
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
            font-size: 0.8rem;
        }}
        .file-name {{
            font-weight: 600;
            color: var(--text);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .file-meta {{
            color: var(--text-muted);
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }}
        .file-path {{
            font-family: monospace;
            font-size: 0.7rem;
            color: #64748b;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-top: 0.25rem;
        }}

        .evidence-box {{
            background: rgba(0, 0, 0, 0.2);
            border-radius: 6px;
            padding: 0.75rem 1rem;
            font-size: 0.8rem;
        }}
        .evidence-box h4 {{
            font-size: 0.75rem;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }}
        .evidence-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.25rem;
        }}
        .evidence-pill {{
            background: var(--surface-hover);
            padding: 0.1rem 0.4rem;
            border-radius: 3px;
            font-size: 0.7rem;
            font-family: monospace;
            color: var(--primary);
        }}
        .evidence-text {{ color: var(--text-muted); }}

        .empty-state {{
            text-align: center;
            padding: 4rem 1rem;
            background: var(--surface);
            border-radius: var(--radius);
        }}
        .empty-state h3 {{ font-size: 1.4rem; margin-bottom: 0.5rem; }}
        .empty-state p {{ color: var(--text-muted); }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <h1>VisualDedup Inspection Report</h1>
                <p>Auditable dataset duplicate analysis and keeper recommendations</p>
            </div>
        </header>

        <section class="stats-grid">
            <div class="stat-card">
                <div class="label">Total Scanned</div>
                <div class="value">{summary.total_scanned}</div>
            </div>
            <div class="stat-card">
                <div class="label">Duplicate Clusters</div>
                <div class="value">{summary.total_clusters}</div>
            </div>
            <div class="stat-card">
                <div class="label">Duplicate Images</div>
                <div class="value">{summary.total_duplicates}</div>
            </div>
            <div class="stat-card highlight">
                <div class="label">Reclaimable Space</div>
                <div class="value">{format_bytes(summary.reclaimable_bytes)}</div>
            </div>
            <div class="stat-card">
                <div class="label">Cache Hits / Misses</div>
                <div class="value">{summary.cache_hits} / {summary.cache_misses}</div>
            </div>
            <div class="stat-card">
                <div class="label">Scan Duration</div>
                <div class="value">{summary.duration_seconds:.2f}s</div>
            </div>
        </section>

        <div class="controls">
            <button class="btn active" onclick="filterClusters('all', this)">All Clusters</button>
            <button class="btn" onclick="filterClusters('exact', this)">Exact Duplicates</button>
            <button class="btn" onclick="filterClusters('near_duplicate', this)">Near-Duplicates</button>
            <input type="text" class="search-box" id="searchBox" placeholder="Filter by filename or ID..." oninput="searchClusters()" />
        </div>

        <section id="clustersContainer">
            {rendered_clusters}
        </section>
    </div>

    <script>
        function filterClusters(category, btn) {{
            document.querySelectorAll('.controls .btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const cards = document.querySelectorAll('.cluster-card');
            cards.forEach(card => {{
                if (category === 'all' || card.getAttribute('data-category') === category) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}

        function searchClusters() {{
            const query = document.getElementById('searchBox').value.toLowerCase();
            const cards = document.querySelectorAll('.cluster-card');
            cards.forEach(card => {{
                const text = card.innerText.toLowerCase();
                if (text.includes(query)) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>
"""

    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(html_content)

    return html_content
