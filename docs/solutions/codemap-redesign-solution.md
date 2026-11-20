# Code Map v3: hệ thống hoá knowledge domain cho AI, chẩn đoán điểm gãy từ máy PROD

> **Phiên bản**: v3 (2026-11-19). Bản đầu giữ ở `codemap-redesign-solution.v1.md`.
> Thay đổi so với v2: ERD tách thành addon; bỏ phần xuất bản / duyệt cho reviewer; thêm bộ tool MCP để AI tài liệu
> (Copilot Studio) tạo knowledge (mục 8); thêm thiết kế chẩn đoán nguyên nhân
> không nối được, vì pack trên máy PROD không mang ra ngoài được.
> **Áp dụng cho**: `viewer-hub` (`viewer_hub/codemap/`, `web/src/modules/codemap/`, addon mới `erd`) và `code-map`
> (`extractor/code_tree_exporter/`, `codemap/diagnose.py`).
> **Bối cảnh**: hàng chục repo (Angular, .NET, Java, Oracle PL/SQL, JP1), hệ thống kế thừa tiếng Nhật (CP932/Shift-JIS),
> máy công ty scan bảo mật chặt (`docs/GUIDELINE.md` §5).

---

## 0. Mục tiêu, môi trường, cách đo

### 0.1. Mục tiêu

| # | Mục tiêu | Thành công khi |
|---|---|---|
| G1 | **Hệ thống hoá knowledge**: thuật ngữ, thực thể, chức năng, luồng, quy tắc, quyết định có một chỗ, một cấu trúc, một vòng đời, neo vào code | Mọi mục knowledge có loại, trạng thái, nguồn gốc, neo; code đổi thì mục liên quan tự về "cần xem lại" |
| G2 | **Nguồn knowledge giàu chất lượng cho AI** qua MCP | Câu trả lời có trích dẫn, độ tươi, mục "không chắc"; tỉ lệ lời gọi MCP trả rỗng giảm dần |
| G3 | **Biết vì sao không nối được** khi dữ liệu nằm trên máy PROD không mang ra được | Mỗi điểm gãy có **mã nguyên nhân** + bên phải sửa (admin input / extractor / liên kết tay / ngoài hệ thống); báo cáo ẩn danh mang ra được đủ để dev code-map tái hiện và sửa |

### 0.2. Hai môi trường

```
┌──────────────────────── MÁY PROD (không mang dữ liệu ra) ────────────────────────┐
│ source repo, catalog → codemap extract → pack (codemap.sqlite, graph.sqlite)      │
│ Viewer Hub: Code map + knowledge.sqlite + MCP ← AI agent trên máy PROD            │
│ codemap diagnose → báo cáo ẩn danh (.md + .json) + bảng tra tên (ở lại máy)       │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       │ chỉ báo cáo ẩn danh, người dùng xem trước khi mang ra
┌──────────────────────────────────────▼─────── MÁY DEV (code-map, viewer-hub) ─────┐
│ đọc báo cáo → tái hiện bằng fixture / corpus-gen → sửa extractor / linker         │
│ → bản code-map mới → chạy lại trên PROD → so hai báo cáo (trước / sau)            │
└────────────────────────────────────────────────────────────────────────────────────┘
```

Hệ quả cho thiết kế:

- Knowledge được xây **trên máy PROD** và ở lại đó; AI dùng nó qua MCP trên cùng máy.
- Mọi quyết định "nguyên nhân là gì" phải **tính trên PROD**, nơi có đủ tên, source, config. Chỉ **kết luận + hình dạng
  đã ẩn danh** đi ra ngoài.
- Báo cáo phải đủ để dev tái hiện **mà không cần hỏi lại** (mỗi vòng hỏi lại tốn một lần chạy trên PROD).

### 0.3. Chỉ số (hiện trên trang KB và trong báo cáo chẩn đoán)

| Chỉ số | Cách tính | Nguồn |
|---|---|---|
| Độ phủ knowledge | % tính năng có tài liệu luồng (người viết / AI viết); % bảng lõi có tên logic + định nghĩa; % thuật ngữ có định nghĩa | `kn.biz_*`, `graph_localization`, từ điển |
| Độ tươi | Số mục "Code đã đổi" / tổng số mục có fingerprint | `knowledge.revalidate` |
| Nhu cầu chưa đáp ứng | Lời gọi MCP trả rỗng, gom theo câu hỏi / tool | `kn.mcp_calls.empty` |
| Độ liền theo nguyên nhân | Số điểm gãy theo mã nguyên nhân (mục 7.3), tách theo bên phải sửa | báo cáo chẩn đoán |
| Điểm gãy im lặng | Tham chiếu không nối được mà **không có issue** | báo cáo chẩn đoán (mục 7.2) |
| Độ đúng của impact | Recall / precision trên benchmark và corpus-gen | `code-map/benchmark-data/`, `tools/corpus-gen` |

---

## 1. Hiện trạng (điều tra từ code)

### 1.1. Tầng sự thật (từ extract, chỉ đọc)

| Thành phần | Ở đâu | Ghi chú |
|---|---|---|
| Node / edge / evidence | `codemap.sqlite`: `graph_nodes`, `graph_edges`, `graph_evidence` | Snippet giới hạn 240 ký tự (`search_index.MAX_SNIPPET_CHARS`); benchmark trung bình 57 |
| Fingerprint hành vi | `graph_fingerprints` | Đổi khi hành vi đổi, không đổi khi dời dòng |
| Issue | `graph_issues` (`issue_type`, `raw_reference`, `message`, `properties_json`) | Chỉ một câu thông báo chung, không có mã nguyên nhân |
| Ứng viên nối | `graph.sqlite`: `resolution_candidates` (rank, score, `reasons_json`) | Chưa đưa lên giao diện hay vào báo cáo chẩn đoán |
| Comment nguồn | `graph.sqlite`: `comments`, phân loại `BUSINESS` khi có tiếng Nhật hoặc dài ≥ 40 ký tự | Chỉ dùng làm từ khoá tìm kiếm và trong file xuất cho AI |
| `semantic_tree` | `graph.sqlite`: `nodes.properties_json` | Phần nặng nhất; chỉ đọc khi mở chi tiết node và khi xuất AI |
| `CONFIG_KEY` | node (88 trên benchmark) | Có sẵn để đối chiếu URL dựng từ config |
| Từ điển, tên logic, menu, owner, ops | Input `semantic-dictionary.csv`, `localized-metadata.csv`, `menus.csv`, `owners.csv`, `ops-facts.csv`, comment Oracle | Benchmark: tất cả 0 dòng |
| Độ cũ so với working tree | `stale.py` | |
| Che bí mật | `redaction.py` | |

### 1.2. Tầng knowledge (`user/codemap/<pack_id>/knowledge.sqlite`, attach là `kn`)

