"""Stage E dedup: same business scraped from overlapping grid cells / category
queries gets merged. Primary key is normalized phone number; fuzzy business
name match (difflib, stdlib -- no extra dependency) catches cases where the
phone differs or is missing (multiple lines, typos, differently formatted).
"""
from __future__ import annotations

import difflib
import re
from typing import Any

_SUFFIXES = {
    "ltd", "limited", "plc", "nigeria", "ng", "enterprise", "enterprises",
    "co", "company", "the", "&",
}
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    lowered = name.strip().lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    tokens = [t for t in _WS_RE.split(no_punct) if t and t not in _SUFFIXES]
    return " ".join(tokens)


def name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


class _UnionFind:
    def __init__(self, items: list[int]):
        self.parent = {i: i for i in items}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def dedup_leads(leads: list[dict[str, Any]], name_threshold: float = 0.85, review_threshold: float = 0.70) -> list[dict[str, Any]]:
    """Mutates and returns `leads` with dedup_group_id / is_duplicate / dedup_review set.

    leads: dicts with at least 'id', 'normalized_name', 'phone_normalized', 'city'.
    Within a group, the first-seen lead (lowest id) is kept as canonical
    (is_duplicate=0); the rest are marked is_duplicate=1.
    """
    if not leads:
        return leads

    uf = _UnionFind([lead["id"] for lead in leads])

    # Pass 1: exact phone match -> same business, high confidence merge.
    by_phone: dict[str, list[int]] = {}
    for lead in leads:
        phone = lead.get("phone_normalized")
        if phone:
            by_phone.setdefault(phone, []).append(lead["id"])
    for ids in by_phone.values():
        for other in ids[1:]:
            uf.union(ids[0], other)

    # Pass 2: fuzzy name match, blocked by (city, first token) to avoid an
    # O(n^2) scan across the whole dataset once this scales past a pilot.
    blocks: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lead in leads:
        norm = lead.get("normalized_name") or normalize_name(lead.get("business_name"))
        first_token = norm.split(" ", 1)[0] if norm else ""
        key = (lead.get("city") or "", first_token)
        blocks.setdefault(key, []).append(lead)

    borderline_pairs: list[tuple[int, int, float]] = []
    for block_leads in blocks.values():
        for i in range(len(block_leads)):
            for j in range(i + 1, len(block_leads)):
                a, b = block_leads[i], block_leads[j]
                ratio = name_similarity(a.get("normalized_name", ""), b.get("normalized_name", ""))
                if ratio >= name_threshold:
                    uf.union(a["id"], b["id"])
                elif ratio >= review_threshold:
                    borderline_pairs.append((a["id"], b["id"], ratio))

    # Assign group ids + canonical/duplicate flags (lowest id per group wins).
    groups: dict[int, list[int]] = {}
    for lead in leads:
        root = uf.find(lead["id"])
        groups.setdefault(root, []).append(lead["id"])

    borderline_ids = {i for pair in borderline_pairs for i in pair[:2]}
    id_to_lead = {lead["id"]: lead for lead in leads}
    for root, ids in groups.items():
        canonical_id = min(ids)
        group_id = f"grp_{canonical_id}"
        for lid in ids:
            lead = id_to_lead[lid]
            lead["dedup_group_id"] = group_id
            lead["is_duplicate"] = 0 if lid == canonical_id else 1
            lead["dedup_review"] = 1 if lid in borderline_ids else lead.get("dedup_review", 0)

    return leads
