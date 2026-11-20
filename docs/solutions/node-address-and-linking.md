# Địa chỉ node và cách người / AI nối hệ thống

Mục tiêu: mỗi node có **một địa chỉ ngắn, đọc được** (Hệ thống › Loại › Tên). Người và AI chỉ cần viết địa chỉ đó
(hoặc gần đúng) là code map tìm ra node, nối link, và giữ link khi code đổi.

## 1. Hiện trạng (đo trên graph mẫu `benchmark-data/all-systems`, 2.792 node)

| Điều | Hiện nay | Hệ quả |
|---|---|---|
| Id node | `api-operation:eshop-on-web-web:api-operation:…:ManageController.cs:10983:11611:…` | Không ai đọc / gõ được. Có vị trí byte, file, project → đổi khi sửa code |
| Tên ngắn `loại: tên` (ref) | `method: Basket.AddItem` | Đã có, nhưng **289 tên bị trùng** (784 node) nên không dùng làm khoá được |
| Tìm node từ tên (AI import, MCP) | chỉ khớp **chính xác**, trùng hay sai một chữ → "không tìm thấy node" | AI phải chép id dài, hoặc link bị bỏ |
| Link sau khi extract lại | lưu `source_ref`/`target_ref` nhưng **không dùng lại** | id đổi → link hiện "node không còn trong graph", phải nối tay lại |
| Ô tìm node trên web | tìm theo tên, hiện loại + đường dẫn | Người chọn được, nhưng không biết node nào "đúng" khi trùng tên |

Thử ghép **Hệ thống + Loại + Tên đầy đủ** (namespace.class.method, package.procedure; bỏ file, dòng, project):

| | Số khoá | Trùng |
|---|---|---|
| Tên ngắn (Class.method) | 2.286 | 278 khoá |
| **Tên đầy đủ** (không tính file, config key, placeholder) | 1.138 | 85 khoá |
| — trong đó do **overload** (khác tham số) | | 24 |
| — trong đó là **cùng một code bị extract hai lần** (project dùng chung `ApplicationCore` thuộc 2 application) | | 61 |

Nghĩa là: tên đầy đủ **đã gần như duy nhất**. Phần trùng còn lại là overload (xử lý được bằng chữ ký) và một lỗi
extractor (node trùng lặp, đáng gộp lại chứ không phải tách ra).

Hai lỗi extractor tìm thấy thêm khi đo:
- **Route MVC theo quy ước** (`{controller}/{action}`): 21 action của `ManageController` cùng route `GET /Manage` →
  thiếu tên action trong route.
- **740/2.792 node là placeholder** (`UNRESOLVED_REFERENCE`): phần lớn là cột (`DEPARTMENT_ID`), hàm có sẵn của
  Oracle (`DBMS_XMLDOM.MAKENODE`), biến cục bộ (`L_RESULT.OBJECTS.EXISTS`). Đây là nhiễu, che mất chỗ hở thật.

## 2. Giải pháp: địa chỉ node

```
<hệ thống> › <loại> › <tên đầy đủ>[(chữ ký)]
```

| Loại | Ví dụ địa chỉ |
|---|---|
| table | `ORDER_DB › table › APP.T_ORDER` |
| procedure | `ORDER_DB › procedure › PKG_ORDER.CREATE_ORDER` |
| method | `order-api › method › Shop.Data.OrderRepository.Save` |
| method overload | `order-api › method › Shop.Data.OrderRepository.Save(Order,bool)` |
| api | `order-api › api › POST /api/orders` |
| screen | `order-web › screen › /orders` |
| ui-action | `order-web › ui-action › OrderListComponent.click.onSearch` |
| job | `batch › job › JN_DAILY.J_ORDER` |

Quy tắc:
1. **Hệ thống** là tên logic khai một lần trong config (không lấy từ đường dẫn repo / tên .csproj).
2. **Tên đầy đủ** là tên người dùng khi nói về code. File, dòng, project là *vị trí*, chỉ để mở code, không nằm
   trong địa chỉ.
3. **Chữ ký** chỉ thêm khi có overload. Trùng thật còn lại (hiếm) thêm `#2` và extractor báo issue.
4. Code dùng chung nhiều application (project `ApplicationCore`) → **một node**, ghi các application dùng nó.

Địa chỉ được lưu thành một cột của node (`address`), duy nhất trong graph. Id cũ giữ nguyên lúc đầu để không phải
migrate; sau này mới đổi id sang địa chỉ (hoặc hash của nó).

## 3. Gõ gần đúng vẫn ra node

Một bộ tìm dùng chung cho AI (MCP, file import) và người (ô tìm trên web). Thử lần lượt, dừng ở bậc đầu tiên ra
**đúng một** node:

| Bậc | Người / AI viết | Khớp với |
|---|---|---|
| 1 | `order-api › method › Shop.Data.OrderRepository.Save` | địa chỉ đầy đủ |
| 2 | `method: Shop.Data.OrderRepository.Save` | bỏ hệ thống |
| 3 | `OrderRepository.Save`, `Save` + gợi ý hệ thống / loại | phần cuối tên đầy đủ |
| 4 | `注文登録`, `Create order` | tên nghiệp vụ (ja/en), thuật ngữ, từ điển |
| 5 | `OrderRepo.save`, `PKG_ORDER.CREATE_ODER` | gần đúng: bỏ hoa thường, `_`/`-`, sai 1–2 ký tự |

