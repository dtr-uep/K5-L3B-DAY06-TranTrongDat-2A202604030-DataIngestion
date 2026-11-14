# Đánh giá tính hữu dụng của metadata

Đánh giá trên 5 câu test cho mỗi chiến lược, mỗi câu lấy 3 kết quả. Các trường được kiểm tra gồm `source`, `page` và `section`, dựa trên nhãn trong [grounding_quality.json](grounding_quality.json) và kết quả trong [traces.json](traces.json).

| Chiến lược | Metadata đầy đủ và đúng | Top-3 tuân thủ filter trên test |
|---|---:|---:|
| A | 15/15 (100%) | 0/1 - không sử dụng |
| B | 15/15 (100%) | 0/1 - không sử dụng |
| C | 15/15 (100%) | 1/1 (100%) |

Trong phạm vi mẫu kiểm tra, metadata của cả ba chiến lược đều đầy đủ và đúng, chưa ghi nhận lỗi. `source` xác định tài liệu, `page` giúp tìm lại trang PDF để đối chiếu bằng chứng, còn `section` hỗ trợ giới hạn phạm vi truy xuất.

Với câu test `q20`, filter yêu cầu `section = Discussion`. C trả về cả 3 chunk thuộc mục Discussion và đưa đoạn chứa câu trả lời về truy xuất đa ngôn ngữ và xử lý đa phương thức lên hạng 1. A và B không áp dụng filter nên top-3 không đáp ứng điều kiện này. Như vậy, C tuân thủ filter trên câu test được kiểm tra.