| Loại | Bảng | Vòng đời | Neo |
|---|---|---|---|
| Quy tắc `RULE-…` | `kn.biz_rules` | `draft → approved → needs_review → retired` | node ids + fingerprint, `revalidate` |
| Quyết định `DEC-…` | `kn.biz_decisions` | `proposed → accepted/rejected/superseded` | node ids |
| Câu hỏi `Q-…` | `kn.biz_questions` | `open → answered` | node ids |
| Tính năng / menu | `kn.biz_items` | `ai → edited → approved` | id cây (`SCREEN`, `JOB_NETWORK`) |
| Tài liệu luồng | `kn.biz_flows.doc_json` | từng phần `ai/edited/approved`, phần đã duyệt có fingerprint | node của từng bước |
| Liên kết tay / AI đề xuất | `kn.biz_links` | `proposed → approved`, `source_ref/target_ref` để gắn lại | id + tên |
| Ghi chú node | `kn.graph_knowledge` | `draft/pending/approved/rejected` | target id |
| Ánh xạ thuật ngữ | `kn.semantic_mappings` | `approved/rejected` | target id → `semantic_id` |
| Nhật ký MCP | `kn.mcp_calls` (`empty`, thời gian) | — | — |

### 1.3. Đầu ra hiện có

- **MCP**: 13 tool, 6 prompt. Tool đề xuất (`propose_*`) ghi vào hàng chờ, đúng quy tắc "MCP chỉ đọc" của `AGENTS.md`.
- **Xuất / nhập cho AI**: YAML mỗi tính năng (`business/ai_exchange.py`), kiểm ref với đồ thị, giữ phần đã duyệt.
- **Chia sẻ knowledge** giữa người dùng Hub: `.codemap-knowledge.json`, ba chế độ gộp (`knowledge_share.py`).
- **ERD toàn DB** trong Code map (`erd.py`, `ErdPage.jsx`, tool `codemap_erd`).
- **`codemap diagnose`** (repo code-map): báo cáo ẩn danh mọi tên ngoài từ vựng của chính code-map; bảng tra tên ở
  lại máy (`diagnose-legend-KHONG-GUI.json`). Đánh giá chi tiết ở mục 7.1.

### 1.4. Khoảng trống

1. **Thu hoạch**: comment nghiệp vụ, comment Oracle, tên logic, `resolution_candidates` chưa thành mục knowledge.
2. **Mô hình**: thiếu loại **Thuật ngữ** và **Thực thể**; 5 bộ trạng thái khác nhau.
3. **Góc nhìn rối**: mức chi tiết, cách vẽ, mục đích trộn lẫn; ERD toàn DB nằm trong Code map dù không gắn với luồng.
4. **Chẩn đoán**: báo triệu chứng, không báo nguyên nhân; có điểm gãy im lặng (mục 7.2).
5. **Đo lường**: dữ liệu có, chưa tổng hợp.

---

## 2. Đánh giá lại bản v1

| Nhận định v1 | Kiểm chứng | Kết luận |
|---|---|---|
| DB 3GB do snippet trùng lặp | Snippet đã giới hạn 240 ký tự | **Sai nguyên nhân**; phần nặng là `graph.sqlite` (`semantic_tree`) |
| Bỏ `graph.sqlite` khỏi pack | Chỉ dùng cho chi tiết node + xuất AI | **Đúng hướng**, chuyển phần cần lúc chạy sang dạng gọn trước (mục 9) |
| `graph_paths` bùng nổ | Benchmark: 1 dòng | **Chưa chứng minh**, đo trên pack thật |
| Bỏ snippet, đọc source khi cần | Pack chỉ kèm source khi có `source_root` | **Không làm**; giữ snippet giới hạn |
| Thiếu 70–80% do URL động | Benchmark: `UNRESOLVED_HTTP_URL` 2 issue; 47/54 lời gọi API không nối được nhưng **0 issue** | **Sai chỗ**: phần lớn là điểm gãy im lặng và thiếu backend / catalog (mục 7.2) |
| MCP ghi trực tiếp | Trái `AGENTS.md` | Đổi thành `propose_*` vào hàng chờ |
| Addon AI stitcher tự gọi LLM | Trái §5 | AI chạy ở agent của user, đề xuất qua MCP |
| Patch YAML qua Git | Hub gọi `git` cần whitelist; pack PROD không chia sẻ | Bỏ; knowledge ở lại máy PROD |
| Không phân loại theo Actor | | **Đồng ý**; trục domain = Tính năng × Thực thể |
| Impact "đủ 100%" | | Đổi thành impact kèm độ phủ |

---

## 3. Mô hình knowledge thống nhất

### 3.1. Hai tầng

```
┌──────────────────────────┐  thu hoạch   ┌───────────────────────────────┐
│ FACTS (extract, chỉ đọc) │─────────────▶│ KNOWLEDGE (người sở hữu)      │──▶ MCP (AI)
│ codemap.sqlite           │              │ knowledge.sqlite (kn.*)       │
│ node, edge, evidence,    │◀─────────────│ thuật ngữ, thực thể, tính     │
│ issue, comment, catalog, │  revalidate  │ năng, luồng, quy tắc, quyết   │
│ fingerprint              │ (fingerprint)│ định, câu hỏi, ghi chú, liên  │
└──────────────────────────┘              │ kết; trạng thái + nguồn gốc   │
                                          └───────────────────────────────┘
```

- **Facts** không do người sửa; sửa input (catalog, từ điển, config) rồi extract lại.
- **Knowledge** là thứ duy nhất người và AI ghi, luôn neo vào facts.

### 3.2. Các loại knowledge

Giữ bảng hiện có, thêm hai loại (in đậm):

| Loại | Id | Bảng | Trả lời |
|---|---|---|---|
| **Thuật ngữ** | `TERM-…` | `kn.biz_terms` (mới; nhận `semantic-dictionary.csv` làm gốc, sửa trên web) | 注文 / Order / Đơn hàng là gì, alias kỹ thuật nào |
| **Thực thể** | `ENT-…` | `kn.biz_entities` (mới) | "Đơn hàng" gồm bảng nào, trạng thái nào, vòng đời ra sao |
| Tính năng | id cây | `kn.biz_items` | Màn hình / jobnet này để làm gì |
| Luồng | flow id | `kn.biz_flows` | Các bước nghiệp vụ của một thao tác |
| Quy tắc | `RULE-…` | `kn.biz_rules` | Điều kiện, ràng buộc, công thức |
| Quyết định | `DEC-…` | `kn.biz_decisions` | Vì sao làm như vậy |
| Câu hỏi | `Q-…` | `kn.biz_questions` | Chỗ chưa ai biết |
| Ghi chú | — | `kn.graph_knowledge` | Ghi chú trên một node |
| Liên kết | `link:…` | `kn.biz_links` | Cạnh đồ thị không thấy được |

**Thực thể** là trục giữa: bảng lõi (`T_CHUMON_HD`, `T_CHUMON_MS`) + tên logic + cột trạng thái + tính năng ghi / đọc (từ
cạnh `INSERTS/UPDATES/READS`) + quy tắc. Đề xuất tự động bằng cụm bảng (cùng tiền tố, nối khoá ngoại, cùng được ghi
trong một thao tác); AI đặt tên và mô tả.

### 3.3. Vòng đời chung

Ánh xạ trạng thái riêng hiện có sang một bộ hiển thị chung (không đổi schema cũ):

| Chung | rules | decisions | questions | items / flows | links | notes |
|---|---|---|---|---|---|---|
| **Đề xuất** (AI / thu hoạch) | draft | proposed | open | ai | proposed | draft, pending |
| **Đã sửa tay** | draft (source sme) | — | — | edited | — | — |
| **Đã xác nhận** | approved | accepted | answered | approved | approved | approved |
| **Cần xem lại** | needs_review | — | — | phần có fingerprint lệch | ref không khớp | — |
| **Bỏ** | retired | rejected, superseded | — | — | (xoá) | rejected |

