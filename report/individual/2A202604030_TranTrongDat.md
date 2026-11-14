# Báo cáo cá nhân — Data Ingestion Engineering

## Dữ liệu và pipeline

Corpus là bài báo *Developing Retrieval Augmented Generation (RAG) based LLM Systems from PDFs: An Experience Report*, arXiv:2410.15944v1. PDF có 36 trang vật lý; tính 33 trang nội dung từ trang 2 đến 34, loại trang tiêu đề/tóm tắt, tài liệu tham khảo và phụ lục. Nội dung sau chuẩn hóa có 63.870 ký tự. Nguồn, SHA-256, cách lấy, số ký tự từng trang và quy tắc đếm được ghi trong [manifest](../../starter/data/manifest.yaml). PDF được tải trực tiếp từ arXiv; các bước tải và lưu file tại `data/arxiv.pdf` được ghi trong manifest.

Pipeline dùng PyMuPDF để trích xuất từng trang theo thứ tự đọc, chuẩn hóa Unicode NFC, khoảng trắng và xuống dòng, đồng thời bỏ số trang ở đầu/cuối. Không dùng OCR; cả 36 trang có text trích xuất được. Việc chia chunk theo từng trang vẫn giữ các câu bị ngắt ở ranh giới trang. Heading được nhận diện bằng định dạng chữ đậm nên có thể bỏ sót hoặc nhận diện sai cấu trúc.

Embedding chạy local bằng Sentence Transformers với model `sentence-transformers/all-MiniLM-L6-v2`, 384 chiều, giới hạn 256 token. Query và document dùng cùng model, vector được chuẩn hóa; đầu vào vượt giới hạn được báo lỗi thay vì âm thầm cắt. Phiên bản model chưa được cố định bằng revision trong code. Chi phí API là 0 USD; chưa đo điện năng hoặc khấu hao thiết bị.

Vector store là PostgreSQL 16.16 với pgvector 0.8.7, tìm kiếm exact theo cosine. Docker lưu dữ liệu trong volume `pg_data`, bảng `day6_chunks` phân biệt từng chiến lược. Khi nạp lại, code xóa chunk của các tài liệu đang nạp trong cùng chiến lược rồi ghi lại trong một transaction, tránh giữ chunk cũ của tài liệu đó. Tài liệu bị loại hẳn khỏi corpus cần được dọn riêng.

Các trường `document_id`, `source` và `page` hỗ trợ truy nguồn. `section` là chuỗi lấy từ heading, được dùng để lọc theo phạm vi nội dung. Một chunk có thể đi qua nhiều heading nhưng chỉ mang nhãn section tại vị trí bắt đầu.

Lệnh chạy từ thư mục `starter/`, sau khi cài dependencies và cấu hình `.env` theo [hướng dẫn setup](../../starter/README.md):

```powershell
docker compose -p day6_student_starter up -d --wait
.\.venv\Scripts\python.exe scripts/check_setup.py
.\.venv\Scripts\python.exe -m src.run
```

Lệnh benchmark tạo lại các file đánh giá với nhãn trống, vì vậy cần lưu bản audit đã chấm trước khi chạy lại. Dependencies được khai báo trong [requirements.txt](../../starter/requirements.txt); một số thư viện dùng khoảng phiên bản nên môi trường chưa được khóa hoàn toàn.

## Cấu hình và benchmark

| Chiến lược | Chunking | Filter |
|---|---|---|
| A | Fixed-size 500 ký tự, overlap 50 ký tự | Không |
| B | Gom đoạn, tối đa 700 ký tự; đoạn quá dài được tách tiếp; không overlap | Không |
| C | Dùng cùng chunk và embedding với B | Lọc `section` khi câu hỏi cung cấp filter |

A–B kiểm tra thay đổi cấu hình chunking, bao gồm cả kích thước và overlap; không tách riêng ảnh hưởng của từng tham số. B–C chỉ thay việc áp dụng filter. C không tự suy luận section từ câu hỏi tự do; câu không có filter được tìm kiếm như B.

