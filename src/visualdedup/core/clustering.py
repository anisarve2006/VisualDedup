"""Duplicate clustering using Disjoint Set (Union-Find) with path compression."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from visualdedup.core.models import DuplicateCluster, FileRecord, MatchEvidence


class UnionFind:
    """Disjoint-set data structure with path compression and union by rank."""

    def __init__(self, elements: List[str]):
        self.parent: Dict[str, str] = {e: e for e in elements}
        self.rank: Dict[str, int] = {e: 0 for e in elements}

    def find(self, item: str) -> str:
        """Find representative with path compression."""
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: str, b: str) -> bool:
        """Union two sets by rank. Returns True if sets were merged, False if already connected."""
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return False

        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1
        return True


def cluster_duplicates(
    records: Dict[str, FileRecord],
    pairwise_matches: List[Tuple[str, str, MatchEvidence]],
) -> List[DuplicateCluster]:
    """Group duplicate image records into clusters using connected components.

    Args:
        records: Mapping from filepath to FileRecord.
        pairwise_matches: List of (filepath_a, filepath_b, MatchEvidence).

    Returns:
        List of DuplicateCluster objects containing 2 or more files each.
    """
    if not pairwise_matches or not records:
        return []

    # Initialize union find for all records involved in matches
    matched_paths = set()
    for a, b, _ in pairwise_matches:
        if a in records and b in records:
            matched_paths.add(a)
            matched_paths.add(b)

    uf = UnionFind(list(matched_paths))
    for a, b, _ in pairwise_matches:
        if a in records and b in records:
            uf.union(a, b)

    # Group records by root
    groups: Dict[str, List[FileRecord]] = {}
    edges_by_root: Dict[str, List[Tuple[str, str, MatchEvidence]]] = {}

    for path in matched_paths:
        root = uf.find(path)
        if root not in groups:
            groups[root] = []
            edges_by_root[root] = []
        groups[root].append(records[path])

    for a, b, evidence in pairwise_matches:
        if a in records and b in records:
            root = uf.find(a)
            edges_by_root[root].append((a, b, evidence))

    clusters: List[DuplicateCluster] = []
    cluster_num = 1

    for root, cluster_records in groups.items():
        if len(cluster_records) < 2:
            continue

        # Determine cluster category
        all_exact = True
        any_exact = False
        sha_set = {r.exact_hash for r in cluster_records}

        if len(sha_set) == 1:
            match_category = "exact"
        else:
            # Check edge types
            cluster_edges = edges_by_root[root]
            has_perceptual = any(e.hash_type != "sha256" for _, _, e in cluster_edges)
            has_exact = any(e.hash_type == "sha256" for _, _, e in cluster_edges)
            if has_perceptual and has_exact:
                match_category = "mixed"
            else:
                match_category = "near_duplicate"

        cluster = DuplicateCluster(
            cluster_id=f"cluster_{cluster_num:04d}",
            records=sorted(cluster_records, key=lambda r: r.path),
            match_category=match_category,
            pairwise_matches=edges_by_root[root],
            keeper_decision=None,
        )
        clusters.append(cluster)
        cluster_num += 1

    return clusters