Quy tắc:

1. **Nguồn gốc** trên mọi mục: `code`, `comment`, `catalog`, `dictionary`, `ai`, `sme`, `doc`.
2. **Neo**: node ids + tên đọc được để gắn lại khi id đổi.
3. **Fingerprint khi xác nhận**: mở rộng `revalidate` từ rules sang flows, entities, notes, links.
4. **Không có bước duyệt** (quyết định 2026-11-20): AI hay người ghi vào đều được dùng ngay, kèm **nguồn** (`ai`,
   `sme`, `doc`…) và người ghi. Không có trang "Chờ duyệt", nút Duyệt hay vai trò reviewer. Dữ liệu đang chờ duyệt
   từ trước được chuyển sang đang dùng một lần (`storage._drop_review_states`). Còn lại hai thứ không phải duyệt:
   câu hỏi chờ trả lời / quyết định chưa chốt, và cờ **Code đã đổi** (fingerprint lệch) hiện ngay trên mục, gỡ bằng
   **Sửa** hoặc **Vẫn đúng**.

---

## 4. Hai lens: Kỹ thuật và Nghiệp vụ

Ba trục hiện trộn lẫn: mức chi tiết (`SYSTEM/APPLICATION/TECHNICAL`, `levels.py`), cách vẽ (Graph / Swimlane), mục đích.
Thu về **hai lens theo mục đích**; mức chi tiết và cách vẽ là tuỳ chọn bên trong lens.

| | Lens **Kỹ thuật** | Lens **Nghiệp vụ** |
|---|---|---|
| Câu hỏi | Sửa X thì vỡ gì? X chạm tới đâu? Vì sao A không tới được B? | Hệ thống làm gì cho chức năng Y? Thực thể Z sống thế nào? Quy tắc nào áp dụng? |
| Trục | Node / cạnh / file | Tính năng × Thực thể; thuật ngữ |
| Mức chi tiết mặc định | Application (mở rộng ra đầy đủ) | System |
| Cách vẽ mặc định | Graph | Swimlane |
| Trang | Luồng kỹ thuật, impact, **điểm gãy** (mục 7.6), chi tiết node + bằng chứng | Bản đồ hệ thống, tính năng (tab **Dữ liệu**: ERD + CRUD của tính năng, mục 5.2), thực thể, thuật ngữ, quy tắc / quyết định / câu hỏi |
| Mức tin cậy | Tất định; cạnh AI / tay đánh dấu riêng; kết quả kèm độ phủ | Chữ do AI viết được chấp nhận ở trạng thái Đề xuất; phát hiện khi cũ |
| Người dùng chính | Dev + AI coding agent | BA, dev + AI viết / soát requirement |

Nhảy giữa hai lens: bước nghiệp vụ → node kỹ thuật (đã có `steps[].nodes`); node kỹ thuật → tính năng, thực thể, quy tắc
dùng nó; bảng → thực thể.

---

## 5. ERD: tách thành addon, Code map chỉ giữ ERD của tính năng

### 5.1. Phân chia

| | Addon **`erd`** (mới) | Code map |
|---|---|---|
| Phạm vi | Toàn DB: chọn schema / hệ thống / bảng bất kỳ, độ sâu 1–2 bước | Chỉ các bảng **tính năng đang xem** chạm tới |
| Chức năng | Duyệt, lấy bảng làm tâm, bộ lọc, chỉ cột khoá, tên JA / EN / kỹ thuật, xuất Mermaid / DBML | Tab **Dữ liệu** của trang tính năng: ERD nhỏ + ma trận CRUD (tính năng × bảng) |
| MCP | `erd_diagram` (thay `codemap_erd`) | Không có tool ERD riêng; `codemap_trace_flow` / `codemap_concept` liệt kê bảng và khoá |
| Nguồn dữ liệu | Đọc từ Code map qua export (mục 5.3); tuỳ chọn đọc FK thật từ addon `db-query` | `erd.py` (giữ, dùng chung) |
| Liên kết | Nhận deep link `/x/erd/?table=…` | Nút **Mở trong ERD** khi addon đã cài và không bị khoá |

Lý do: ERD toàn DB không phụ thuộc luồng hay knowledge, nặng giao diện, có vòng phát hành riêng. Đúng quy tắc "tính năng
mới ưu tiên làm addon" của `AGENTS.md`. Code map chỉ giữ phần gắn với ngữ cảnh tính năng.

### 5.2. ERD của tính năng (trong Code map)

- Tập bảng = các `TABLE/VIEW` mà luồng của tính năng đọc / ghi (từ cạnh dữ liệu, gồm liên kết tay đã xác nhận).
- Khoá ngoại **chỉ giữa các bảng trong tập**; bảng ngoài tập mà có FK tới thì hiện thành một ô mờ "N bảng khác"
  (bấm thì mở addon nếu có).
- Ma trận CRUD: hàng = thao tác / luồng, cột = bảng, ô = C/R/U/D. Sinh hoàn toàn từ cạnh, không cần AI.
- Giới hạn tối đa 40 bảng; vượt thì gom theo thực thể.
- `erd.py` thêm chế độ `tables=[…]` (tập bảng cho trước) bên cạnh `table` / `schema` / `system`.

### 5.3. Addon đọc dữ liệu Code map

Hiện chỉ addon khai được `exports` (`docs/plans/addon-interop.md`); Code map là module có sẵn. Mở rộng:

1. **Module có sẵn khai `exports`** trong `Module(...)` cùng định dạng contract (`addons/contract.py`): id provider là
   key module (`codemap`), Hub gọi hàm trong tiến trình, vẫn kiểm schema, ghi Giám sát, chỉ đọc.
2. Export của Code map cho addon ERD:

   | Export | Trả về |
   |---|---|
   | `erd_model` | Model ERD (`erd.build`) theo `table` / `schema` / `system` / `tables` |
   | `db_objects` | Danh sách schema, bảng (tên kỹ thuật, tên logic, hệ thống) để tìm / chọn |
   | `table_usage` | Tính năng / API / job đọc ghi một bảng (để ERD hiện "ai dùng bảng này") |

3. Addon `erd` khai `uses: [{"id": "codemap", "exports": [...], "version": "…"}]`. `deps.py` coi module có sẵn là
   provider luôn có mặt (trừ khi premium khoá); bản Hub là "version" của provider.
4. Addon chạy `managed` (Python, gọi Hub qua `addon.call`) hoặc chỉ có trang (gọi `addonApi`) tuỳ cách làm UI; logic
   ERD vẫn ở `erd.py` nên không chép code.

Chuyển đổi: một bản Hub giữ `codemap_erd` làm alias (ghi rõ "dùng `erd_diagram`"), sau đó bỏ. Trang ERD cũ của Code map
chuyển hướng sang addon nếu đã cài, ngược lại hiện hướng dẫn cài.

---

## 6. Thu hoạch knowledge và phục vụ AI (G1, G2)

### 6.1. Nguồn tất định đã trích nhưng chưa dùng

