# ĐẶC TẢ GIẢI PHÁP KỸ THUẬT: TỐI ƯU HÓA HẠ TẦNG CODE MAP & TỔ CHỨC ĐỒ THỊ TRI THỨC ĐA HỆ THỐNG TRÊN VIEWER HUB

> **Tài liệu**: Technical Solution & Architecture Design Specification  
> **Áp dụng cho**:  
> - `code-map` (`/Volumes/thuong.pham/sources/code-map`)  
> - `viewer-hub` (`/Volumes/thuong.pham/sources/viewer-hub`)  
> **Ngữ cảnh hệ thống**: Doanh nghiệp quy mô lớn, hàng chục Repositories (Angular, .NET, Java, Oracle PL/SQL, JP1 Batch), hệ thống kế thừa sử dụng tiếng Nhật (`CP932/Shift-JIS`).

---

## MỤC LỤC
1. [Bản chất các vấn đề cốt lõi & Nguyên nhân gốc rễ](#1-bản-chất-các-vấn-đề-cốt-lõi--nguyên-nhân-gốc-rễ)
2. [Tầng 1: Tái cấu trúc Lưu trữ – Xóa bỏ DB 3GB (Thin Graph + Source On-Demand)](#2-tầng-1-tái-cấu-trúc-lưu-trữ--xóa-bỏ-db-3gb-thin-graph--source-on-demand)
3. [Tầng 2: Giải quyết đứt gãy đồ thị – Pipeline nối 2 vòng (Deterministic + AI Semantic Resolver)](#3-tầng-2-giải-quyết-đứt-gãy-đồ-thị--pipeline-nối-2-vòng-deterministic--ai-semantic-resolver)
4. [Tầng 3: Nâng cấp MCP Server thành "Graph OS" cho AI Agent](#4-tầng-3-nâng-cấp-mcp-server-thành-graph-os-cho-ai-agent)
5. [Tầng 4: Cơ chế chia sẻ & Đồng bộ nhóm Không xung đột (Git-Backed Patches)](#5-tầng-4-cơ-chế-chia-sẻ--đồng-bộ-nhóm-không-xung-đột-git-backed-patches)
6. [Tầng 5: Tái thiết kế Giao diện Viewer Hub (Data-Centric & Engineering Workbench)](#6-tầng-5-tái-thiết-kế-giao-diện-viewer-hub-data-centric--engineering-workbench)
7. [Bóc tách Addon trong Viewer Hub](#7-bóc-tách-addon-trong-viewer-hub)
8. [Kế hoạch triển khai kỹ thuật (Implementation Plan)](#8-kế-hoạch-triển-khai-kỹ-thuật-implementation-plan)

---

## 1. BẢN CHẤT CÁC VẤN ĐỀ CỐT LÕI & NGUYÊN NHÂN GỐC RỄ

### 1.1. Tại sao cơ sở dữ liệu phình to ~3GB?
Qua điều tra mã nguồn `extractor/code_tree_exporter/`, kích thước 3GB sinh ra từ 3 điểm thiết kế sai lệch:
1. **Lưu toàn bộ Abstract Syntax Tree (AST)**:
   - File `graph.sqlite` lưu trữ toàn bộ cây cú pháp chi tiết (`semantic_tree`) dưới dạng chuỗi JSON khổng lồ trong trường `nodes.properties_json`. Mỗi hàm, class, procedure có thể chiếm từ vài chục KB đến vài MB JSON.
   - Nhưng **khi Web UI và MCP truy vấn, chúng không hề cần cây AST thô này**. Chúng chỉ cần: *Tên node, loại node, file:line, và các cạnh nối*.
2. **Sao chép trùng lặp text code (Code Duplication)**:
   - Bảng `graph_evidence` nhồi nhét toàn bộ các đoạn mã nguồn (snippets) vào SQLite. Khi mã nguồn đã nằm sẵn trong các repo trên ổ cứng, việc sao chép hàng gigabytes text code vào DB là dư thừa.
3. **Bùng nổ tổ hợp đường đi luồng (`graph_paths`)**:
   - Hàm `_flows()` trong `serving_tables.py` cố gắng tính toán và ghi sẵn (precompute) toàn bộ các đường đi từ mọi màn hình/API đến mọi bảng CSDL. Trong hệ thống hàng chục repo, số lượng đường đi bùng nổ theo cấp số nhân $\to$ hàng triệu bản ghi trong `graph_paths`.

### 1.2. Tại sao đồ thị bị đứt gãy và Code Map trở nên vô dụng?
Mục đích cốt lõi của Code Map là phục vụ **Phân tích tác động (Impact Analysis)** và cung cấp ngữ cảnh cho **AI Coding Agent**. Tuy nhiên, hiện tại:
- `linker.py` chỉ dùng 6 bộ so khớp chuỗi cứng nhắc (`link_api`, `link_gateway`...).
- Trong hệ thống thực tế: URL gọi qua biến cấu hình, thủ tục gọi qua `EXECUTE IMMEDIATE`, các service giao tiếp qua Kafka hoặc chia sẻ qua CSDL.
- **Hậu quả**: Extractor không thể nối được các ranh giới này, sinh ra hàng loạt `UNRESOLVED_REFERENCE`. Đồ thị bị gãy thành các ốc đảo rời rạc. Khi kỹ sư hoặc AI hỏi: *"Sửa bảng này ảnh hưởng tới màn hình nào?"*, kết quả trả về **bị thiếu 70–80%**, khiến không ai dám tin cậy vào đồ thị.

### 1.3. Tại sao hướng đi phân loại theo "Actor" (Khách hàng, Kế toán, CSKH) là không khả thi?
- Hệ thống là tiếng Nhật, mã nguồn kế thừa (legacy). Phân quyền được lưu động trong các bảng CSDL (`USER_ROLES`, `PERMISSIONS`), code tĩnh chỉ kiểm tra token hoặc gọi hàm kiểm tra chung chung.
- Cố gắng dùng AST parser hoặc AI để "đoán" chức danh nhân sự từ code tiếng Nhật là phi thực tế, mong manh và tốn công vô ích.
- **Quy chuẩn đúng đắn**: Phải tổ chức theo **Repository / Phân hệ kỹ thuật** (đã có sẵn trong `code-map.json` / `systems.csv`) và lấy **Cơ sở dữ liệu trung tâm (Data-Centric)** làm trục liên kết.

---

## 2. TẦNG 1: TÁI CẤU TRÚC LƯU TRỮ – XÓA BỎ DB 3GB (THIN GRAPH + SOURCE ON-DEMAND)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        MÔ HÌNH LƯU TRỮ MỚI (DUNG LƯỢNG ~80MB - 150MB)                  │
└────────────────────────────────────────────────────────────────────────────────────────┘

        [1. THIN GRAPH DATABASE]                       [2. REPOSITORY SOURCE CODE]
        (File: codemap_base.sqlite)                    (Đọc trực tiếp từ ổ cứng / Git)

   ┌───────────────────────────────────┐             ┌───────────────────────────────────┐
   │ • graph_nodes (Chỉ metadata nhẹ)  │             │ • src/app/order/order.component.ts│
   │ • graph_edges (Cạnh in/out)       │             │ • Controllers/OrderController.cs  │
   │ • graph_evidence:                 │ ──────────▶ │ • schemas/APP_SALES/packages/     │
   │   (Chỉ lưu: file, line, col)      │   Pointer   └───────────────────────────────────┘
   │ • search_fts5 (FTS index nén)     │             (Chỉ đọc nội dung file khi User click
   └───────────────────────────────────┘              hoặc AI request xem code snippet)
```

### 2.1. Cắt bỏ AST thô và Tổ hợp tính sẵn
1. **Loại bỏ `graph.sqlite` khỏi gói phân phối**:
   - Sửa `viewer_hub/packs/builder.py`: Chỉ đóng gói duy nhất `codemap.sqlite` + `manifest.json`.
   - Cắt bỏ hoàn toàn bước tính trước `graph_paths` trong `serving_tables.py`. Thay vào đó, đường đi luồng sẽ được duyệt động theo thời gian thực (On-demand Graph Traversal bằng BFS/DFS). SQLite duyệt B-Tree theo ID mất chưa tới 5 mili-giây.
2. **Cơ chế Source On-Demand trong `graph_evidence`**:
   - Cấu trúc bảng `graph_evidence` mới:
     ```sql
     CREATE TABLE graph_evidence (
       evidence_id    TEXT PRIMARY KEY,
       target_id      TEXT NOT NULL,
       source_path    TEXT NOT NULL,    -- Đường dẫn tương đối trong repo
       start_line     INTEGER,
       end_line       INTEGER,
       evidence_kind  TEXT NOT NULL
       -- CẮT BỎ CỘT SNIPPET (Không lưu text code vào DB)
     );
     ```
   - Khi API `/api/snippet` hoặc MCP cần xem code: Engine mở trực tiếp file nguồn trên đĩa cứng tại `source_path`, đọc từ dòng `start_line` đến `end_line` (hỗ trợ giải mã tự động Shift-JIS / UTF-8).

### 2.2. Tối ưu hóa Tìm kiếm bằng SQLite FTS5 (`search_index.py`)
- Thay thế bảng `search_terms` (hàng triệu dòng token thủ công) bằng FTS5:
  ```sql
  CREATE VIRTUAL TABLE search_nodes_fts USING fts5(
    stable_id UNINDEXED,
    node_type,
    technical_name,
    display_name,
    qualified_name,
    tokenize = 'unicode61 remove_diacritics 2'
  );
  ```
- **Kết quả tổng hợp Tầng 1**: File SQLite phục vụ toàn bộ hệ thống giảm từ **3GB xuống còn ~100MB**.

---

## 3. TẦNG 2: GIẢI QUYẾT ĐỨT GÃY ĐỒ THỊ – PIPELINE NỐI 2 VÒNG (DETERMINISTIC + AI RESOLVER)

Không thể bắt bộ bóc tách tĩnh tự giải quyết các liên kết động. Ta nâng cấp `linker.py` thành quy trình 2 vòng độc lập:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                         PIPELINE NỐI ĐỒ THỊ 2 VÒNG (TWO-STAGE)                         │
└────────────────────────────────────────────────────────────────────────────────────────┘

  [VÒNG 1: DETERMINISTIC LINKER (Bộ nối tĩnh truyền thống - linker.py)]
  • Chạy bóc tách AST các repo.
  • Chạy 6 Resolvers tĩnh hiện tại (khớp URL chính xác, catalog DDL).
  • Thu gom toàn bộ các điểm gãy còn lại vào 2 danh sách Socket:
    1. DANH SÁCH ĐẦU RA (Egress Sockets):
       - HTTP Calls không khớp route: URL gọi, Method, tham số, file:line.
       - Message Topics được gửi (Producer).
    2. DANH SÁCH ĐẦU VÀO (Ingress Sockets):
       - Các API Controller Endpoints chưa có ai gọi tới.
       - Các Worker / Consumer lắng nghe Message.
                          │
                          ▼
  [VÒNG 2: AI SEMANTIC RESOLVER (Chạy bằng lệnh CI hoặc MCP Tool)]
  • AI nhận 2 danh sách Sockets.
  • AI quét bổ sung các file cấu hình mà AST bỏ qua:
    - File cấu hình môi trường: `environment.ts`, `appsettings.json`, `Web.config`.
    - Định nghĩa routing Gateway / CloudFormation / Nginx.
    - File mapping SQL: `SqlMap.xml`, MyBatis mapper.
  • AI tiến hành đối soát Semantic (Fuzzy URL matching + DTO field matching + Tiếng Nhật kỹ thuật):
    Ví dụ:
      - Client gọi: `POST /api/chumon/v1/toroku`
      - Backend hứng: `[HttpPost("entry")]` nằm trong `ChumonApiController.cs`
      - AI nhận diện: `注文 (Chumon)` trùng khớp; DTO `ChumonTorokuRequest` khớp 100% các trường JSON.
  • AI xuất kết quả thành các cạnh đề xuất vào file `codemap-patches/links/auto_stitched.yaml`.
```

---

## 4. TẦNG 3: NÂNG CẤP MCP SERVER THÀNH "GRAPH OS" CHO AI AGENT

MCP Server không chỉ là công cụ đọc dữ liệu thụ động. Nó phải cung cấp khả năng điều khiển và chữa lành đồ thị (Graph OS) cho các AI Agent (Copilot, Claude Code, Antigravity):

### Đặc tả 4 Công cụ MCP cốt lõi mới (`viewer_hub/codemap/mcp/write_tools.py`):

#### 1. `codemap_diagnose_flow` (Truy tìm điểm gãy của luồng)
- **Mục đích**: Cho phép AI kiểm tra tại sao từ Màn hình A không truy vết được tới Bảng CSDL B.
- **Cơ chế**: Thuật toán Bidirectional Search duyệt xuôi từ A và duyệt ngược từ B $\to$ tìm ra khoảng hở giữa 2 node gần nhất.
- **Đầu ra**: Trả về chính xác:
  ```json
  {
    "status": "broken",
    "last_reachable_node": "ui-action:portal_customer:OrderComponent:submit",
    "target_node": "table:ORACLE:APP_SALES:T_CHUMON_HD",
    "gap": {
      "reason": "URL '/api/chumon/v1/toroku' không tìm thấy Backend Route",
      "candidate_matches": [
        { "node_id": "api-operation:order_service:POST:/chumon/entry", "confidence": 0.95 }
      ]
    }
  }
  ```

#### 2. `codemap_connect` (AI nối cạnh trực tiếp vào đồ thị)
- **Mục đích**: Cho phép AI Agent tự động kết nối mắt xích sau khi đã phân tích code và file cấu hình.
- **Tham số**:
  ```json
  {
    "source_id": "ui-action:portal_customer:OrderComponent:submit",
    "target_id": "api-operation:order_service:POST:/chumon/entry",
    "edge_type": "CALLS_API",
    "confidence": 0.98,
    "reason": "Khớp controller qua routing trong appsettings.json và DTO ChumonTorokuRequest"
  }
  ```

#### 3. `codemap_create_virtual_node` (Tạo Node cho thành phần ngoài code)
- **Mục đích**: Tạo node đại diện cho các dịch vụ bên thứ ba (Cổng thanh toán, Ngân hàng, Webhook đối tác) mà repo không có source code.
- **Tham số**: `node_type` (`EXTERNAL_SYSTEM`, `MESSAGE_TOPIC`, `QUEUE`), `technical_name`, `display_name`, `description`.

#### 4. `codemap_impact_extended` (Phân tích tác động đa tầng)
- **Mục đích**: Chạy thuật toán duyệt ngược đồ thị đi qua **cả cạnh trích xuất tĩnh + cạnh do AI/User nối**.
- **Kết quả**: Báo cáo đầy đủ 100% danh sách: *Màn hình bị ảnh hưởng*, *Batch Job bị ảnh hưởng*, *API bị ảnh hưởng* khi chuẩn bị sửa đổi một bảng CSDL hoặc một DTO.

---

## 5. TẦNG 4: CƠ CHẾ CHIA SẺ & ĐỒNG BỘ NHÓM KHÔNG XUNG ĐỘT (GIT-BACKED PATCHES)

### 5.1. Bản chất vấn đề xung đột SQLite:
- SQLite là file nhị phân (Binary B-tree). Không thể commit file `.sqlite` lên Git để giải quyết xung đột bằng lệnh merge.
- Chia sẻ file nhị phân qua mạng nội bộ khiến mọi người ghi đè lẫn nhau.

### 5.2. Giải pháp: Kiến trúc "Base SQLite + Git-Backed Text Patches"

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        CƠ CHẾ ĐỒNG BỘ TRI THỨC BẰNG GIT (ZERO CONFLICT)                │
└────────────────────────────────────────────────────────────────────────────────────────┘

        [BẢN ĐỒ CODE TĨNH]                               [TRI THỨC BỔ SUNG / AI NỐI]
        (Do CI build từ mã nguồn)                        (Do Dev & AI cùng đóng góp)

    codemap_base.sqlite (~100MB)                       Thư mục Git: /codemap-patches/
    • Đẩy lên Server nội bộ / S3.                      ├── links/
    • Tải về máy cá nhân ở chế độ CHỈ ĐỌC              │   ├── portal_to_api.yaml
      (Read-only). Không ai sửa file này.              │   └── batch_jp1_flows.yaml
                                                       └── notes/
                                                           └── table_explanations.yaml
                                                                      │
                                                                      ▼
                                                               GIT PUSH / PULL
                                                    (Code Review, PR, Merge như code thường!)
```

### 5.3. Cách thức vận hành:
1. **Lưu trữ dưới dạng File Văn bản (YAML/JSON)**:
   Mọi liên kết do AI nối hoặc ghi chú do Kỹ sư viết đều được ghi thành các file YAML trong thư mục `codemap-patches/` của repo Git:
   ```yaml
   # codemap-patches/links/portal_to_api.yaml
   - link_id: lnk-chumon-toroku-001
     source_ref: "SCREEN:portal_customer:/order/entry"
     target_ref: "API:order_service:POST:/chumon/entry"
     edge_type: CALLS_API
     status: approved
     reason: "AI nối: Khớp DTO và thuật ngữ 注文 (chumon)"
     created_by: ai-agent
     approved_by: thuong.pham
   ```
2. **Chia sẻ và Merge thông qua Git**:
   - Khi Dev A hoặc AI tạo liên kết $\to$ Commit file `.yaml` lên Git.
   - Dev B chỉ cần `git pull`. Nếu 2 người cùng sửa 1 file $\to$ Git xử lý conflict văn bản trực quan qua Pull Request, **không bao giờ sợ hỏng hay ghi đè file SQLite**.
3. **Viewer Hub tự động nạp ở Runtime**:
   - Khi Viewer Hub khởi động: Hub mở file nền `codemap_base.sqlite` (read-only), sau đó quét thư mục `codemap-patches/` để nạp toàn bộ các liên kết và ghi chú vào bộ nhớ (RAM View).
   - Đồ thị luôn đảm bảo đồng bộ mới nhất với kho Git của toàn đội ngũ.

---

## 6. TẦNG 5: TÁI THIẾT KẾ GIAO DIỆN VIEWER HUB (DATA-CENTRIC & WORKBENCH)

Không sa đà vào việc vẽ sơ đồ luồng chi tiết từng hàm gây rối mắt. Giao diện được cấu trúc lại thành **3 không gian làm việc kỹ thuật**:

### 6.1. Không gian 1: Data-Centric Topology (Bản đồ CSDL Trung tâm)
- **Nguyên lý**: Lấy các Bảng CSDL chính (Core Tables) làm trục trung tâm:
  - Cột bên trái: Danh sách các Repo GHI dữ liệu vào bảng (Insert/Update Writers).
  - Cột ở giữa: Khối CSDL / Bảng (`T_CHUMON_HD`, `M_KOKYAKU`, `T_SEIKYU`).
  - Cột bên phải: Danh sách các Repo ĐỌC dữ liệu từ bảng (Select Readers / Batch Jobs).
- **Lợi ích**: Tự động 100% từ code, không cần dịch tiếng Nhật, lập tức nhìn thấy bức tranh liên thông giữa các ứng dụng.

### 6.2. Không gian 2: AI Stitcher Studio (Màn hình Đối soát Điểm gãy)
- Màn hình chuyên dụng cho Kỹ sư và Tech Lead duyệt các mối nối của AI:
  - Hiển thị danh sách các điểm đứt gãy cạnh nhau (Side-by-side): Code gọi bên trái $\leftrightarrow$ Code hứng bên phải.
  - Hộp giải thích ngữ nghĩa tiếng Nhật của AI (giải nghĩa `論理名`, đối soát DTO).
  - Nút **[✅ 1-Click Approve]** để phê duyệt đưa vào `codemap-patches/`.

### 6.3. Không gian 3: Engineering Inspector (Soi sâu từng Node)
- Khi click vào bất kỳ node nào trên đồ thị, thanh bên phải mở ra 3 tab kỹ thuật:
  - Tab 1: **Overview**: Tên kỹ thuật, tên logic tiếng Nhật (`注文ヘッダテーブル`), hệ thống sở hữu.
  - Tab 2: **Code Snippet On-Demand**: Đọc code thực tế từ đĩa cứng kèm số dòng `file:line` (hỗ trợ hiển thị đúng font tiếng Nhật CP932/Shift-JIS/UTF-8).
  - Tab 3: **Edges & AI Notes**: Toàn bộ liên kết in/out và ghi chú giải thích nghiệp vụ của AI.

---

## 7. BÓC TÁCH ADDON TRONG VIEWER HUB

Theo đúng quy chuẩn kiến trúc của Viewer Hub (`AGENTS.md` và `docs/addons.md`):

### 7.1. Phân định ranh giới giữa Core và Addon:
1. **Phần GIỮ LẠI trong Viewer Hub Core (`viewer_hub/codemap/`)**:
   - `packs.py`, `storage.py`: Bộ đọc file `codemap_base.sqlite` nền, quản lý kết nối CSDL và đọc các file patch YAML từ Git.
   - Mount route cơ bản phục vụ API cho giao diện.
2. **Phần TÁCH THÀNH ADDON (`codemap-ai-stitcher`)**:
   - Toàn bộ engine AI dò tìm điểm gãy, kết nối mô hình LLM để đối soát tiếng Nhật, suy luận DTO và sinh cạnh nối tự động.
   - Đóng gói thành một **`managed` Addon** (chạy Python trong tiến trình riêng ngoài Hub).
   - *Lợi ích*: Nếu tác vụ AI phân tích ngữ cảnh tốn nhiều RAM hoặc crash thì tiến trình chính của Viewer Hub vẫn hoạt động 100% ổn định.

---

## 8. KẾ HOẠCH TRIỂN KHAI KỸ THUẬT (IMPLEMENTATION PLAN)

```
GIAI ĐOẠN 1: GIẢI PHÓNG DUNG LƯỢNG & TỐI ƯU HIỆU NĂNG (Sprint 1)
├── 1. Sửa `packs/builder.py`: Bỏ graph.sqlite khỏi .sapack (Giảm 3GB -> 100MB)
├── 2. Bỏ precompute `graph_paths` trong `serving_tables.py`; chuyển sang on-demand BFS
├── 3. Chuyển đổi bảng tìm kiếm sang SQLite FTS5 trong `search_index.py`
└── 4. Bỏ lưu text snippet trong `graph_evidence`; chuyển sang đọc file on-demand

GIAI ĐOẠN 2: GIT-BACKED PATCHES & MỞ KHÓA MCP MUTATION (Sprint 2)
├── 1. Xây dựng module đọc/ghi thư mục `codemap-patches/` (định dạng YAML)
├── 2. Nâng cấp 4 tool MCP: `codemap_diagnose_flow`, `codemap_connect`,
│      `codemap_create_virtual_node`, `codemap_impact_extended`
└── 3. Bổ sung cơ chế Auto-healing Rebind để cạnh nối không bị mồ côi khi re-index

GIAI ĐOẠN 3: AI SEMANTIC RESOLVER & WORKBENCH UI (Sprint 3)
├── 1. Xây dựng Pipeline Vòng 2: AI Semantic Resolver tự động dò tìm và ghép cặp Socket
├── 2. Đóng gói Addon `codemap-ai-stitcher` cho Viewer Hub
└── 3. Tái cấu trúc Web UI: Data-Centric Topology + AI Review Studio + Inspector On-demand
```

---
*Tài liệu này là đặc tả kỹ thuật hoàn chỉnh thay thế toàn bộ các đề xuất sơ lược trước đó.*
