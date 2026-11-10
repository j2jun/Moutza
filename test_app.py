"""Run: python3 -m unittest -v"""
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import app


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


class MoutzaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        handler = type("H", (app.Handler,), {"db_path": cls.db, "log_message": lambda *a: None})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.remove(cls.db)

    def req(self, path, form=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        try:
            with opener.open(self.base + path, data) as r:
                return r.status, r.read().decode(), r.headers
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.read().decode(), err.headers

    def post(self, **form):
        return self.req("/add", form)

    def test_add_view_search_similar(self):
        status, _, h = self.post(title="Merit Scholarship Guide", url="https://example.edu/aid",
                                 school="State U", tags="scholarship, financial aid",
                                 description="How to apply for merit scholarships.")
        self.assertEqual(status, 303)
        self.post(title="Need-based grants", url="https://example.edu/grants", school="State U",
                  tags="financial aid", description="Grants and scholarship deadlines.")
        self.post(title="Robotics Club", url="https://club.example.org", school="Tech Institute",
                  tags="club, engineering", description="Weekly build nights.")

        status, body, _ = self.req(h["Location"])
        self.assertEqual(status, 200)
        self.assertIn("Merit Scholarship Guide", body)
        similar = body.split("Pinned nearby")[1]
        self.assertIn("Need-based grants", similar)
        self.assertNotIn("Robotics Club", similar)

        _, body, _ = self.req("/?q=scholarship")
        self.assertLess(body.index("Merit Scholarship Guide"), body.index("Need-based grants"))
        self.assertNotIn("Robotics Club", body)

        _, body, _ = self.req("/?school=Tech+Institute")
        self.assertIn("Robotics Club", body)
        self.assertNotIn("Merit Scholarship Guide", body)

    def test_random_redirects_to_a_flyer(self):
        self.post(title="Any", url="https://a.b", school="s")
        status, _, h = self.req("/random")
        self.assertEqual(status, 303)
        self.assertRegex(h["Location"], r"^/r/\d+$")

    def test_rejects_bad_input(self):
        for form in ({"title": "x", "url": "javascript:alert(1)", "school": "s"},
                     {"title": "", "url": "https://a.b", "school": "s"},
                     {"title": "x" * 201, "url": "https://a.b", "school": "s"}):
            status, _, _ = self.post(**form)
            self.assertEqual(status, 400, form)

    def test_escapes_html(self):
        _, _, h = self.post(title="<script>alert(1)</script>", url="https://a.b/?x=\"><b>", school="<i>S</i>")
        _, body, _ = self.req(h["Location"])
        self.assertNotIn("<script>alert", body)
        self.assertNotIn("<i>S</i>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_not_found_and_too_large(self):
        self.assertEqual(self.req("/r/99999")[0], 404)
        self.assertEqual(self.req("/nope")[0], 404)
        self.assertEqual(self.post(description="x" * (app.MAX_BODY + 1))[0], 413)


if __name__ == "__main__":
    unittest.main()
