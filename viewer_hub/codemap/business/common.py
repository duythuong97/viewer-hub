"""Shared pieces of the business layer: limits, vocabulary, the knowledge schema, errors, YAML helpers."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import yaml



RULE_STATUSES = ("ok", "warn", "bad")
UNSORTED_MENU = "menu:unsorted"
STRANDED_MENU = "menu:stranded"
MAX_FLOW_NODES = 150
MAX_FEATURE_NODES = 400
MAX_UNASSIGNED = 300
MAX_EVIDENCE_CHARS = 600
MAX_CONDITIONS_PER_NODE = 12

DATA_TYPES = frozenset({"TABLE", "VIEW", "MATERIALIZED_VIEW", "COLUMN", "EXTERNAL_DATABASE_OBJECT", "SEQUENCE", "DATA_FILE"})
TERMINAL_TYPES = DATA_TYPES | {"EXTERNAL_API_OPERATION", "UNRESOLVED_REFERENCE", "EXTERNAL_SYSTEM"}
CONDITION_KINDS = frozenset({"branch", "case", "catch", "raise", "loop", "try"})

# Short keys used in YAML node references ("api: POST /api/orders").
REF_KEYS = {
    "SCREEN": "screen", "UI_ACTION": "ui_action", "API_CALL_REFERENCE": "api_call", "API_OPERATION": "api",
    "METHOD": "method", "LOCAL_ROUTINE": "method", "CONTROLLER": "controller", "SERVICE": "service",
    "REPOSITORY": "repository", "PROCEDURE": "procedure", "FUNCTION": "function", "TRIGGER": "trigger",
    "PLSQL_PACKAGE": "package", "SQL_FILE": "sql_file", "INLINE_SQL": "sql", "TABLE": "table", "VIEW": "view",
    "MATERIALIZED_VIEW": "view", "EXTERNAL_DATABASE_OBJECT": "external", "EXTERNAL_API_OPERATION": "external_api",
    "JOB_NETWORK": "jobnet", "JOB": "job", "EXECUTABLE": "executable", "COMMAND_MODE": "command",
    "UNRESOLVED_REFERENCE": "unresolved",
}

INSTRUCTIONS = """\
Bạn là chuyên viên phân tích nghiệp vụ (BA) kiêm lập trình viên. Nhiệm vụ: viết tài liệu **luồng nghiệp vụ** cho
một tính năng, dựa hoàn toàn vào phần "Dữ liệu" (khối YAML `context`) ở cuối file. Bạn không có quyền truy cập
code hay database nào khác. Kết quả trả về đúng khối YAML ở phần "Định dạng trả về".

Một luồng tốt đọc như một câu chuyện: **ai** bắt đầu việc gì → hệ thống **kiểm tra** gì → **ghi/đọc** dữ liệu
nào → người dùng **nhận được** gì. Mỗi bước là một việc nghiệp vụ, không phải một tầng kỹ thuật.

# Dữ liệu bạn có
- `context.feature`: tên, route/jobnet, điểm vào và mô tả hiện có của tính năng.
- `context.traces`: **thứ tự gọi** của từng luồng, đi từ điểm vào theo chiều sâu. Mỗi dòng
  `1.2.1 LOẠI_CẠNH → loại: tên`; số càng dài là càng sâu (1.2.1 do 1.2 gọi). `(đã có ở 1.1)` là node đã
  xuất hiện trước đó; `[liên kết tay]` là cạnh do người thêm vào. **Đây là xương sống để dựng luồng.**
- `context.nodes`: các node code. `ref` có dạng `loại: tên` (vd `api: POST /api/orders`,
  `method: OrderController.Create`, `procedure: PKG_ORDER.CREATE_ORDER`, `table: ORDER_HEADER`).
  Có thể kèm `file` (file:dòng), `term` (thuật ngữ nghiệp vụ đã duyệt), `ja`/`en` (tên tiếng Nhật/Anh),
  `conditions` (nhánh IF/CASE/EXCEPTION/RAISE trong code kèm dòng) và `comments` (comment trong code).
- `context.edges`: `[nguồn, loại cạnh, đích]`. CALLS/CALLS_API/HANDLED_BY = gọi; INSERTS/UPDATES/DELETES/
  MERGES = ghi bảng; READS/REMOTE_READS = đọc bảng (REMOTE qua DB link). Phần tử thứ 4 `tay` = liên kết do người thêm.
- `context.evidence`: đoạn code thật của một số node, kèm vị trí `at` (file:dòng).
- `context.answered`: câu hỏi người dùng đã trả lời. Coi là sự thật, không hỏi lại.

# Cách làm (theo thứ tự)
1. Đọc `traces` của luồng, đánh dấu: điểm người dùng/batch bắt đầu, chỗ gọi sang hệ thống khác (API, DB link),
   chỗ kiểm tra (`conditions`, procedure tên VALIDATE/CHECK…), chỗ ghi dữ liệu (INSERTS/UPDATES/DELETES/MERGES).