| Nguồn | Sinh ra đề xuất | Cách làm |
|---|---|---|
| Comment `BUSINESS` / `DOCUMENTATION` | Ghi chú node; ứng viên quy tắc khi comment chứa điều kiện (`〜の場合`, `以外`, `必須`, `上限`…) | Extract đưa bảng gọn `graph_comments(node_id, line, text)` vào `codemap.sqlite`, qua `redaction.py`, giới hạn độ dài |
| Comment bảng / cột Oracle, tên logic | Định nghĩa thuật ngữ, mô tả thực thể / cột | Đã có trong `graph_localization` / property `comment` |
| `semantic-dictionary.csv` | Thuật ngữ gốc | Nạp vào `kn.biz_terms`, sửa trên web không mất khi pack mới |
| `resolution_candidates` | Liên kết đề xuất | Rank 1, score cao → "Liên kết đề xuất" |
| Điều kiện trong `semantic_tree` | Ứng viên quy tắc / bảng quyết định | Đã dùng trong xuất AI; chuyển sang `graph_conditions` gọn (mục 9) |

**Ưu tiên theo nhu cầu**: gom `kn.mcp_calls` trả rỗng theo từ khoá → "AI hỏi mà KB không có" → danh sách việc cần thu
hoạch, hiện trên trang KB.

### 6.2. AI làm giàu (agent trên máy PROD, không trong Hub)

Hub không gọi LLM. Mở rộng hai kênh đã có:

1. **MCP**: thêm `propose_term`, `propose_entity`, `propose_link` (cùng mẫu `write_tools.py`: token riêng, vào trạng thái
   Đề xuất). Prompt `harvest`: lấy danh sách việc → đọc facts + comment → đề xuất.
2. **File**: YAML xuất cho AI (`ai_exchange.py`) thêm thuật ngữ, thực thể, comment nghiệp vụ, ứng viên liên kết.

Kiểm lúc nhận đề xuất (từ chối nếu thiếu): mỗi khẳng định trích ít nhất một node / evidence / comment; ref tồn tại trong
đồ thị; có mục "không chắc"; code và tài liệu lệch thì tạo câu hỏi, không tự đặt quy tắc (`prompts.COMMON`).

### 6.3. Nguyên tắc trả lời MCP

- Dòng đầu: độ tươi (`graph_stamp`, file đã đổi theo `stale.py`).
- Knowledge đã xác nhận trước, facts sau, đề xuất cuối (ghi rõ trạng thái).
- Trích dẫn bằng id (`[N3]`, `RULE-…`, `TERM-…`) hoặc `file:dòng`.
- Mục "Không chắc" bắt buộc. Impact và trace kèm **độ phủ**: "đường đi qua 3 điểm gãy, mã nguyên nhân …" (dùng chung
  phân loại mục 7.3, nên AI biết điểm gãy là thiếu input hay giới hạn của extractor).

### 6.4. Tool theo lens

| Lens Kỹ thuật | Lens Nghiệp vụ |
|---|---|
| `codemap_search` | `codemap_search` (`scope=business`) |
| `codemap_trace_flow`, `codemap_impact`, `codemap_file_context`, `codemap_status` | `codemap_current_behavior`, `codemap_check_terms`, `codemap_get_flow_doc` |
| `codemap_diagnose_flow` (mới: vì sao A không tới B, mục 7.5) | `codemap_concept` (mới: thẻ thuật ngữ / thực thể: định nghĩa, bảng, CRUD, quy tắc, câu hỏi mở) |
| `propose_link` | `propose_term`, `propose_entity`, `propose_rule`, `propose_flow_doc`, `propose_question`, `propose_decision` |

Hai endpoint MCP (`/codemap/mcp/technical`, `/codemap/mcp/business`): `Module.mcp` thành danh sách, cập nhật `GUIDE.md`,
`/help`, MCP Bridge, `tests/test_modules.py`. Giữ endpoint gộp cũ một thời gian.

**Domain brief**: mỗi tính năng / thực thể có brief sinh tất định từ knowledge đã xác nhận + facts (mục đích, bước, CRUD,
quy tắc, câu hỏi mở, độ tươi); `codemap_concept` / `get_flow_doc` trả brief để agent nạp làm context.

---

## 7. Chẩn đoán điểm gãy từ máy PROD (G3)

### 7.1. `codemap diagnose` hiện có: tốt ở đâu, thiếu ở đâu

Đã chạy trên `benchmark-data/all-systems` để đánh giá.

**Đã tốt (giữ)**: ẩn danh bằng từ vựng của chính code-map, cùng tên thì cùng placeholder (so được hai phía Angular /
.NET); bảng tra tên ở lại máy; có bảng cấu hình source, đường đi tới DB theo loại điểm bắt đầu, lời gọi API chưa nối,
API không xuống DB, mẫu issue.

**Chưa đủ để ra nguyên nhân**:

| # | Vấn đề | Thấy ở benchmark |
|---|---|---|
| D1 | **Điểm gãy im lặng**: `link_api` chỉ tạo issue khi có > 1 ứng viên; 0 ứng viên thì không có gì | 47/54 `API_CALL_REFERENCE` không có `CALLS_API`, 0 issue trên các node đó |
| D2 | **Chỉ báo triệu chứng**: "không có API cùng phần cuối route" không phân biệt *thiếu repo backend* / *extractor không đọc được kiểu khai route* / *URL dựng từ config chưa giải* / *prefix khác (gateway, IIS virtual dir, `UsePathBase`)* | 23 lời gọi "không có API cùng phần cuối"; thực tế backend của hai repo frontend không có trong config |
| D3 | **So khớp ứng viên vô nghĩa**: so theo đoạn cuối route, khi đoạn cuối là `{id}` thì mọi API có `{id}` thành ứng viên | `PUT /w1/api/w2/{id} ⇢ DELETE /api/catalog-items/{id}; GET /Order/{id}` |
| D4 | **Lời gọi không gắn được vào method** chỉ có tên đã ẩn (`Call w19.w25`), không có *hình dạng*: receiver là interface hay class, có bao nhiêu implementation trong đồ thị, có đăng ký DI không, có phải mediator (`Send`) / reflection | 32/32 API có handler nhưng 0 xuống DB |
| D5 | **Không nối chuỗi nguyên nhân**: 94 procedure chỉ tới `UNRESOLVED` và 212 `TABLE_NOT_IMPORTED` được báo ở hai mục rời, không nói "phần lớn procedure gãy vì catalog thiếu N bảng" | mục 4 và 7 của báo cáo |
| D6 | **Nhiễu**: `DUAL` (bảng giả của Oracle) đếm là `TABLE_NOT_IMPORTED` | 16 lần |
| D7 | **Mất bằng chứng**: issue bị cắt theo giới hạn cấu hình ("65 additional … omitted") | nhiều dòng |
| D8 | **Không có vết quyết định của linker**: resolver nào đã thử, so với khoá nào, gần khớp gì, vì sao bỏ; `resolution_candidates` không vào báo cáo | — |
| D9 | **Không có mẫu tái hiện**: dev nhận số đếm và tên đã ẩn, không có hình dạng code để viết fixture | — |
| D10 | **Chỉ toàn cục**: không hỏi được "vì sao màn hình A không tới bảng B" cho một luồng cụ thể | — |
| D11 | **URL dựng từ config** chưa đối chiếu với 88 node `CONFIG_KEY`: không biết khoá có trong file config đã quét hay không | `{baseUrlConfiguration_Value_ApiBase}{…}` |

