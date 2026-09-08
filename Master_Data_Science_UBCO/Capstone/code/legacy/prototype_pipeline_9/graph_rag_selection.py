"""Shared graph/RAG block-selection helpers.

The helpers here intentionally stay conservative: they add evidence only when
the document structure makes rule inheritance explicit, such as an intro clause
followed by parenthesized list items.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


GENERIC_LIST_ITEM_RE = re.compile(r"^\s*\([a-z0-9ivxlcdm]{1,5}\)\s+", re.IGNORECASE)
GENERIC_LIST_INTRO_RE = re.compile(
    r"\b(?:"
    r"must\s*:|shall\s*:|must\s+consider|must\s+comply|"
    r"subject\s+to\s+(?:the\s+)?following|following\s+(?:features|conditions|requirements)|"
    r"requirements?\s+(?:are|is|include|includes)|conditions?\s+(?:are|is|include|includes)|"
    r"as\s+follows\s*:|before\s+granting|may\s+(?:project|vary|be varied)"
    r")\b",
    re.IGNORECASE,
)


def _section_key(node: dict[str, Any]) -> str:
    section_path = node.get("section_path") or []
    if section_path:
        return " > ".join(str(part).strip() for part in section_path if str(part).strip())
    return str(node.get("parent_context") or "").strip()


def add_list_continuation_closure(
    nodes: list[dict[str, Any]],
    selected_ids: set[str],
    *,
    order_key: str,
    heading_roles: set[str] | None = None,
) -> set[str]:
    """Add sibling list items that inherit a selected/explicit rule intro.

    A common zoning pattern is:

    ``The authority must consider:`` followed by ``(a)``, ``(b)``, ``(i)`` items.
    Those child items may not contain modal verbs or numeric units, but they are
    still part of the operative rule. This function adds those child items only
    inside a same-page list group with an explicit intro.
    """

    heading_roles = heading_roles or {"scope_heading"}
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        by_page[int(node["page_number"])].append(node)

    added: set[str] = set()
    for page_nodes in by_page.values():
        page_nodes.sort(key=lambda row: int(row.get(order_key, 0)))
        active_intro: dict[str, Any] | None = None
        active_items: list[dict[str, Any]] = []
        saw_list_item = False

        def flush_group() -> None:
            nonlocal active_intro, active_items, saw_list_item
            if not active_intro or not active_items:
                active_intro = None
                active_items = []
                saw_list_item = False
                return

            intro_selected = active_intro["block_id"] in selected_ids
            group_has_selected_item = any(item["block_id"] in selected_ids for item in active_items)
            if intro_selected or group_has_selected_item:
                for item in active_items:
                    if not item.get("is_junk"):
                        added.add(item["block_id"])
                        selected_ids.add(item["block_id"])
                if group_has_selected_item and active_intro.get("block_id") and not active_intro.get("is_junk"):
                    selected_ids.add(active_intro["block_id"])

            active_intro = None
            active_items = []
            saw_list_item = False

        for node in page_nodes:
            if node.get("is_junk"):
                continue

            role = node.get("graph_role", "")
            if role in heading_roles and active_intro is not None:
                flush_group()

            text = str(node.get("text_compact") or node.get("text") or "")
            is_intro = bool(GENERIC_LIST_INTRO_RE.search(text))
            is_item = bool(GENERIC_LIST_ITEM_RE.match(text))
            node_section = _section_key(node)

            if is_intro:
                flush_group()
                active_intro = node
                active_items = []
                saw_list_item = False
                continue

            if active_intro is None:
                continue

            intro_section = _section_key(active_intro)
            same_section = not intro_section or not node_section or node_section == intro_section
            if is_item and same_section:
                active_items.append(node)
                saw_list_item = True
                continue

            if saw_list_item:
                flush_group()

        flush_group()

    return added
