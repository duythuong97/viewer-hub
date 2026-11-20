"""Business rules and operational facts for the nodes of an answer ([R…])."""
from __future__ import annotations

import sqlite3

from viewer_hub.codemap import knowledge

from .business_view import knowledge_sections

STATUS = {
    "approved": "in use",
    "draft": "in use",  # a knowledge db not upgraded yet (read-only hub)
    "needs_review": "CODE CHANGED since it was written",
    "retired": "retired",
}
SOURCE = {"ai": "written by AI", "sme": "written by a person", "doc": "from a document", "code": "from the code"}


def _cited(node_ids: list[str], labels: dict[str, str]) -> str:
    cited = [labels[node] for node in node_ids if node in labels]
    return f" | nodes: {', '.join(cited)}" if cited else ""


def _touching(items: list[dict], stable_ids: set[str]) -> list[dict]:
    return [item for item in items if stable_ids & set(item.get("node_ids") or [])]


def rules_section(db: sqlite3.Connection, stable_ids: list[str], labels: dict[str, str]) -> list[str]:
    if not knowledge.has_table(db, "biz_rules", "kn"):
        return []
    knowledge.revalidate(db, knowledge.graph_stamp(db))
    wanted = set(stable_ids)
    rules = [rule for rule in _touching(knowledge.list_rules(db), wanted) if rule["status"] != "retired"]
    lines: list[str] = []
    if rules:
        lines.append("## Business rules (knowledge base)")
        order = {"approved": 0, "draft": 0, "needs_review": 1}
        for index, rule in enumerate(sorted(rules, key=lambda item: (order.get(item["status"], 3), item["rule_id"])), start=1):
            state = STATUS.get(rule["status"], rule["status"])
            state += f", {SOURCE.get(rule.get('source'), rule.get('source'))}"
            if rule["status"] == "needs_review" and rule.get("review_reason"):
                state += f": {rule['review_reason']}"
            evidence = rule.get("evidence") or "no evidence"
            lines.append(
                f"[R{index}] {rule['rule_id']} ({state}) {rule['title']}"
                + (f" — {' '.join(rule['text'].split())[:300]}" if rule.get("text") else "")
                + f" | evidence: {evidence}{_cited(rule.get('node_ids') or [], labels)}"
            )
    facts = knowledge.ops_facts(db, stable_ids)
    if facts:
        lines.append("## Operational facts (ops-facts.csv)")
        for fact in facts:
            lines.append(
                f"- {labels.get(fact['node_id'], '')} {fact['target']} {fact['kind']}: {fact['value']}"
                + (f" ({fact['note']})" if fact.get("note") else "")
            )
    return ["", *lines] if lines else []


def uncertain_lines(db: sqlite3.Connection | None, stable_ids: list[str]) -> list[str]:
    if db is None or not knowledge.has_table(db, "biz_rules", "kn"):
        return []
    wanted = set(stable_ids)
    lines = []
    review = [rule["rule_id"] for rule in _touching(knowledge.list_rules(db, status="needs_review"), wanted)]
    if review:
        lines.append(f"- Rules whose code changed since they were written (check the code before relying on them): {', '.join(review)}")
    return lines


knowledge_sections.append(rules_section)