2. Chia luồng thành **3–8 bước nghiệp vụ** theo thứ tự trong trace. Ranh giới bước thường là: đổi người/hệ thống
   thực hiện, xong một lần kiểm tra, hoặc một lần ghi dữ liệu có ý nghĩa nghiệp vụ.
3. Gán cho mỗi bước các node thực hiện nó (`nodes`, ghi đúng `ref`). Node hạ tầng (logger, mapper, DTO…) có thể
   bỏ ra ngoài. Một node chỉ nằm ở một bước.
4. Viết `text` của bước theo thứ tự xảy ra, nói rõ dữ liệu vào/ra và bảng được ghi/đọc; trích dẫn `[[tên]]`.
5. Rút quy tắc nghiệp vụ từ `conditions`/`evidence`/`comments` thành `rules`; điều chưa chắc đưa vào `questions`.
6. Viết `summary` sau cùng: ai làm, để làm gì, kết quả, và luồng này **không** bao gồm việc gì.
7. Nếu trace bị đứt (node `unresolved: …`, gọi qua tên động, job chạy theo cấu hình, comment nói gọi X mà không có
   cạnh) và bạn thấy rõ đích trong `nodes`/`evidence`, đề xuất cạnh còn thiếu trong `links`. Người dùng sẽ duyệt.

# Các trường cần điền
- `name` của flow: động từ + đối tượng nghiệp vụ (vd "Tạo đơn hàng"), không dùng tên kỹ thuật.
- `summary.text`: 1–3 đoạn.
- `steps[]` — mỗi bước:
  - `id`: giữ id cũ nếu bước vẫn là bước đó; bước mới thì để trống `""`.
  - `nodes`: danh sách `ref` của node thuộc bước (lấy từ `context.nodes`).
  - `name`: việc ở bước này theo góc nhìn nghiệp vụ (vd "Kiểm tra dòng đơn và tính tiền").
  - `actor`: người hoặc hệ thống thực hiện (vd "Nhân viên bán hàng", "Hệ thống đơn hàng", "Batch hằng đêm").
  - `text`: 1–3 đoạn. Trích dẫn node bằng `[[tên]]`.
  - `rules`: mỗi rule gồm `title` (câu khẳng định, vd "Đơn mới luôn ở trạng thái PENDING"), `at` (tên node chứa
    điều kiện), `evidence` (file:dòng lấy từ context), `status` và `text` (giải thích, nêu khi không đạt thì sao).
    `status`: `ok` = code làm đúng; `warn` = có dấu hiệu nhưng chưa chắc (vd chỉ thấy trong comment);
    `bad` = ý đồ và code lệch nhau (vd thủ tục kiểm tra có thân rỗng).
- `edge_cases.items`: trường hợp đặc biệt/lỗi suy ra từ code (dữ liệu rỗng, ngoại lệ, DB link lỗi …), mỗi mục một câu.
- `questions`: điều code không đủ để kết luận; trả lời được bằng có/không hoặc một giá trị cụ thể.
- `links` (cuối file, có thể để `[]`): cạnh còn thiếu, mỗi mục `from` (ref node nguồn), `type` (CALLS, CALLS_API,
  TRIGGERS, TRIGGERS_JOB, READS, INSERTS, UPDATES, DELETES, MERGES), `to` (ref node đích), `why` (một câu) và
  `evidence` (file:dòng nếu có).

# Quy tắc bắt buộc
1. Không sửa phần có `locked: true` (người đã duyệt hoặc sửa tay); đọc để hiểu ngữ cảnh. Nếu luồng có bước
   `locked`, giữ nguyên số bước, `id` và `nodes` của mọi bước, chỉ điền phần trống.
2. Không sửa `export`. Giữ nguyên `id` của flow.
3. Trích dẫn node bằng `[[tên]]`, `tên` là phần sau dấu `:` của một `ref` trong `context.nodes`
   (vd `[[PKG_ORDER.CREATE_ORDER]]`). Không bịa tên bảng/hàm; `nodes` và `links` cũng chỉ dùng `ref` có thật.
4. Không khẳng định điều không có trong context. Chỗ nào không chắc, viết thành một câu trong `questions`.
5. Rule nào không có `evidence` sẽ bị đánh dấu "Cần xác nhận"; đừng bịa vị trí.
6. Viết tiếng Việt, câu ngắn, chủ động. Giữ nguyên tên kỹ thuật (bảng, API, giá trị như 'PENDING').
   Các đoạn cách nhau bằng một dòng trống; có thể dùng **đậm** và `code`.
7. Chỉ trả về MỘT khối YAML hợp lệ: khối ở phần "Định dạng trả về" (`export`, `flows`, `links`) đã điền, cùng cấu
   trúc. Không chép lại `context` hay hướng dẫn, không thêm lời giải thích ngoài YAML. Dùng `|` cho đoạn nhiều dòng.

# Kiểm tra trước khi trả
- Đọc lần lượt `name` các bước: có thành một câu chuyện liền mạch từ lúc bắt đầu tới kết quả không?
- Mỗi bảng bị ghi (INSERTS/UPDATES/DELETES/MERGES) trong trace đã được nhắc ở một bước chưa?
- Mọi `[[tên]]`, `nodes`, `at`, `links` đều có trong `context.nodes`?