[Benchmark](../../benchmark/arxiv-questions.json) gồm 20 câu, chia 15 dev (`q01`–`q15`) và 5 test (`q16`–`q20`). Có 4 câu filter, trong đó `q20` thuộc test. Mỗi câu lưu đáp án kỳ vọng, nguồn, trang và evidence quote. Code kiểm tra evidence xuất hiện trên trang nguồn sau chuẩn hóa; sự khớp chuỗi không tự chứng minh evidence đủ hỗ trợ toàn bộ đáp án.

Dev chủ yếu lấy nội dung ở các trang đầu và test ở các trang 26, 32, 34; cùng một tài liệu nên vẫn có nguy cơ trùng chủ đề và cách diễn đạt. Nhật ký cấu hình và giả thuyết được điền sau khi chạy. Chưa có minh chứng ghi tiêu chí lựa chọn trước khi xem test, vì vậy kết quả test được dùng để mô tả thí nghiệm, không coi là đánh giá độc lập của một quyết định chọn cấu hình đã chốt trước đó.

## Kết quả

### 1. Retrieval accuracy

Một hit yêu cầu đúng nguồn/trang và đủ evidence trong một chunk. Các tỷ lệ dưới đây được tính từ cùng benchmark và định nghĩa metric.

| Chiến lược | Split | Hit@1 | Evidence Hit@3 | Số chunk | Thời gian embedding tài liệu | Chi phí API |
|---|---|---:|---:|---:|---:|---:|
| A | Dev | 8/15 | 9/15 | 154 | 2,1783 giây | 0 USD |
| A | Test | 1/5 | 2/5 | 154 | 2,1783 giây | 0 USD |
| B | Dev | 8/15 | 10/15 | 135 | 2,0331 giây | 0 USD |
| B | Test | 2/5 | 4/5 | 135 | 2,0331 giây | 0 USD |
| C | Dev | 8/15 | 10/15 | 135 | 0 giây tính thêm; tái sử dụng B | 0 USD |
| C | Test | 3/5 | 5/5 | 135 | 0 giây tính thêm; tái sử dụng B | 0 USD |

Thời gian embedding là theo cấu hình, không phải hai lần chạy riêng cho dev và test. Lần chạy được ghi nhận lúc 10:54:36 ngày 14/11/2026 (UTC+7). Các phép đo dùng chung gồm chunking 0,0018 giây, ghi database 0,2757 giây, embedding query và search 1,5905 giây. Trường `ingestion_and_chunking` trong kết quả thực tế chỉ đo chunking, không bao gồm đọc PDF; thời gian search chưa tách theo chiến lược.

### 2–4. Coherence, metadata usefulness và grounding quality

Coherence dùng cùng vị trí đầu trang trên 10 trang nội dung đầu tiên (PDF 2–11), mỗi vị trí chọn một chunk cho mỗi chiến lược. Thang 0–2 đánh giá khả năng hiểu độc lập và giữ trọn ý. B và C có cùng text nên cùng nhãn.

Grounding đánh giá chung top-3 của cùng 5 câu test: 0 = không có bằng chứng, 1 = có nhưng chưa đủ, 2 = đủ trả lời và truy nguồn. Đây là chất lượng evidence retrieval, không phải độ chính xác câu trả lời LLM.

| Chiến lược | Coherence trung bình /2 | Metadata đủ và đúng | Tuân thủ filter trên test | Grounding: số câu mức 0 / 1 / 2 | Grounding trung bình /2 |
|---|---:|---:|---:|---|---:|
| A | 1,1 (10 mẫu) | 15/15 | 0/1 | 2 / 1 / 2 | 1,0 |
| B | 1,4 (10 mẫu) | 15/15 | 0/1 | 1 / 0 / 4 | 1,6 |
| C | 1,4 (10 mẫu) | 15/15 | 1/1 | 0 / 0 / 5 | 2,0 |