### 7.2. Nguyên tắc thiết kế mới

1. **Quyết định nguyên nhân trên PROD** với dữ liệu thật (tên, source, config, catalog); chỉ mã nguyên nhân, số đếm và
   hình dạng đã ẩn danh đi ra.
2. **Không còn điểm gãy im lặng**: mọi tham chiếu không nối được có đúng một bản ghi chẩn đoán.
3. **Hình dạng thay cho tên**: thay vì `w19.w25`, báo `receiver=interface, impl_in_graph=0, impl_text_found=1,
   di_registration=yes`. Hình dạng không lộ nghiệp vụ nhưng đủ để biết extractor thiếu gì.
4. **Gom theo nguyên nhân, xếp theo tác động**: nhóm nguyên nhân nào làm gãy nhiều luồng nhất lên đầu.
5. **Mỗi nhóm có mẫu tái hiện** ẩn danh để dev viết fixture không cần hỏi lại.
6. **Máy đọc được**: kèm `.json` để dev so trước / sau và đưa vào benchmark.

### 7.3. Phân loại nguyên nhân

Mỗi điểm gãy nhận một mã, và mã quyết định **ai sửa**:

| Mã | Nghĩa | Bằng chứng quyết định (tính trên PROD) | Ai sửa |
|---|---|---|---|
| `INPUT_REPO_MISSING` | Không source nào khai route / object được gọi | Không `API_OPERATION` nào chung ≥ 2 đoạn tĩnh của route; quét chữ mọi source đã cấu hình cũng không thấy khai báo | Admin: thêm repo vào config |
| `INPUT_CATALOG_MISSING` | Bảng / cột không có trong catalog | `TABLE_NOT_IMPORTED`; tên có trong DDL / code khác hay không; schema owner nào | Admin: bổ sung export Oracle |
| `INPUT_CONFIG_MISSING` | URL / tên dựng từ khoá config không có trong file đã quét | Placeholder trong `evaluated` ↔ node `CONFIG_KEY`; tên file config mẫu (`environment*.ts`, `appsettings*.json`, `Web.config`) có / không | Admin: thêm thư mục config vào source |
| `EXTRACTOR_DECL_MISSED` | Source có khai báo nhưng extractor không sinh node | Quét chữ thấy mẫu khai route (`[Route(`, `[Http*(`, `Map{Get,Post}(`, `@RequestMapping`, `app.get(`…) trong file không có `API_OPERATION`; báo mẫu nào | Dev code-map |
| `EXTRACTOR_CALL_UNBOUND` | Lời gọi trong method không gắn được vào đích | Hình dạng receiver (interface / abstract / generic / delegate / dynamic), số implementation trong đồ thị, DI registration, mediator, reflection | Dev code-map (hoặc liên kết tay nếu là reflection) |
| `ROUTE_PREFIX_MISMATCH` | Phần đuôi tĩnh khớp, phần đầu khác | Các đoạn tĩnh cuối trùng; prefix chung lặp lại trên nhiều lời gọi (`/petclinic/api` ↔ `/api`) | Admin: khai `routePrefixes` / gateway; hoặc dev nếu là `UsePathBase` / virtual dir chưa đọc |
| `ROUTE_VERB_MISMATCH` | Route khớp, verb khác | | Kiểm code (có thể là lỗi thật của ứng dụng) |
| `ROUTE_AMBIGUOUS` | Nhiều đích khớp ngang nhau | Số ứng viên, điểm, lý do | Liên kết tay / dev |
| `URL_DYNAMIC` | URL không giải được tĩnh, không dựa trên config | Hình dạng biểu thức (nối chuỗi, biến, hàm) | Liên kết tay |
| `SQL_DYNAMIC` | `EXECUTE IMMEDIATE`, tên bảng ghép chuỗi | Hình dạng biểu thức | Liên kết tay |
| `ROUTINE_AMBIGUOUS` | Overload / nhiều package trùng tên | Số ứng viên, chữ ký | Dev code-map (giải overload) |
| `EXTERNAL_EXPECTED` | Đích là hệ thống ngoài (host khác, DB link) | Host / DB link không thuộc source nào | Chấp nhận; tạo node ngoài |
| `IGNORABLE` | Không phải điểm gãy | `DUAL`, bảng hệ thống, test code | Lọc khỏi số liệu |

### 7.4. Thay đổi ở extractor (`code-map`)

1. **Vết thử nối** (`link_attempts` trong `graph.sqlite`, một dòng mỗi tham chiếu không nối được):
   `reference_id, resolver, key_tried, candidate_count, near_misses_json (top 3: id, điểm, khác ở đâu), reason_code`.
   Ghi trong `link_api`, `link_gateway`, `resolve_deferred_references`, `materialize_dangling_references`.
2. **Hết im lặng**: `link_api` với 0 ứng viên tạo issue `API_ROUTE_NOT_FOUND` kèm signature và near misses.
3. **So khớp theo đoạn tĩnh**: bỏ `{id}` / tham số khi so đuôi route; chấm điểm theo số đoạn tĩnh trùng (sửa D3; dùng
   chung cho linker và diagnose).
4. **Hình dạng lời gọi chưa gắn**: extractor .NET / Java ghi `receiver_kind`, `is_interface`, `generic_arity`,
   `invocation_kind` (direct / interface / delegate / mediator / reflection) vào issue.
5. **Không cắt bằng chứng cho chẩn đoán**: giới hạn số issue chỉ áp dụng cho bảng phục vụ web; `link_attempts` giữ đủ
   (hoặc giữ đủ số đếm + mẫu theo từng nhóm).
6. `IGNORABLE`: danh sách bảng giả / hệ thống theo dialect (`DUAL`, `SYS.*`…).

### 7.5. Thay đổi ở `codemap diagnose`

1. **Mục mới "Nguyên nhân"** đứng đầu báo cáo: bảng mã nguyên nhân × số điểm gãy × số luồng bị ảnh hưởng × ai sửa, xếp
   theo số luồng.
2. **Chuỗi nguyên nhân** (D5): với mỗi điểm bắt đầu không tới DB, đi tới điểm gãy đầu tiên, lấy mã của nó; tổng hợp
   "N luồng dừng vì `INPUT_CATALOG_MISSING` (M bảng, top schema DB1.w3)".
3. **Quét chữ có kiểm soát** trên source đã cấu hình (chỉ đọc file đã nằm trong config, không chạy gì): đếm mẫu khai
   route / DI / mediator theo file, so với node đã trích → `EXTRACTOR_DECL_MISSED`, `INPUT_REPO_MISSING`.
4. **Đối chiếu config** (D11): placeholder ↔ `CONFIG_KEY`; liệt kê *loại* file config có / thiếu.
5. **Mẫu tái hiện ẩn danh** cho mỗi nhóm (D9): đoạn code ±10 dòng quanh điểm gãy, giữ cú pháp và từ vựng framework, tên
   thay bằng `wN` như phần còn lại, chuỗi literal thay bằng hình dạng (`"/w1/api/{p}"`, `"<str:12>"`), comment bỏ.
   Mặc định **tắt**; bật bằng `--samples-code`, và báo cáo ghi rõ có kèm code đã ẩn danh. Người dùng xem trước khi mang ra.
