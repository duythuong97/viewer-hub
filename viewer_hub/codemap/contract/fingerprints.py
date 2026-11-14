"""Combined behaviour fingerprint, from code-map extractor/code_tree_exporter/fingerprints.py.

The extract stores one fingerprint per node (graph_fingerprints); rules and
approved documentation keep ``combined()`` of the nodes they describe, and go back
to review when a later pack gives a different value.
"""
from __future__ import annotations

import hashlib
from typing import Iterable


def combined(fingerprints: dict[str, str], node_ids: Iterable[str]) -> str:
    """One fingerprint for a set of nodes (a rule, an approved document part); MISSING marks a deleted node."""
    parts = sorted(f"{node_id}={fingerprints.get(node_id, 'MISSING')}" for node_id in set(node_ids))
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:20]
