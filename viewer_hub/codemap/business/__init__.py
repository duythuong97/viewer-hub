"""Business layer over the graph: menus, features, flows and their documents.

The tree is derived from the graph on every request so it follows the latest
extract:

* every ``SCREEN`` (Angular route) is a feature, grouped into a menu by the
  first segment of its route;
* every ``JOB_NETWORK`` (jobnet.csv) is a feature in the "Chạy nền" menu;
* a feature proposes one flow per ``UI_ACTION`` (screen) or ``JOB`` (jobnet);
* ``API_OPERATION`` nodes no feature reaches are listed as unassigned entry
  points.

What people change (names, descriptions, review status, flow documents written
by AI and edited by hand) is kept in the knowledge database (``kn.biz_*``) and
keyed by graph ids, so the next extract does not overwrite it.

AI never sees the code directly. ``export_pack`` writes one YAML file per
feature with the feature's nodes, edges, code evidence and a template to fill;
``check_import``/``apply_import`` read the file the AI returns, check every node
reference against the graph and keep reviewed parts untouched.

Ported from code-map codemap/business.py (read side; writes go to the user's knowledge db only). Modules:
common (limits, schema, errors), graph (GraphIndex), tree, flows, edits, ai_exchange (AI export/import),
search, links (manual edges), data (a feature's tables and CRUD matrix, who uses a table).
"""
from __future__ import annotations

from .common import (  # noqa: F401
    BusinessError, CONDITION_KINDS, DATA_TYPES, INSTRUCTIONS, KNOWLEDGE_SCHEMA, LINK_CALL_TYPES,
    LINK_DATA_TYPES, LINK_STATUSES, LINK_TYPES, MAX_CONDITIONS_PER_NODE, MAX_EVIDENCE_CHARS, MAX_FEATURE_NODES,
    MAX_FLOW_NODES, MAX_UNASSIGNED, REF_KEYS, RULE_STATUSES, STRANDED_MENU, TERMINAL_TYPES, UNSORTED_MENU, _now,
)
from .graph import (  # noqa: F401
    DATABASE_TYPES, GraphIndex, JOB_TYPES, MAX_CACHED_INDEXES, apply_links, feature_labels, graph_hash,
    graph_index, ref_name, ref_of, screen_actions, system_of,
)
from .tree import (  # noqa: F401
    ENTRY_FEATURE_TYPES, TREE_GROUPS, build_tree, find_item,
)
from .flows import (  # noqa: F401
    feature_detail, load_flow, node_facts, semantic_levels, skeleton, system_level,
)
from .edits import (  # noqa: F401
    answer_question, update_item, update_part,
)
from .ai_exchange import (  # noqa: F401
    MAX_TRACE_LINES, apply_import, check_import, export_pack, flow_document, flow_trace, propose_flow,
)
from .data import (  # noqa: F401
    CRUD, MAX_DATA_TABLES, TABLE_TYPES, feature_data, table_usage,
)
from .search import (  # noqa: F401
    node_flows, node_page, search, search_nodes,
)