6. **Chế độ nhắm một luồng** (D10): `codemap diagnose --from <id|tên> --to <id|tên>`: tìm hai chiều, trả khoảng hở,
   near misses, mã nguyên nhân, đường đi đã ẩn danh. Cùng thuật toán với tool MCP `codemap_diagnose_flow` (dùng trên PROD,
   có tên thật).
7. **Đầu ra kép**: `diagnose-report.md` (người đọc) + `diagnose-report.json` (mã, số đếm, hình dạng, mẫu; không tên thật).
8. **So trước / sau** trên máy dev: `codemap diagnose-compare old.json new.json` báo nhóm nào giảm, nhóm nào mới.
9. Từ khoá kiểm `--strict` giữ nguyên; thêm test "không tên thật nào lọt ra" cho phần hình dạng và mẫu code
   (`codemap/tests/test_diagnose.py`).

### 7.6. Trên Viewer Hub (máy PROD)

- Trang **Điểm gãy** (lens Kỹ thuật): đọc `graph_issues` + `link_attempts`, gom theo mã nguyên nhân, **tên thật** (chỉ
  trên máy này), mỗi nhóm có hướng xử lý: liên hệ admin (input), tạo liên kết tay (dynamic), hoặc "giới hạn của
  extractor, gửi báo cáo chẩn đoán".
- Nút **Tạo báo cáo chẩn đoán**: chạy cùng logic với `codemap diagnose` trên pack đang mở (cần từ vựng của code-map đóng
  kèm pack dưới dạng file dữ liệu), lưu báo cáo + bảng tra tên vào thư mục dữ liệu, mở xem trước. Hub không gửi đi đâu.
- Trace / impact hiện mã nguyên nhân tại chỗ gãy.

### 7.7. Vòng sửa trên máy dev

1. Đọc mục "Nguyên nhân", lấy nhóm `EXTRACTOR_*` lớn nhất.
2. Từ mẫu tái hiện, viết fixture vào `extractor/tests` và một pattern trong `tools/corpus-gen` (`expected: detectable`
   hoặc `partial`), để lỗi không quay lại.
3. Sửa extractor / linker, chạy benchmark và corpus-gen.
4. Phát hành code-map, chạy lại trên PROD, so hai báo cáo bằng `diagnose-compare`.

---

## 8. MCP để AI tài liệu (Copilot Studio) tạo knowledge

### 8.1. Mục đích

Agent trên Copilot Studio nắm **tài liệu nghiệp vụ** (spec, 画面設計書, 機能仕様書, DB設計書) nhưng **không thấy code**. Mục
này định nghĩa bộ tool MCP để agent đó **ghi knowledge vào Code map**: tài liệu luồng, liên kết node, thuật ngữ, thực thể,
quy tắc, ghi chú, câu trả lời. Agent cần đọc đúng hai thứ: **còn thiếu gì** và **tên trong tài liệu ứng với node nào**.
Mọi thứ khác là tool ghi.

Bộ tool này dùng chung cho mọi agent viết knowledge (Copilot Studio, GitHub Copilot, Claude Code). Nó không phải một API
riêng cho Copilot Studio.

### 8.2. Hiện có và cần thêm

| Tool | Trạng thái | Thay đổi |
|---|---|---|
| `codemap_get_flow_doc` | có | Giữ |
| `codemap_propose_flow_doc` | có | Cho phép `citations` ở từng bước / quy tắc |
| `codemap_propose_rule` | có | Hiện bắt buộc `evidence` (file:dòng); đổi thành **`evidence` hoặc `citations`** |
| `codemap_propose_question` | có | Giữ |
| `codemap_propose_decision` | có | Thêm `citations` |
| `codemap_knowledge_gaps` | **mới**, đọc | Danh sách việc cần viết |
| `codemap_resolve` | **mới**, đọc | Tên trong tài liệu → node id |
| `codemap_propose_link` | **mới** | Liên kết hai node |
| `codemap_propose_term` | **mới** | Thuật ngữ |
| `codemap_propose_entity` | **mới** | Thực thể nghiệp vụ |
| `codemap_propose_note` | **mới** | Ghi chú trên node |
| `codemap_propose_answer` | **mới** | Trả lời câu hỏi đang mở |

### 8.3. Quy ước chung cho tool ghi

- **Quyền**: như `write_tools.py` hiện nay. Tool ghi chỉ hiện khi có knowledge token (`X-Code-Map-Token` hoặc
  `Authorization: Bearer`); Hub ở chế độ chỉ đọc thì không có.
- **Trạng thái**: mọi thứ ghi vào ở trạng thái **Đề xuất** (`draft` / `proposed` / `ai`), nguồn `doc` khi có
  `citations`, `ai` khi không có. Ghi xong là dùng ngay; kết quả tool nhắc agent trích là "AI viết" (`AI_HINT`).
- **Người ghi**: `created_by` lấy từ `X-Code-Map-User`, hoặc tên client trong `initialize` (ví dụ `copilot-studio`).
- **Tham chiếu node** (`nodes`, `source`, `target`): nhận node id **hoặc** tên kỹ thuật / tên logic, như `_NODES` hiện có.
  Tên phải ra đúng một node. Nếu ra nhiều node, tool trả danh sách ứng viên và không ghi gì.
- **Trích dẫn** (`citations`), cùng một kiểu cho mọi tool:
  ```json
  [{"doc": "注文登録画面設計書.xlsx", "section": "3.2 イベント定義", "url": "<tuỳ chọn>", "quote": "<≤ 200 ký tự, tuỳ chọn>"}]
  ```
  Bắt buộc với knowledge lấy từ tài liệu (link, term, entity, answer). Không có thì từ chối.
- **Không nhân bản**: mỗi loại có khoá tự nhiên (link: nguồn + đích + loại cạnh; term: `semantic_id`; entity: tập bảng;
  answer: `question_id`). Gửi lại cùng khoá thì **cập nhật** đề xuất cũ. Mục đã xác nhận thì không sửa; tool báo "đã xác
  nhận, tạo câu hỏi nếu tài liệu khác".
- **Kết quả**: văn bản gọn gồm id đã tạo / cập nhật, lý do từ chối từng mục, và gợi ý bước tiếp theo.
- **Giới hạn**: tối đa 20 mục mỗi lần gọi (tool nhận mảng); chữ ≤ `MAX_TEXT`; chữ nhận vào đi qua che bí mật.
- **Ghi log**: mọi lời gọi vào `kn.mcp_calls` và Giám sát như hiện nay.

### 8.4. Tool đọc

#### `codemap_knowledge_gaps`

Những gì còn thiếu, xếp theo tác động (số luồng liên quan, số lần AI khác hỏi mà KB trả rỗng).

| Tham số | Kiểu | Nghĩa |
|---|---|---|
| `kind` | `flow_doc` \| `link` \| `term` \| `entity` \| `question` \| `all` | Loại việc |
| `system` | string, tuỳ chọn | Thu hẹp theo hệ thống |
| `feature` | string, tuỳ chọn | Thu hẹp theo tính năng (id hoặc tên) |
| `limit` | int, mặc định 20, tối đa 50 | |