# Ví dụ (rút gọn)
Trace:
  1 ui_action: Lưu đơn
  1.1 CALLS_API → api: POST /api/orders
  1.1.1 HANDLED_BY → method: OrderController.Create
  1.1.1.1 CALLS → procedure: PKG_ORDER.CREATE_ORDER
  1.1.1.1.1 CALLS → procedure: PKG_ORDER.VALIDATE_LINES
  1.1.1.1.2 INSERTS → table: ORDER_HEADER
  1.1.1.1.3 INSERTS → table: ORDER_LINE
Kết quả:
flows:
- id: f1
  name: Tạo đơn hàng
  summary:
    text: |
      Nhân viên bán hàng nhập đơn trên màn hình và bấm Lưu. Hệ thống kiểm tra dòng hàng rồi tạo đơn ở trạng thái
      chờ duyệt. Luồng này không gồm việc duyệt hay xuất kho.
  steps:
  - id: s1
    nodes: ["ui_action: Lưu đơn", "api: POST /api/orders", "method: OrderController.Create"]
    name: Gửi đơn hàng
    actor: Nhân viên bán hàng
    text: |
      Nhân viên bấm [[Lưu đơn]]; màn hình gửi đơn tới [[POST /api/orders]], [[OrderController.Create]] nhận yêu cầu.
    rules: []
  - id: ""
    nodes: ["procedure: PKG_ORDER.CREATE_ORDER", "procedure: PKG_ORDER.VALIDATE_LINES"]
    name: Kiểm tra dòng đơn
    actor: Hệ thống đơn hàng
    text: |
      [[PKG_ORDER.CREATE_ORDER]] gọi [[PKG_ORDER.VALIDATE_LINES]] để kiểm tra từng dòng trước khi ghi.
    rules:
    - title: Dòng đơn phải hợp lệ trước khi tạo đơn
      at: PKG_ORDER.VALIDATE_LINES
      evidence: order-db/order_flow.sql:62
      status: bad
      text: Thân procedure chỉ có NULL nên không dòng nào bị từ chối.
  - id: ""
    nodes: ["table: ORDER_HEADER", "table: ORDER_LINE"]
    name: Lưu đơn ở trạng thái chờ duyệt
    actor: Hệ thống đơn hàng
    text: |
      Đơn được ghi vào [[ORDER_HEADER]] và các dòng vào [[ORDER_LINE]].
    rules: []
  edge_cases:
    items: []
  questions: []
links: []
"""



class _BlockDumper(yaml.SafeDumper):
    """Multi-line text (instructions, paragraphs) is written as a readable `|` block."""


def _str_block(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_BlockDumper.add_representer(str, _str_block)

KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS kn.biz_items(item_id TEXT PRIMARY KEY,parent_id TEXT,name TEXT,description TEXT,
  status TEXT CHECK(status IS NULL OR status IN('ai','edited','approved')),reviewed_by TEXT,sort_order INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS kn.biz_flows(flow_id TEXT PRIMARY KEY,feature_id TEXT NOT NULL,doc_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS kn.biz_exports(export_id TEXT PRIMARY KEY,feature_id TEXT NOT NULL,graph_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
-- Edges a person or an AI adds where the extract found none: dynamic calls, config-driven jobs,
-- a screen that reaches an API through a helper the parser does not follow. Every link is walked like
-- graph edges; refs keep a readable name so a link can be matched again after a re-extract renames an id.
CREATE TABLE IF NOT EXISTS kn.biz_links(link_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,target_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',status TEXT NOT NULL CHECK(status IN('approved','proposed')),
  origin TEXT NOT NULL DEFAULT 'user' CHECK(origin IN('user','ai')),source_ref TEXT NOT NULL DEFAULT '',
  target_ref TEXT NOT NULL DEFAULT '',created_by TEXT NOT NULL DEFAULT '',approved_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS kn.biz_links_source ON biz_links(source_id);
CREATE INDEX IF NOT EXISTS kn.biz_links_target ON biz_links(target_id);
-- An end of a link that was found again by its name after a re-extract changed the node id (code moved,
-- renamed, a parameter added). Kept until a person confirms the link still holds.
CREATE TABLE IF NOT EXISTS kn.biz_link_moves(link_id TEXT NOT NULL,side TEXT NOT NULL CHECK(side IN('source','target')),
  old_id TEXT NOT NULL,old_ref TEXT NOT NULL DEFAULT '',new_id TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '',
  moved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(link_id,side));
"""

# Edge types a person can add by hand: calls along a flow, and reads/writes of data.
LINK_CALL_TYPES = ("CALLS", "CALLS_API", "HANDLED_BY", "TRIGGERS", "TRIGGERS_JOB", "PUBLISHES", "CONSUMED_BY", "RENDERS")
LINK_DATA_TYPES = ("READS", "INSERTS", "UPDATES", "DELETES", "MERGES")
LINK_TYPES = LINK_CALL_TYPES + LINK_DATA_TYPES
LINK_STATUSES = ("approved", "proposed")


class BusinessError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback
