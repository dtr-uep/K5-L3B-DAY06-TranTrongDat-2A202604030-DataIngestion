"""HTTP contract checks; no model loading, ingestion, or database writes."""
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app


class DemoHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, payload=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(self.url + path, data=data, headers=headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_saved_results_available_without_embedding_or_database(self):
        status, _, body = self.request("/api/saved")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(len(data["questions"]), 20)
        self.assertEqual(len(data["traces"]), 60)
        for question in data["questions"]:
            traces = [trace for trace in data["traces"] if trace["question_id"] == question["id"]]
            self.assertEqual({trace["strategy"] for trace in traces}, {"A", "B", "C"})
        self.assertIsNone(app.EMBEDDER)

    def test_static_assets_and_pdf(self):
        for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"),
                           ("/style.css", "text/css"), ("/document.pdf", "application/pdf")):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(mime, headers["Content-Type"])
                self.assertTrue(body)

    def test_only_allowlisted_files_are_served(self):
        for path in ("/../starter/.env", "/starter/.env", "/app.py", "/.git/config"):
            self.assertEqual(self.request(path)[0], 404)

    def test_invalid_queries_rejected_before_model_loading(self):
        for payload in ({"question": ""}, {"question": "x", "strategy": "D"},
                        {"question": "x", "section": []}, ["not an object"],
                        {"question": "x" * 2001}):
            with self.subTest(payload=str(payload)[:70]):
                self.assertEqual(self.request("/api/query", payload)[0], 400)
        self.assertIsNone(app.EMBEDDER)

    def test_foreign_origin_rejected(self):
        self.assertEqual(self.request("/api/query", {"question": "hello"},
                                      {"Origin": "https://example.org"})[0], 403)


if __name__ == "__main__":
    unittest.main()