Kết quả luôn là một trong ba:
- **Khớp** (một node): dùng luôn. Kèm câu "khớp ở bậc 3 theo `OrderRepository.Save`" để người đọc biết vì sao.
- **Nhiều ứng viên**: trả tối đa 5, mỗi cái có địa chỉ + lý do (cùng hệ thống, cùng luồng, gần trong graph).
  Ứng viên **cùng luồng / cạnh node nguồn** xếp trên. AI chọn lại bằng địa chỉ, người bấm chọn. Không ghi gì khi
  chưa chọn.
- **Không có**: nói rõ "ngoài phạm vi đã quét" hay "có thể là tên khác trong code", gợi ý `codemap_search`.

Nối link cũng kiểm tra *có hợp lý không* trước khi ghi: READS / WRITES chỉ tới bảng, API call tới API, gọi
sang hệ thống khác ghi rõ trong ghi chú.

## 4. Chỗ hở → gợi ý link

Code map đã biết chỗ nào thiếu cạnh: API call không khớp API (có `near_misses`), class DI không bind, placeholder
bảng / procedure. Gom thành danh sách **chỗ hở**, mỗi chỗ có ứng viên từ bộ tìm ở mục 3:

```
order-web › api_call › GET /gw/api/orders/{id}   (không khớp, khác tiền tố /gw ≠ /svc)
  → ứng viên: order-api › api › GET /svc/api/orders/{id}   [Nối]  [Không phải]
```

- **Người**: trang "Chỗ hở" trong Code map, bấm *Nối* là thành link (ghi người nối); *Không phải* ẩn chỗ hở đó.
- **AI**: tool `codemap_knowledge_gaps` (đã có trên nhánh KB) trả cùng danh sách. AI nối bằng địa chỉ, link ghi
  "AI thêm", người thấy ngay và xoá được.
- Placeholder nhiễu (cột, hàm Oracle có sẵn, biến cục bộ) bị lọc khỏi danh sách để chỗ hở thật nổi lên.

## 5. Link không mất khi code đổi

Mỗi link lưu **địa chỉ** hai đầu (thay ref như bây giờ). Sau mỗi lần extract:
1. id còn → giữ.
2. id mất, địa chỉ còn → gắn lại vào node mới, im lặng (code dời file / dời dòng).
3. địa chỉ cũng mất → bộ tìm bậc 2–5 với địa chỉ cũ. Ra một node → gắn lại, đánh dấu **"Code đã đổi"** để người xem.
4. Vẫn không ra → mục "Link mất node" kèm ứng viên, người chọn lại hoặc xoá. Không tự xoá.

## 6. Lộ trình

| Bước | Ở đâu | Việc | Được gì |
|---|---|---|---|
| 1 | viewer-hub | Một bộ tìm (gộp `resolve.py` của nhánh KB với resolver của file import), thêm bậc 3–5, lý do khớp, ứng viên theo luồng | AI gõ gần đúng vẫn nối được; import không bỏ link |
| 2 | viewer-hub | Gắn lại link / ghi chú theo ref đã lưu (mục 5, dùng ref trước khi có địa chỉ) | Extract lại không làm rơi link |
| 3 | code-map | Cột `address` cho mọi node + issue khi trùng | Địa chỉ duy nhất, ngắn, ổn định |
| 4 | code-map | Gộp node code dùng chung; route MVC có action; lọc placeholder nhiễu | Bớt 61 cặp trùng, 21 API sai, ~700 placeholder nhiễu |
| 5 | viewer-hub | Trang "Chỗ hở" + nút *Nối* / *Không phải*; ô tìm hiện địa chỉ và lý do | Người nối nhanh, cùng danh sách với AI |
| 6 | cả hai | (sau) đổi id node sang địa chỉ, migration một lần | Bỏ hẳn id dài |

Bước 1–2 không cần extract lại, làm được ngay. Bước 3–4 cần chạy lại extractor trên máy PROD (pack không mang ra
được), nên phần đo trùng (`diagnose`) phải in số khoá trùng theo địa chỉ để kiểm trên máy đó.

### Trạng thái

- **Bước 1 xong**: `viewer_hub/codemap/business/resolve.py` (`NameIndex`): địa chỉ tính ngay trong Viewer Hub từ
  `qualified_name`, 5 bậc, lý do khớp, ứng viên. Dùng ở file nhập từ AI (`ai_exchange`) và tool MCP ghi quy tắc / câu hỏi /
  quyết định (`write_tools._node_ids`). Nhánh KB (`claude/infallible-keller-524f8c`) có `mcp/resolve.py` riêng dựa trên
  search index: khi gộp nhánh, cho `codemap_resolve` và các tool `propose_*` dùng chung `NameIndex`.
- **Bước 2 xong**: link lưu địa chỉ ở `source_ref` / `target_ref`; `links.relink` chạy khi nạp link (`apply_links`) với
  node đã mất id, chỉ nhận bậc 1–3; bảng mới `kn.biz_link_moves` giữ dấu "Code đã đổi" tới khi người bấm **Vẫn đúng**.
  Bậc 4–5 chỉ hiện làm ứng viên cho người chọn.
