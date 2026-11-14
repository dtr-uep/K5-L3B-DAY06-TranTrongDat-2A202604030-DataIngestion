# Chạy demo

Từ thư mục gốc repo:

```powershell
.\starter\.venv\Scripts\python.exe -B demo/app.py
```

Mở **http://127.0.0.1:8765**. Giữ terminal đang chạy; nhấn `Ctrl+C` để dừng.

Để thử query mới, khởi động database nếu đang dừng:

```powershell
docker compose -p day6_student_starter -f starter/docker-compose.yml up -d --wait
```

Nếu cổng 8765 đang bận:

```powershell
.\starter\.venv\Scripts\python.exe -B demo/app.py --port 8766
```

Sau đó mở **http://127.0.0.1:8766**.
