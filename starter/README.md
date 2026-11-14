# Pipeline PDF → pgvector → retrieval A/B/C

Pipeline đọc `data/arxiv.pdf` và `benchmark/arxiv-questions.json` tính từ root repo. Sử dụng cùng model `sentence-transformers/all-MiniLM-L6-v2` cho ba cấu hình: A fixed-size 500 ký tự/overlap 50; B paragraph tối đa 700 ký tự; C dùng cùng chunk và embedding với B, chỉ thêm section filter khi câu hỏi cung cấp.

## Cài đặt lần đầu

Cần Python, Docker Desktop hoặc Docker Engine + Compose, và mạng để tải dependencies/model ở lần đầu. Môi trường đã dùng là Python 3.12. Các lệnh dưới đây chạy từ root repo bằng PowerShell:

```powershell
python -m venv starter/.venv
.\starter\.venv\Scripts\python.exe -m pip install -r starter/requirements.txt
Copy-Item starter/.env.example starter/.env
docker compose -p day6_student_starter -f starter/docker-compose.yml up -d --wait
.\starter\.venv\Scripts\python.exe starter/scripts/check_setup.py
```

Chỉ copy `.env.example` khi chưa có `.env`; giữ cấu hình local hiện có nếu đã setup. Không commit `.env`, API key hoặc `.venv`. Mặc định PostgreSQL dùng `127.0.0.1:55433` và mật khẩu cố định chỉ dành cho lab local. Nếu thay port, sửa đồng thời Compose và `DATABASE_URL`. `init.sql` chỉ chạy khi tạo volume mới; không xóa volume chứa dữ liệu để xử lý lỗi setup.

PDF có 36 trang vật lý, pipeline tính 33 trang nội dung. Nguồn, quyền dữ liệu, SHA-256, cách tải và thống kê từng trang nằm trong [manifest](data/manifest.yaml). Lưu PDF tại `data/arxiv.pdf` ở root repo, không phải `starter/data/arxiv.pdf`. Bộ câu hỏi và gold nằm trong [benchmark](../benchmark/arxiv-questions.json).

## Chạy benchmark

Chỉ cần chạy khi muốn ingest hoặc tạo lại kết quả:

```powershell
cd starter
.\.venv\Scripts\python.exe -m src.run
```

Pipeline tạo schema nếu cần, ghi vectors A/B/C, chạy cùng 20 câu và xuất top-3 cùng metrics. Bảng `day6_chunks` lưu bền vững trong Docker volume `pg_data`. Truy xuất exact theo cosine; chunk có `document_id`, `source`, `page` và `section`. Khi ingest lại một tài liệu, chunk cũ của tài liệu đó trong cùng chiến lược được thay trong một transaction.

Model chạy local, không cần API key; chi phí API là 0. Đầu vào vượt giới hạn token hoặc lỗi backend được báo lỗi; không fallback sang vector giả. `EMBEDDING_MODEL` trong `.env` có thể đổi model khi ingest, nhưng query phải dùng đúng model đã tạo vectors.

**Chạy benchmark sẽ ghi đè các file JSON kết quả và tạo lại nhãn audit trống.** Sao lưu bản đã chấm trước khi chạy. Chạy demo trên database đã có dữ liệu không cần chạy lại benchmark.

## Các file kết quả

| File trong `results/` | Nội dung |
|---|---|
| [traces.json](results/traces.json) | 60 lượt truy xuất: 20 câu × 3 cấu hình; chunk text, score, metadata, gold và nhãn evidence |
| [retrieval_accuracy.json](results/retrieval_accuracy.json) | Hit@1/Hit@3 dev/test, cấu hình, model, thống kê chunk và thời gian |
| [chunk_coherence.json](results/chunk_coherence.json) | Cùng 10 vị trí nguồn cho A/B/C; điểm coherence 0–2 và lý do |
| [grounding_quality.json](results/grounding_quality.json) | 5 câu test × 3 cấu hình; điểm grounding 0–2 và kiểm tra metadata |
| [metadata_usefulness.md](results/metadata_usefulness.md) | Tổng hợp metadata đủ/đúng, filter compliance, tác dụng và giới hạn |

Các mẫu JSON được code tạo, nhãn đánh giá được bổ sung sau. Báo cáo metadata Markdown và [experiment log](../artifacts/experiment_log.csv) được tổng hợp riêng; pipeline không cập nhật hai file này. Top-3 có thể ít hơn 3 khi filter không có đủ ứng viên. Phép đo `ingestion_and_chunking` hiện chỉ tính chunking, không gồm đọc PDF. Chưa lưu log lỗi của lần chạy được báo cáo.

## Chạy demo, không lưu query

Từ root repo:

```powershell
.\starter\.venv\Scripts\python.exe -B demo/app.py
```

Mở **http://127.0.0.1:8765**. Xem [demo/README.md](../demo/README.md) để biết các thao tác:

- Xem mọi câu benchmark và đối chiếu A/B/C từ kết quả đã lưu; không cần database.
- Nhập câu hỏi mới, chọn một hoặc cả ba cấu hình; chọn section nếu muốn C lọc. C không có filter sẽ tìm giống B.
- Xem top-3 chunk, cosine score, metadata và mở trang PDF. Không sinh câu trả lời LLM.

Truy vấn mới dùng database chỉ đọc và model của kết quả đã lưu; không thay vectors hay các file audit. Lịch sử query mới chỉ tồn tại trong phiên trình duyệt.

## Dừng database, giữ dữ liệu

Từ root repo:

```powershell
docker compose -p day6_student_starter -f starter/docker-compose.yml stop
```

Khởi động lại bằng lệnh `up -d --wait` ở phần setup; không cần ingest lại nếu volume vẫn còn.