Trả về mỗi dòng: `gap_id`, loại, đối tượng (tên + tên logic + id), lý do. Lý do có thể là: chưa có tài liệu, phần cần
xem lại, mã nguyên nhân điểm gãy (mục 7.3), chưa có định nghĩa. Với `link`, chỉ trả điểm gãy mà tài liệu có thể giúp
(`URL_DYNAMIC`, `SQL_DYNAMIC`, `ROUTE_AMBIGUOUS`, `ROUTE_PREFIX_MISMATCH`, `EXTRACTOR_CALL_UNBOUND`), kèm top 5 ứng viên
đích (id, tên, tên logic, điểm). Không trả điểm gãy `INPUT_*`: đó là thiếu input, admin phải sửa.

#### `codemap_resolve`

Đổi tên trong tài liệu ra node.

| Tham số | Kiểu | Nghĩa |
|---|---|---|
| `names` | string[] (≤ 20) | Tên màn hình, API, bảng, job, thuật ngữ; tiếng Nhật / Anh / Việt / tên kỹ thuật |
| `type` | string, tuỳ chọn | `SCREEN`, `API_OPERATION`, `TABLE`, `JOB`… |
| `system` | string, tuỳ chọn | |

Trả về với mỗi tên: `exact` (1 node), `ambiguous` (danh sách ứng viên) hoặc `none`. Dùng chung index với
`codemap_search` (từ điển, tên logic, `semantic_mappings`).

### 8.5. Tool ghi mới

#### `codemap_propose_link`

| Tham số | Bắt buộc | Nghĩa |
|---|---|---|
| `links` | ✓ | Mảng (≤ 20) các mục bên dưới |
| ↳ `source` | ✓ | id hoặc tên node nguồn |
| ↳ `target` | ✓ | id hoặc tên node đích |
| ↳ `edge_type` | ✓ | Một trong `LINK_TYPES` (`CALLS`, `CALLS_API`, `HANDLED_BY`, `TRIGGERS`, `TRIGGERS_JOB`, `PUBLISHES`, `CONSUMED_BY`, `RENDERS`, `READS`, `INSERTS`, `UPDATES`, `DELETES`, `MERGES`) |
| ↳ `reason` | ✓ | Vì sao hai node nối nhau |
| ↳ `citations` | ✓ | |
| ↳ `confidence` | | 0–1 |
| ↳ `gap_id` | | Điểm gãy mà liên kết này đóng (từ `codemap_knowledge_gaps`) |

Kiểm: hai đầu tồn tại; `edge_type` hợp với loại node hai đầu (`check_link` hiện có); không trùng cạnh đã trích từ code.
Liên kết không gắn `gap_id` vẫn nhận nhưng được gắn cờ "ngoài điểm gãy". Ghi vào `kn.biz_links` với `status=proposed`,
`origin=ai`, cùng `source_ref` / `target_ref` (để gắn lại khi id đổi) và trích dẫn. Khi đã xác nhận, liên kết được vẽ
nhãn "theo tài liệu" và được tính trong trace / impact.

#### `codemap_propose_term`

| Tham số | Bắt buộc | Nghĩa |
|---|---|---|
| `terms` | ✓ | Mảng (≤ 20) |
| ↳ `label` | ✓ | `{"ja": "注文", "en": "Order", "vi": "Đơn hàng"}` (ít nhất một ngôn ngữ) |
| ↳ `definition` | ✓ | Định nghĩa nghiệp vụ |
| ↳ `aliases` | | Tên kỹ thuật, từ đồng nghĩa (`CHUMON`, `T_CHUMON_HD`, `createOrder`) |
| ↳ `domain` | | Mã domain, dùng cho id `semantic:<domain>:<khái niệm>` |
| ↳ `nodes` | | Node mà thuật ngữ chỉ tới (bảng, màn hình…) |
| ↳ `citations` | ✓ | |

Ghi vào `kn.biz_terms` (mới, mục 3.2). Alias khớp tên kỹ thuật thì đề xuất luôn `semantic_mappings`.

#### `codemap_propose_entity`

| Tham số | Bắt buộc | Nghĩa |
|---|---|---|
| `name` | ✓ | `{"ja": …, "en": …, "vi": …}` |
| `description` | ✓ | |
| `tables` | ✓ | Bảng thuộc thực thể (id hoặc tên) và vai trò: `header`, `detail`, `history`, `master` |
| `states` | | `{"column": "STATUS_KBN", "values": [{"code": "10", "meaning": "受付"}, …]}` |
| `lifecycle` | | Chuỗi trạng thái và tính năng chuyển trạng thái (tên hoặc id) |
| `citations` | ✓ | |

Ghi vào `kn.biz_entities` (mới). Kiểm: bảng tồn tại; cột trạng thái thuộc một trong các bảng.

#### `codemap_propose_note`

| Tham số | Bắt buộc | Nghĩa |
|---|---|---|
| `node` | ✓ | id hoặc tên |
| `text` | ✓ | Ghi chú nghiệp vụ |
| `citations` | | |

Ghi vào `kn.graph_knowledge` với `status=pending`.

#### `codemap_propose_answer`

| Tham số | Bắt buộc | Nghĩa |
|---|---|---|
| `question_id` | ✓ | `Q-…` |
| `answer` | ✓ | Câu trả lời |
| `option` | | Tiêu đề phương án được chọn (nếu câu hỏi có phương án) |
| `citations` | ✓ | |

Câu trả lời lưu kèm câu hỏi ở dạng **đề xuất**. Câu hỏi vẫn `open` cho tới khi người dùng xác nhận.

### 8.6. Trình tự agent dùng

Ghi thành instructions cho agent. Hub sinh sẵn đoạn này trong trang Hướng dẫn, cùng chỗ với cấu hình MCP cho GitHub
Copilot đã có. Không dựa vào MCP prompts.

```
Viết tài liệu luồng:
  codemap_knowledge_gaps(kind=flow_doc) → codemap_get_flow_doc(flow) → tra tài liệu →
  codemap_propose_flow_doc(flow_id, document) [+ codemap_propose_rule / propose_question cho chỗ tài liệu và code lệch]

Nối node:
  codemap_knowledge_gaps(kind=link) → với từng điểm gãy: tra tài liệu xem nguồn gọi / ghi tới đâu →
  codemap_resolve(names) → codemap_propose_link(links=[{source, target, edge_type, reason, citations, gap_id}])

Thuật ngữ, thực thể:
  codemap_knowledge_gaps(kind=term|entity) → codemap_resolve → codemap_propose_term / codemap_propose_entity

Quy tắc chung: chỉ khẳng định điều có trong tài liệu và có trích dẫn; tên không resolve được thì không đoán id;
tài liệu khác code thì tạo câu hỏi (codemap_propose_question), không tự chọn bên nào đúng.
```

### 8.7. Việc cần làm

1. `citations` + nguồn `doc` cho các bảng `kn.*` (cột `citations_json`, thêm qua `CREATE TABLE IF NOT EXISTS` / migration).
2. `codemap_resolve`, `codemap_knowledge_gaps` (phụ thuộc mã nguyên nhân của GĐ 1 cho phần `link`; trước đó dùng
   `issue_type`).
3. `codemap_propose_link`, `codemap_propose_note`, `codemap_propose_answer` (dùng bảng đã có).
4. `codemap_propose_term`, `codemap_propose_entity` (cần `kn.biz_terms`, `kn.biz_entities` của GĐ 3).
5. Sửa `propose_rule` / `propose_flow_doc` / `propose_decision` nhận `citations`.
6. Cập nhật `GUIDE.md` ("### Tool cho AI" phải có một dòng cho mỗi tool, `tests/test_modules.py` kiểm), và đoạn
   instructions sinh sẵn.
