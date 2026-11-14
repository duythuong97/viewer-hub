"""``codemap_erd``: the foreign-key diagram around a table (or of a schema / system) as Mermaid, DBML or JSON."""
from __future__ import annotations

import json
from typing import Any

from viewer_hub.codemap import erd
from viewer_hub.codemap.storage import open_search
from viewer_hub.codemap.workspace import Workspace

from .tools import TOOLS, Tool, ToolError, _answer, _text

DEFAULT_TABLES = 40
FORMATS = ("mermaid", "dbml", "json")


def erd_answer(workspace: Workspace, arguments: dict[str, Any]) -> str:
    table = _text(arguments, "table", required=False, limit=300)
    schema = _text(arguments, "schema", required=False, limit=300)
    system = _text(arguments, "system", required=False, limit=300)
    fmt = _text(arguments, "format", required=False, limit=10) or "mermaid"
    if fmt not in FORMATS:
        raise ToolError("format must be mermaid, dbml or json")
    depth = arguments.get("depth", 1)
    if depth not in (1, 2, "1", "2"):
        raise ToolError("depth must be 1 or 2")
    max_tables = arguments.get("max_tables", DEFAULT_TABLES)
    if not isinstance(max_tables, int) or isinstance(max_tables, bool) or not 1 <= max_tables <= erd.MAX_TABLES:
        raise ToolError(f"max_tables must be an integer from 1 to {erd.MAX_TABLES}")
    columns = _text(arguments, "columns", required=False, limit=10) or "all"
    if columns not in {"all", "keys"}:
        raise ToolError("columns must be all or keys")
    try:
        with open_search(workspace.output) as db:
            model = erd.build(db, table=table, schema=schema, system=system, depth=int(depth), limit=max_tables)
    except erd.ErdError as exc:
        raise ToolError(exc.message) from exc
    keys_only = columns == "keys"
    tables = {item["id"]: item for item in model["tables"]}
    body = [f"## {model['summary']}"]
    if model["relations"]:
        body.append("")
        body.append("Foreign keys (child → parent):")
        for relation in model["relations"]:
            source, target = tables[relation["from_table"]], tables[relation["to_table"]]
            extras = [relation["cardinality"]]
            if relation["delete_rule"] and relation["delete_rule"] != "NO ACTION":
                extras.append(f"ON DELETE {relation['delete_rule']}")
            if relation["source"]:
                extras.append(f"from {relation['source']}")
            body.append(f"- {relation['constraint'] or '(unnamed)'}: {source['qualified_name']}.({', '.join(relation['from_columns'])}) → "
                        f"{target['qualified_name']}.({', '.join(relation['to_columns'])}) [{'; '.join(extras)}]")
    body.append("")
    if fmt == "json":
        body.extend(["```json", json.dumps(model, ensure_ascii=False), "```"])
    else:
        body.extend([f"```{fmt}", erd.render(model, fmt, keys_only=keys_only).rstrip("\n"), "```"])
    uncertain: list[str] = []
    if not model["has_fk_data"]:
        uncertain.append(f"- {erd.NO_FK_MESSAGE} (This pack has no foreign-key data: re-extract with the new code-map.)")
    if model["truncated"]:
        uncertain.append(f"- {model['omitted']} table(s) beyond max_tables={model['limit']} are not shown; "
                         "narrow with table + depth=1 or raise max_tables.")
    if model.get("outside_relations"):
        uncertain.append(f"- {model['outside_relations']} foreign key(s) of these tables point to or come from tables not shown.")
    ddl = [relation["constraint"] or relation["id"] for relation in model["relations"] if relation["source"] == "ddl"]
    if ddl:
        uncertain.append("- Parsed from DDL files, not the database catalog (may differ from the live schema): " + ", ".join(ddl[:20]))
    if model["relations"]:
        uncertain.append("- Cardinality is a guess: one-to-one only when the FK columns are the whole primary key "
                         "(unique constraints are not in the graph).")
    uncertain.append("- Only declared foreign-key constraints are shown; joins written in code without a constraint are not. "
                     "Use codemap_impact for the code that reads and writes these tables.")
    return _answer(workspace, body, uncertain, None)


ERD_TOOL = Tool(
    "codemap_erd",
    "ERD (foreign keys)",
    "Entity-relationship diagram from the database catalog: the tables linked to a table by foreign keys "
    "(depth 1-2, both directions: the tables it references and the tables that reference it), or every table of a "
    "schema or system, with columns, types, PK/FK flags, logical names (ja/en) and each FK's columns and ON DELETE "
    "rule. Use it for impact analysis of a table or column change (which child tables break, what cascades on "
    "delete), to understand a data model before writing SQL, or to give a diagram (Mermaid erDiagram by default, "
    "DBML for dbdiagram.io, or JSON).",
    {
        "type": "object",
        "properties": {
            "table": {"type": "string", "description": "Focus table: name (ORDERS), SCHEMA.TABLE, DB.SCHEMA.TABLE or node id."},
            "schema": {"type": "string", "description": "Instead of table: every table of a schema, e.g. DB1.APP."},
            "system": {"type": "string", "description": "Instead of table: every table of a system (system key)."},
            "depth": {"type": "integer", "enum": [1, 2], "description": "FK hops from the focus table (default 1)."},
            "format": {"type": "string", "enum": list(FORMATS), "description": "Diagram format (default mermaid)."},
            "columns": {"type": "string", "enum": ["all", "keys"], "description": "all columns (default) or only PK/FK columns."},
            "max_tables": {"type": "integer", "minimum": 1, "maximum": erd.MAX_TABLES,
                           "description": f"Most tables in the diagram (default {DEFAULT_TABLES})."},
        },
    },
    erd_answer,
)

TOOLS.append(ERD_TOOL)
