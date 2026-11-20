"""Copied from code-map extractor/code_tree_exporter/contract/addresses.py.

Node addresses: the short, readable name people and AI write for a node, the same in every reader.

``<system> › <type> › <full name>``, e.g. ``order-api › method › Shop.Data.OrderRepository.Save``. The full name is
the name people use for the code (namespace, class, package), never its file, line or project, so the address
survives moving code between files. The parameter list is added only when the name has overloads; what is still the
same after that gets ``#2``, ``#3`` (and an ``ADDRESS_DUPLICATE`` issue: two nodes for one piece of code).

``serving.py`` stores one address per node in ``graph_node_addresses``. Viewer Hub keeps a copy of this file
(``viewer_hub/codemap/contract/addresses.py``) and computes the same addresses for packs built before the table
existed; change both together.

Columns are left out: they are reached through their table.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

SEPARATOR = " › "

# The short type keys of refs (``table: ORDER_HEADER``) and addresses.
REF_KEYS = {
    "SCREEN": "screen", "UI_ACTION": "ui_action", "API_CALL_REFERENCE": "api_call", "API_OPERATION": "api",
    "METHOD": "method", "LOCAL_ROUTINE": "method", "CONTROLLER": "controller", "SERVICE": "service",
    "REPOSITORY": "repository", "PROCEDURE": "procedure", "FUNCTION": "function", "TRIGGER": "trigger",
    "PLSQL_PACKAGE": "package", "SQL_FILE": "sql_file", "INLINE_SQL": "sql", "TABLE": "table", "VIEW": "view",
    "MATERIALIZED_VIEW": "view", "EXTERNAL_DATABASE_OBJECT": "external", "EXTERNAL_API_OPERATION": "external_api",
    "JOB_NETWORK": "jobnet", "JOB": "job", "EXECUTABLE": "executable", "COMMAND_MODE": "command",
    "UNRESOLVED_REFERENCE": "unresolved",
}
DATABASE_TYPES = frozenset({"TABLE", "VIEW", "MATERIALIZED_VIEW", "COLUMN", "SEQUENCE", "SYNONYM", "PROCEDURE", "FUNCTION",
                            "TRIGGER", "PLSQL_PACKAGE", "DATABASE", "DATABASE_SCHEMA", "INLINE_SQL", "SQL_FILE"})
JOB_TYPES = frozenset({"JOB_NETWORK", "JOB"})
_PARAMS = re.compile(r"^(.*?)(\(.*\))?$", re.S)


def type_key(node_type: str) -> str:
    return REF_KEYS.get(node_type, node_type.lower())


def system_of(node_type: str, system_key: str | None, database_key: str | None, repository_key: str | None) -> str:
    """The system a node runs in: the database for DB objects, the repository for code."""
    if node_type in JOB_TYPES:
        return "Jobnet"
    if node_type in {"EXTERNAL_DATABASE_OBJECT", "DATABASE_LINK"}:
        return database_key or "Hệ thống ngoài"
    if node_type in {"EXTERNAL_API_OPERATION", "EXTERNAL_SYSTEM"}:
        return system_key or "Hệ thống ngoài"
    if node_type == "UNRESOLVED_REFERENCE":
        # A table or routine nobody resolved still lives in the database it was referenced from.
        return database_key if database_key and database_key not in {"DEFERRED", "UNKNOWN"} else "Chưa xác định"
    if node_type in DATABASE_TYPES and database_key:
        return database_key
    return repository_key or system_key or database_key or "Khác"


def owner_of(node_type: str, system_key: str | None, database_key: str | None, repository_key: str | None) -> str:
    """The system that owns the code (tree grouping): routines and SQL files sit with their repository."""
    return system_key or repository_key or database_key or ("Jobnet" if node_type in JOB_TYPES else "Khác")


def ref_name(node: dict[str, Any]) -> str:
    """The name a document uses for a node: Class.method for code, the technical name otherwise."""
    technical = node["technical_name"]
    if node["node_type"] in {"METHOD", "LOCAL_ROUTINE", "UI_ACTION", "PROCEDURE", "FUNCTION"} and "." not in technical:
        parts = [part for part in re.split(r"[.:]", node["qualified_name"]) if part]
        if len(parts) >= 2 and parts[-1] == technical and not parts[-2].lower() in {"cs", "ts", "sql", "js"}:
            return f"{parts[-2]}.{technical}"
    return technical or node["display_name"]


def full_name(node: dict[str, Any]) -> tuple[str, str]:
    """(full name without parameters, parameter list or "") of a node."""
    qualified = node["qualified_name"] or ""
    if "|M:" in qualified:  # .NET method: Project.csproj|global::Ns.Class|M:Ns.Class.Method(Type)
        name = qualified.split("|M:", 1)[1]
    elif "|global::" in qualified:  # .NET type
        name = qualified.split("|global::", 1)[1]
    elif node["node_type"] in {"API_OPERATION", "API_CALL_REFERENCE", "SCREEN", "UI_ACTION", "METHOD", "LOCAL_ROUTINE"} \
            or not qualified:
        name = ref_name(node)
    else:
        name = qualified
        for prefix in {node.get("system", ""), node.get("owner", "")}:  # DB1.PKG.PROC, app.AppComponent
            if prefix and name.upper().startswith(prefix.upper() + "."):
                name = name[len(prefix) + 1:]
                break
        head, _, rest = name.partition(".")
        if rest and re.search(r"[-/\\]", head):  # a source name (angular-web.AppComponent), never part of code
            name = rest
    match = _PARAMS.match(name.strip())
    return (match.group(1) or name).strip(), (match.group(2) or "").strip()


def node_view(node_id: str, node_type: str, technical_name: str | None, qualified_name: str | None,
              display_name: str | None, system_key: str | None, database_key: str | None,
              repository_key: str | None) -> dict[str, Any]:
    """A ``graph_nodes`` row as the functions above read it."""
    return {
        "node_id": node_id, "node_type": node_type, "technical_name": technical_name or "",
        "qualified_name": qualified_name or "", "display_name": display_name or technical_name or node_id,
        "system": system_of(node_type, system_key, database_key, repository_key),
        "owner": owner_of(node_type, system_key, database_key, repository_key),
    }


def assign(nodes: Iterable[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Address of every node, unique, and the nodes that needed a ``#n`` (same system, type, name and parameters):
    {address without the number: node ids}."""
    full: dict[str, tuple[str, str]] = {}
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for node in nodes:
        full[node["node_id"]] = full_name(node)
        groups.setdefault((node["system"], node["node_type"], full[node["node_id"]][0].lower()), []).append(node)
    addresses: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for (system, node_type, _), members in groups.items():
        seen: dict[str, list[str]] = {}
        for node in sorted(members, key=lambda node: (full[node["node_id"]][1], node["node_id"])):
            name, params = full[node["node_id"]]
            if len(members) > 1:  # overloads keep their parameter list; what is still the same gets #2, #3
                name += params
                seen.setdefault(name, []).append(node["node_id"])
                if len(seen[name]) > 1:
                    name += f" #{len(seen[name])}"
            addresses[node["node_id"]] = SEPARATOR.join((system, type_key(node_type), name))
        for name, ids in seen.items():
            if len(ids) > 1:
                duplicates[SEPARATOR.join((system, type_key(node_type), name))] = ids
    return addresses, duplicates
