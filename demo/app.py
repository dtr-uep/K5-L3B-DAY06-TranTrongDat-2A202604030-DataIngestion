"""Local, read-only retrieval demo. Run with the starter virtual environment."""
import argparse
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
RESULTS = ROOT / "starter" / "results"
sys.path.insert(0, str(ROOT / "starter"))
MODEL_LOCK = threading.Lock()
EMBEDDER = None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def saved_data():
    benchmark = read_json(ROOT / "benchmark" / "arxiv-questions.json")
    traces = read_json(RESULTS / "traces.json")
    metrics = read_json(RESULTS / "retrieval_accuracy.json")
    return {"questions": benchmark["questions"], "traces": traces, "metrics": metrics}


def database_url():
    import os
    from dotenv import load_dotenv
    from psycopg.conninfo import make_conninfo

    load_dotenv(ROOT / "starter" / ".env")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("Thiếu DATABASE_URL trong starter/.env.")
    return make_conninfo(url, connect_timeout=5, options="-c default_transaction_read_only=on")


def sections():
    import psycopg

    with psycopg.connect(database_url()) as connection:
        rows = connection.execute(
            "SELECT DISTINCT metadata->>'section' FROM day6_chunks "
            "WHERE strategy = 'C' AND metadata->>'section' IS NOT NULL ORDER BY 1"
        ).fetchall()
    return [row[0] for row in rows]


def query(payload):
    global EMBEDDER
    question = payload.get("question", "")
    strategy = payload.get("strategy", "all")
    section = payload.get("section", "")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("Nhập câu hỏi từ 1 đến 2.000 ký tự.")
    if strategy not in ("all", "A", "B", "C"):
        raise ValueError("Chọn A, B, C hoặc cả ba cấu hình.")
    if not isinstance(section, str) or len(section) > 200:
        raise ValueError("Section không hợp lệ.")
    from src.embeddings import MyEmbedder
    from src.store import PgVectorStore
    import psycopg

    metrics = read_json(RESULTS / "retrieval_accuracy.json")
    model_name = metrics["embedding"]["model"]
    url = database_url()
    selected = ["A", "B", "C"] if strategy == "all" else [strategy]
    # Validate the stored index before loading the model or embedding a query.
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT strategy, count(*), min(vector_dims(embedding)), "
            "max(vector_dims(embedding)) FROM day6_chunks "
            "WHERE strategy = ANY(%s) GROUP BY strategy", (selected,)
        ).fetchall()
    counts = {row[0]: row for row in rows}
    for name in selected:
        if name not in counts:
            raise ValueError(f"Database chưa có dữ liệu cho cấu hình {name}.")
        if counts[name][2:] != (metrics["embedding"]["dimensions"],) * 2:
            raise ValueError("Số chiều vector trong database không khớp model của kết quả đã lưu.")
    if section and "C" in selected and section not in sections():
        raise ValueError("Section không tồn tại trong cấu hình C.")
    started = time.perf_counter()
    with MODEL_LOCK:
        if EMBEDDER is None:
            EMBEDDER = MyEmbedder(model_name)
        if EMBEDDER.model_name != model_name:
            raise ValueError("Model đã thay đổi. Khởi động lại app để tải đúng model.")
        vector = EMBEDDER.embed_query(question.strip())
    store = PgVectorStore(url, EMBEDDER.dimensions)
    results = []
    for name in selected:
        filters = {"section": section} if name == "C" and section else None
        hits = store.search(name, vector, top_k=3, filters=filters)
        results.append({"strategy": name, "filter": filters,
                        "hits": [dict(hit, rank=rank) for rank, hit in enumerate(hits, 1)]})
    return {"question": question.strip(), "results": results,
            "seconds": round(time.perf_counter() - started, 3), "model": model_name}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        try:
            if route == "/api/saved":
                return self.reply(200, saved_data())
            if route == "/api/sections":
                return self.reply(200, {"sections": sections()})
            if route == "/document.pdf":
                return self.reply(200, (ROOT / "data" / "arxiv.pdf").read_bytes(), "application/pdf")
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if route in assets:
                name, mime = assets[route]
                return self.reply(200, (STATIC / name).read_bytes(), mime)
            self.reply(404, {"error": "Không tìm thấy đường dẫn."})
        except FileNotFoundError:
            self.reply(404, {"error": "Thiếu file dữ liệu. Kiểm tra benchmark/, starter/results/ và data/arxiv.pdf."})
        except Exception:
            self.reply(503, {"error": "Không đọc được dữ liệu. Kiểm tra Docker, starter/.env và bảng day6_chunks. Chế độ kết quả đã lưu không cần database."})

    def do_POST(self):
        if urlparse(self.path).path != "/api/query":
            return self.reply(404, {"error": "Không tìm thấy đường dẫn."})
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}",
                   f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed:
            return self.reply(403, {"error": "Chỉ nhận yêu cầu từ giao diện local."})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(415, {"error": "Yêu cầu phải dùng JSON."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16000:
                raise ValueError("Nội dung yêu cầu không hợp lệ.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Yêu cầu phải là một JSON object.")
            self.reply(200, query(payload))
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
        except Exception:
            self.reply(503, {"error": "Chưa truy xuất được. Kiểm tra Docker, DATABASE_URL, model local và kết nối tải model ở lần đầu. Không có kết quả giả lập."})

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Demo: http://127.0.0.1:{server.server_port}", flush=True)
    print("Nhan Ctrl+C de dung. Query moi khong duoc luu.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