Metadata được tổng hợp từ nhãn kiểm tra `source`, `page`, `section` trên 45 bản ghi test, chưa ghi nhận lỗi theo các nhãn hiện có. `source` và `page` giúp tìm lại bằng chứng; `section` giúp C giới hạn phạm vi. Với `q20`, C chỉ trả kết quả thuộc Discussion và tìm được câu trả lời ở rank 1. A/B không áp dụng filter, nên không đạt điều kiện section của câu này. Metadata đúng không bảo đảm kết quả liên quan; test chỉ có một câu filter nên khả năng khái quát còn hạn chế.

Minh chứng:

- [Trace đầy đủ](../../starter/results/traces.json) và [retrieval accuracy](../../starter/results/retrieval_accuracy.json).
- [Mẫu và nhãn coherence](../../starter/results/chunk_coherence.json).
- [Nhãn grounding và metadata từng bản ghi](../../starter/results/grounding_quality.json).
- [Phân tích metadata usefulness](../../starter/results/metadata_usefulness.md).
- [Nhật ký thí nghiệm](../../artifacts/experiment_log.csv).

## 5. Data strategy impact và kết luận

So với A, B giảm 19 chunk, từ 154 xuống 135 (khoảng 12,3%). Tổng token chunk giảm từ 15.429 xuống 13.977; một phần chênh lệch đến từ overlap của A. Evidence Hit@3 tăng từ 9/15 lên 10/15 trên dev và từ 2/5 lên 4/5 trên test. Coherence tăng từ 1,1 lên 1,4/2, nhưng các đoạn quá dài và câu nối qua trang vẫn có thể bị cắt.

C giữ nguyên chunk và embedding của B, nên không cải thiện coherence. Filter giúp thay đổi phạm vi search ở những câu có điều kiện. Trên test, C tăng Evidence Hit@3 từ 4/5 lên 5/5; trên dev, B và C cùng đạt 10/15. Filter chỉ có tác dụng khi giá trị section được cung cấp đúng và metadata phản ánh đúng phạm vi.

Hai trường hợp lỗi cụ thể:

- **`q16`, A:** câu hỏi yêu cầu tên embedding model trong ví dụ FAISS và các tác vụ tương ứng, bằng chứng ở `data/arxiv.pdf`, trang 26. Top-3 của A ở các trang 29, 2, 9 chỉ nói về embedding hoặc RAG nói chung. B/C tìm được đoạn nêu model và tác vụ tại rank 1.
- **`q18`, A:** bằng chứng về lỗi sao chép code từ PDF ở trang 32. Rank 1 của A bị cắt tại `copying from PDF file gene`, thiếu phần giải thích lỗi; hai rank còn lại không bổ sung đủ. Vì vậy grounding đạt 1 dù Evidence Hit@3 là 0. B/C giữ đoạn giải thích ở rank 3 và đạt grounding 2.

Trong phạm vi corpus và mẫu đã đo, C phù hợp khi có section filter đáng tin; khi không có filter, C có hành vi như B. B là cấu hình tìm kiếm không lọc có kết quả tốt hơn A trong thí nghiệm này. Không kết luận C tốt nhất cho mọi corpus hoặc câu hỏi.

Đánh giá sử dụng ChatGPT/Codex để hỗ trợ rà soát code, đề xuất nhãn và tổng hợp kết quả; không dùng mô hình để sinh câu trả lời trong benchmark. Nhãn coherence và grounding có hỗ trợ AI, còn metadata có phần kiểm tra của tác giả; chưa có người chấm độc lập và vẫn cần tác giả rà soát nhãn. Nguy cơ thiên lệch gồm đã xem điểm retrieval trước khi chấm, chỉ chọn chunk đầu trang, một PDF và tập test nhỏ.

Nếu mở rộng, cần chốt tiêu chí chọn trên dev trước khi xem test mới, tăng số câu filter, cải thiện nhận diện heading và xử lý câu nối trang, bổ sung lỗi evidence bị tách giữa nhiều chunk, khóa phiên bản model/thư viện và đo thời gian từng giai đoạn theo từng chiến lược. Hồ sơ hiện chưa có log lỗi lưu từ lần chạy được báo cáo.