7. Test: tham chiếu mơ hồ không ghi gì; gửi lại cùng khoá thì cập nhật; mục đã xác nhận không bị sửa; thiếu trích dẫn
   bị từ chối.

Cần thử với Copilot Studio thật: connector hiển thị tham số mảng / đối tượng lồng (`links`, `terms`, `citations`) có
tốt không. Nếu không, nhận thêm dạng chuỗi JSON cho cùng tham số.

---

## 9. Dung lượng

Đo trên pack thật trước khi sửa:

```sql
SELECT name, SUM(pgsize)/1048576 AS mb FROM dbstat GROUP BY name ORDER BY mb DESC;   -- cả hai file
SELECT COUNT(*) FROM graph_paths;
```

Benchmark (2.792 node) chỉ 14MB + 10MB, chưa nói được gì về pack thật. Hướng xử lý tuỳ kết quả:

1. `graph.sqlite` thành **tuỳ chọn** của pack; chuyển phần cần lúc chạy vào `codemap.sqlite` ở dạng gọn:
   `graph_comments`, `graph_conditions(node_id, kind, text)`, `link_attempts` (cho trang Điểm gãy). Chi tiết node hiện
   `semantic_tree` chỉ khi có `graph.sqlite`. `codemap diagnose` vẫn chạy trên `graph.sqlite` ở máy PROD.
2. `graph_paths` lớn: duyệt theo yêu cầu, giới hạn độ sâu + số node, cache theo `graph_stamp`.
3. FTS5 thay `search_terms` chỉ khi đo thấy lợi; tiếng Nhật không có khoảng trắng nên `unicode61` không tách được (cần
   trigram hoặc giữ `search_tokens`); kiểm bằng `testdata/search-token-vectors.json`.
4. Giữ snippet giới hạn.

---

## 10. Ràng buộc bảo mật và quy tắc repo

| Quy tắc | Áp dụng |
|---|---|
| MCP chỉ đọc, ghi qua token + trạng thái Đề xuất | Tool mới `propose_*`; `erd_diagram` và export của Code map chỉ đọc |
| Không tải / gọi mạng lúc chạy | Hub không gọi LLM; Hub không gửi báo cáo chẩn đoán đi đâu |
| Tiến trình con chỉ argv, file được whitelist | Không gọi `git`; quét chữ của diagnose chỉ đọc file, không chạy |
| Dữ liệu user không mất | Bảng mới `CREATE TABLE IF NOT EXISTS` trong `kn`; đổi format = migration |
| Bí mật / tên thật không ra khỏi PROD | Báo cáo chỉ chứa từ vựng của code-map + placeholder; mẫu code mặc định tắt; test "không tên thật lọt ra"; bảng tra tên ở lại máy |
| Tính năng mới ưu tiên addon | ERD toàn DB thành addon `erd` |
| React + Material 3, tiếng Việt | Trang mới dùng `web/src/md`, `SearchBar` + `FilterBar` |

---

## 11. Lộ trình

**GĐ 0: Đo**
- Chạy câu đo mục 9 và `codemap diagnose` hiện tại trên PROD.
- *Xong khi*: biết phần nào chiếm dung lượng, nhóm triệu chứng nào lớn nhất.

**GĐ 1: Chẩn đoán ra nguyên nhân** (làm trước vì quyết định chất lượng mọi thứ còn lại)
- Extractor: `API_ROUTE_NOT_FOUND`, `link_attempts`, so khớp theo đoạn tĩnh, `IGNORABLE`, không cắt bằng chứng.
- Diagnose: mục Nguyên nhân, chuỗi nguyên nhân, quét chữ, đối chiếu config, `.json`, `diagnose-compare`.
- *Xong khi*: trên benchmark không còn điểm gãy im lặng; 47 lời gọi API chưa nối nhận mã `INPUT_REPO_MISSING` /
  `ROUTE_PREFIX_MISMATCH` đúng; 94 procedure gãy quy về `INPUT_CATALOG_MISSING`.

**GĐ 2: Hai lens + vòng đời chung + ERD addon**
- Công tắc **Kỹ thuật | Nghiệp vụ**, nhảy giữa hai lens; trạng thái chung; mở rộng `revalidate`.
- Module có sẵn khai `exports`; addon `erd`; tab Dữ liệu (ERD + CRUD) của tính năng; alias `codemap_erd`.
- *Xong khi*: trang ERD toàn DB chạy trong addon, đọc dữ liệu qua export; Code map chỉ hiện ERD của tính năng.

**GĐ 3: Thuật ngữ, thực thể, thu hoạch**
- `kn.biz_terms`, `kn.biz_entities`; đề xuất thực thể theo cụm bảng.
- `graph_comments`, `graph_conditions`; thu hoạch comment / catalog / từ điển / `resolution_candidates`; danh sách việc từ
  `mcp_calls` rỗng.
- *Xong khi*: mỗi bảng lõi có thực thể đề xuất; comment nghiệp vụ hiện trên node.

**GĐ 4: Phục vụ AI**
- `codemap_concept`, `codemap_diagnose_flow`, `propose_term/entity/link`, prompt `harvest`; hai endpoint MCP; domain brief;
  mã nguyên nhân trong trace / impact.
- *Xong khi*: tỉ lệ MCP trả rỗng giảm; câu trả lời có trích dẫn, độ tươi, độ phủ.

**GĐ 4b: Tool MCP để AI tài liệu tạo knowledge** (mục 8)
- `citations` + nguồn `doc`; `codemap_resolve`, `codemap_knowledge_gaps`; `propose_link`, `propose_note`,
  `propose_answer`; sau GĐ 3: `propose_term`, `propose_entity`; instructions sinh sẵn.
- *Xong khi*: agent Copilot Studio viết được tài liệu luồng và đề xuất liên kết có trích dẫn cho một tính năng thật.

**GĐ 5: Trang Điểm gãy trên Hub + dung lượng**
- Trang Điểm gãy, nút tạo báo cáo chẩn đoán trong Hub.
- `graph.sqlite` tuỳ chọn; `graph_paths` / FTS5 theo kết quả GĐ 0.

---

## 12. Câu hỏi còn mở

1. Pack 3GB: bảng nào chiếm bao nhiêu? (GĐ 5)
2. Mẫu code đã ẩn danh (mục 7.5 bước 5) có được phép mang ra khỏi PROD không, hay chỉ hình dạng + số đếm?
3. Trên PROD có chạy được `codemap diagnose` (cần code-map + Python), hay mọi chẩn đoán phải đi qua Viewer Hub?
4. Addon `erd` có cần đọc FK thật từ `db-query` khi catalog thiếu khoá ngoại không?
5. Admin có cung cấp được `menus.csv`, `semantic-dictionary.csv`, comment Oracle cho dữ liệu thật không? (nguồn domain
   rẻ nhất, benchmark hiện không có)
6. Tài liệu Copilot Studio đang nắm có cho trích dẫn ổn định (tên file + mục, đường dẫn SharePoint) không? Trích dẫn là
   điều kiện để Hub nhận đề xuất.
