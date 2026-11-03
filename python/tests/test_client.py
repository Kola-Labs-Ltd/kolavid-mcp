"""The KolaVid Python client against a fake HTTP layer (and a loopback server for the urllib transport). Nothing here
reaches kolavid.com."""

from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kolavid  # noqa: E402
from kolavid import (  # noqa: E402
    Account,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InsufficientCreditsError,
    KolaVid,
    KolaVidError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    Response,
    ServerError,
    UrllibTransport,
    ValidationError,
    Video,
    VideoFailedError,
    VideoInProgressError,
    VideoNotReadyError,
    WaitTimeoutError,
)

KEY = "kv_live_test_0123456789abcdefghijklmnopqrstuvwx"
VID = "4d018ec2-1111-2222-3333-444455556666"
BASE = "https://kolavid.com/api/v1"


def video_body(status="completed", progress=100, **extra):
    body = {
        "id": VID, "status": status, "progress": progress, "title": "How vaccines work", "length_minutes": 2,
        "aspect_ratio": "16:9", "created_at": "2026-11-02T12:00:00Z",
        "completed_at": "2026-11-02T12:03:10Z" if status == "completed" else None,
        "video_url": f"https://kolavid.com/api/v1/files/{VID}/video?expires=1&sig=abc" if status == "completed" else None,
        "thumbnail_url": None, "share_url": None, "app_url": f"https://kolavid.com/app/jobs/{VID}", "error": None,
    }
    body.update(extra)
    return body


def answer(status=200, body=None, headers=None, raw=None):
    content = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    return Response(status, {k.lower(): v for k, v in (headers or {}).items()}, content)


class FakeTransport:
    """Answers each request with the next queued Response (or raises the next queued exception)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.closed = False

    def _next(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if not self.answers:
            raise AssertionError(f"unexpected request {method} {url}")
        item = self.answers.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def request(self, method, url, *, headers, body, timeout):
        return self._next(method, url, headers, body, timeout)

    def stream(self, method, url, *, headers, timeout, sink):
        item = self._next(method, url, headers, None, timeout)
        if 200 <= item.status_code < 300:
            sink.write(item.content)
            return Response(item.status_code, item.headers, b"")
        return item

    def close(self):
        self.closed = True


def client_with(*answers, **options):
    transport = FakeTransport(*answers)
    client = KolaVid(KEY, transport=transport, **options)
    client.sleeps = []
    client._sleep = client.sleeps.append
    return client, transport


class SetupTests(unittest.TestCase):
    def test_the_key_comes_from_the_environment_when_not_given(self):
        with mock.patch.dict(os.environ, {"KOLAVID_API_KEY": KEY}):
            transport = FakeTransport(answer(200, {"email": "a@b.c", "credits": 1, "plan": "free"}))
            KolaVid(transport=transport).me()
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], f"Bearer {KEY}")

    def test_no_key_is_a_clear_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(KolaVidError) as caught:
                KolaVid()
        self.assertIn("KOLAVID_API_KEY", str(caught.exception))

    def test_the_key_is_never_shown_in_full(self):
        client = KolaVid(KEY, transport=FakeTransport())
        self.assertNotIn(KEY, repr(client))
        self.assertIn("kv_live_", repr(client))

    def test_base_url_may_be_given_with_or_without_the_api_path(self):
        for base in ("http://localhost:8000", "http://localhost:8000/", "http://localhost:8000/api/v1"):
            client = KolaVid(KEY, base_url=base, transport=FakeTransport())
            self.assertEqual(client._url("/me"), "http://localhost:8000/api/v1/me")
        with mock.patch.dict(os.environ, {"KOLAVID_BASE_URL": "https://staging.example.test"}):
            self.assertEqual(KolaVid(KEY, transport=FakeTransport()).base_url, "https://staging.example.test")

    def test_context_manager_closes_the_transport(self):
        transport = FakeTransport()
        with KolaVid(KEY, transport=transport):
            pass
        self.assertTrue(transport.closed)


class RequestTests(unittest.TestCase):
    def test_create_sends_the_fields_and_the_sdk_headers(self):
        created = {"id": VID, "status": "queued", "created_at": "2026-11-02T12:00:00Z",
                   "app_url": f"https://kolavid.com/app/jobs/{VID}", "status_url": f"{BASE}/videos/{VID}"}
        client, transport = client_with(answer(201, created))
        video = client.videos.create(prompt="How vaccines work, for 12-year-olds", length_minutes=2,
                                     aspect_ratio="9:16", voice="Kore", language="Spanish")
        call = transport.calls[0]
        self.assertEqual((call["method"], call["url"]), ("POST", f"{BASE}/videos"))
        self.assertEqual(json.loads(call["body"]), {
            "prompt": "How vaccines work, for 12-year-olds", "length_minutes": 2, "aspect_ratio": "9:16",
            "voice": "Kore", "language": "Spanish"})
        headers = call["headers"]
        self.assertEqual(headers["User-Agent"], f"kolavid-python/{kolavid.__version__}")
        self.assertEqual(headers["X-KolaVid-Client"], "sdk-python")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")
        self.assertIsInstance(video, Video)
        self.assertEqual((video.id, video.status, video.status_url), (VID, "queued", f"{BASE}/videos/{VID}"))
        self.assertEqual(video.created_at, datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        self.assertIsNone(video.video_url)

    def test_create_with_text_or_a_link_leaves_out_what_was_not_given(self):
        client, transport = client_with(answer(201, {"id": VID, "status": "queued"}),
                                        answer(201, {"id": VID, "status": "queued"}))
        client.videos.create(text="An article.")
        client.videos.create(source_url="https://example.com/post", extra_body={"future_field": True})
        self.assertEqual(json.loads(transport.calls[0]["body"]),
                         {"text": "An article.", "length_minutes": 1, "aspect_ratio": "16:9"})
        self.assertEqual(json.loads(transport.calls[1]["body"]), {
            "source_url": "https://example.com/post", "length_minutes": 1, "aspect_ratio": "16:9",
            "future_field": True})

    def test_create_with_nothing_to_explain_is_refused_before_any_request(self):
        client, transport = client_with()
        with self.assertRaises(ValueError):
            client.videos.create(prompt="   ")
        self.assertEqual(transport.calls, [])

    def test_get_parses_a_finished_video_and_keeps_unknown_fields(self):
        client, transport = client_with(answer(200, video_body(new_field="kept")))
        video = client.videos.get(VID)
        self.assertEqual(transport.calls[0]["url"], f"{BASE}/videos/{VID}")
        self.assertTrue(video.is_completed and video.is_finished and not video.is_failed)
        self.assertEqual(video.completed_at, datetime(2026, 11, 2, 12, 3, 10, tzinfo=timezone.utc))
        self.assertEqual(video.length_minutes, 2)
        self.assertEqual(video.raw["new_field"], "kept")

    def test_ids_are_escaped_and_a_video_object_works_as_an_id(self):
        client, transport = client_with(answer(200, video_body()), answer(200, video_body()))
        client.videos.get("a/b?c")
        client.videos.get(Video(id=VID, status="queued"))
        self.assertEqual(transport.calls[0]["url"], f"{BASE}/videos/a%2Fb%3Fc")
        self.assertEqual(transport.calls[1]["url"], f"{BASE}/videos/{VID}")

    def test_list_sends_limit_and_status(self):
        client, transport = client_with(answer(200, {"videos": [video_body(), video_body("making", 40)]}),
                                        answer(200, {"videos": []}))
        videos = client.videos.list(limit=5, status="completed")
        self.assertEqual(transport.calls[0]["url"], f"{BASE}/videos?limit=5&status=completed")
        self.assertEqual([v.status for v in videos], ["completed", "making"])
        self.assertEqual(client.videos.list(), [])
        self.assertEqual(transport.calls[1]["url"], f"{BASE}/videos?limit=25")

    def test_me_is_the_account(self):
        client, _ = client_with(answer(200, {"email": "you@example.com", "credits": 4880, "plan": "starter"}))
        account = client.me()
        self.assertEqual(account, Account(email="you@example.com", credits=4880.0, plan="starter"))

    def test_fractional_seconds_of_any_length_parse_on_old_pythons(self):
        from kolavid._types import parse_time

        self.assertEqual(parse_time("2026-11-02T12:00:00.12Z").microsecond, 120000)
        self.assertEqual(parse_time("2026-11-02T12:00:00.123456789+00:00").microsecond, 123456)
        self.assertIsNone(parse_time("not a time"))
        self.assertIsNone(parse_time(None))


class ErrorTests(unittest.TestCase):
    def raised(self, *answers, call=lambda c: c.me(), **options):
        client, transport = client_with(*answers, **options)
        with self.assertRaises(KolaVidError) as caught:
            call(client)
        return caught.exception, transport, client

    def test_401_is_an_authentication_error(self):
        error, _, _ = self.raised(answer(401, {"detail": "Invalid or missing API key. Send Authorization: Bearer kv_live_..."}))
        self.assertIsInstance(error, AuthenticationError)
        self.assertEqual(error.status_code, 401)
        self.assertIn("Invalid or missing API key", error.message)

    def test_402_has_the_pricing_page(self):
        body = {"detail": "Not enough credits.", "error": "insufficient_credits", "pricing_url": "https://kolavid.com/pricing"}
        error, transport, _ = self.raised(answer(402, body), call=lambda c: c.videos.create(prompt="x"))
        self.assertIsInstance(error, InsufficientCreditsError)
        self.assertEqual((error.code, error.pricing_url), ("insufficient_credits", "https://kolavid.com/pricing"))
        self.assertEqual(len(transport.calls), 1)

    def test_403_404_and_500_kinds(self):
        self.assertIsInstance(self.raised(answer(403, {"detail": "Closed."}))[0], PermissionDeniedError)
        self.assertIsInstance(self.raised(answer(404, {"detail": "Video not found."}),
                                          call=lambda c: c.videos.get("nope"))[0], NotFoundError)
        error = self.raised(answer(500, raw=b"<html>oops</html>"), max_retries=0)[0]
        self.assertIsInstance(error, ServerError)
        self.assertEqual(error.message, "<html>oops</html>")

    def test_422_field_problems_are_details(self):
        body = {"detail": [{"loc": ["body", "length_minutes"], "msg": "Input should be less than or equal to 5",
                            "type": "less_than_equal"}]}
        error, _, _ = self.raised(answer(422, body), call=lambda c: c.videos.create(prompt="x", length_minutes=9))
        self.assertIsInstance(error, ValidationError)
        self.assertEqual(error.details[0]["loc"], ["body", "length_minutes"])
        self.assertEqual(error.message, "length_minutes: Input should be less than or equal to 5")

    def test_422_with_a_sentence_has_no_details(self):
        error, _, _ = self.raised(answer(422, {"detail": "This link can't be read.", "error": "invalid_request"}),
                                  call=lambda c: c.videos.create(source_url="https://example.com"))
        self.assertIsInstance(error, ValidationError)
        self.assertEqual((error.details, error.code), ([], "invalid_request"))

    def test_a_rate_limit_is_waited_out_as_retry_after_says(self):
        client, transport = client_with(answer(429, {"detail": "Too many requests."}, {"Retry-After": "7"}),
                                        answer(200, {"email": "a@b.c", "credits": 0, "plan": "free"}))
        self.assertEqual(client.me().email, "a@b.c")
        self.assertEqual(client.sleeps, [7.0])
        self.assertEqual(len(transport.calls), 2)

    def test_a_create_is_retried_after_the_per_key_rate_limit(self):
        client, transport = client_with(answer(429, {"detail": "Too many requests."}, {"Retry-After": "2"}),
                                        answer(201, {"id": VID, "status": "queued"}))
        self.assertEqual(client.videos.create(prompt="x").id, VID)
        self.assertEqual(client.sleeps, [2.0])

    def test_rate_limit_after_the_last_retry_is_raised_with_retry_after(self):
        error, transport, client = self.raised(*[answer(429, {"detail": "Too many requests."}, {"Retry-After": "3"})] * 3)
        self.assertIsInstance(error, RateLimitError)
        self.assertEqual(error.retry_after, 3.0)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(client.sleeps, [3.0, 3.0])

    def test_a_retry_after_too_long_to_wait_is_raised_at_once(self):
        error, transport, _ = self.raised(answer(429, {"detail": "Slow down."}, {"Retry-After": "3600"}))
        self.assertIsInstance(error, RateLimitError)
        self.assertEqual(len(transport.calls), 1)

    def test_another_video_being_made_is_not_retried(self):
        body = {"detail": "You already have a video in progress. Wait for it to finish before starting another.",
                "error": "rate_limited"}
        error, transport, _ = self.raised(answer(429, body), call=lambda c: c.videos.create(prompt="x"))
        self.assertIsInstance(error, VideoInProgressError)
        self.assertIsInstance(error, RateLimitError)
        self.assertIsNone(error.retry_after)
        self.assertEqual(len(transport.calls), 1)

    def test_server_errors_and_dropped_connections_are_retried_for_reads(self):
        client, transport = client_with(answer(503), APIConnectionError("reset"),
                                        answer(200, {"email": "a@b.c", "credits": 1, "plan": "free"}))
        self.assertEqual(client.me().plan, "free")
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(len(client.sleeps), 2)
        self.assertTrue(all(0 < s <= 8 for s in client.sleeps))

    def test_a_create_is_never_sent_twice_when_it_may_have_made_a_video(self):
        for first in (answer(500, {"detail": "boom"}), answer(502), answer(504), APITimeoutError("slow"),
                      APIConnectionError("x")):
            client, transport = client_with(first, answer(201, {"id": VID, "status": "queued"}))
            with self.assertRaises(KolaVidError):
                client.videos.create(prompt="x")
            self.assertEqual(len(transport.calls), 1, first)

    def test_a_create_is_retried_when_the_api_is_unavailable(self):
        client, transport = client_with(answer(503, {"detail": "Links can't be read right now."}), answer(201, {"id": VID, "status": "queued"}))
        self.assertEqual(client.videos.create(prompt="x").status, "queued")
        self.assertEqual(len(transport.calls), 2)

    def test_max_retries_zero_asks_once(self):
        error, transport, _ = self.raised(answer(503), max_retries=0)
        self.assertIsInstance(error, ServerError)
        self.assertEqual(len(transport.calls), 1)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class WaitTests(unittest.TestCase):
    def client(self, *answers):
        client, transport = client_with(*answers)
        clock = FakeClock()
        client._clock, client._sleep = clock, clock.sleep
        return client, transport, clock

    def test_wait_polls_until_completed(self):
        client, transport, clock = self.client(answer(200, video_body("queued", 0)),
                                               answer(200, video_body("making", 50)),
                                               answer(200, video_body("completed", 100)))
        seen = []
        video = client.videos.wait(VID, poll_interval=10, on_progress=lambda v: seen.append(v.progress))
        self.assertEqual(video.status, "completed")
        self.assertEqual(seen, [0, 50, 100])
        self.assertEqual(clock.now, 1020.0)
        self.assertEqual(len(transport.calls), 3)

    def test_a_failed_video_is_returned_with_its_reason(self):
        client, _, _ = self.client(answer(200, video_body("failed", 100, error="Stopped before it was finished.")))
        video = client.videos.wait(VID)
        self.assertTrue(video.is_failed)
        self.assertEqual(video.error, "Stopped before it was finished.")

    def test_wait_gives_up_after_the_timeout(self):
        client, transport, clock = self.client(*[answer(200, video_body("making", 30))] * 10)
        with self.assertRaises(WaitTimeoutError) as caught:
            client.videos.wait(VID, poll_interval=5, timeout=12)
        self.assertEqual(caught.exception.video.progress, 30)
        self.assertEqual(clock.now, 1012.0)
        self.assertEqual(len(transport.calls), 4)

    def test_a_poll_interval_must_be_positive(self):
        client, _, _ = self.client()
        with self.assertRaises(ValueError):
            client.videos.wait(VID, poll_interval=0)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = Path(self.folder.name)

    def test_download_saves_the_mp4_without_sending_the_key(self):
        client, transport = client_with(answer(200, video_body()), answer(200, raw=b"MP4DATA"))
        saved = client.videos.download(VID, self.dir / "out" / "vaccines.mp4")
        self.assertEqual(saved.read_bytes(), b"MP4DATA")
        file_call = transport.calls[1]
        self.assertEqual(file_call["url"], video_body()["video_url"])
        self.assertNotIn("Authorization", file_call["headers"])
        self.assertEqual(file_call["headers"]["X-KolaVid-Client"], "sdk-python")
        self.assertEqual(sorted(p.name for p in saved.parent.iterdir()), ["vaccines.mp4"])

    def test_download_into_a_folder_names_the_file_after_the_video(self):
        client, _ = client_with(answer(200, video_body()), answer(200, raw=b"X"))
        self.assertEqual(client.videos.download(VID, self.dir), self.dir / f"kolavid-{VID}.mp4")

    def test_an_expired_link_is_asked_for_again_once(self):
        fresh = video_body(video_url="https://kolavid.com/api/v1/files/x/video?expires=2&sig=new")
        client, transport = client_with(answer(200, video_body()), answer(404, {"detail": "This link has expired."}),
                                        answer(200, fresh), answer(200, raw=b"NEW"))
        saved = client.videos.download(VID, self.dir / "v.mp4")
        self.assertEqual(saved.read_bytes(), b"NEW")
        self.assertEqual(transport.calls[3]["url"], fresh["video_url"])

    def test_a_video_still_being_made_or_failed_is_not_downloaded(self):
        client, transport = client_with(answer(200, video_body("making", 40)))
        with self.assertRaises(VideoNotReadyError) as caught:
            client.videos.download(VID, self.dir / "v.mp4")
        self.assertEqual(caught.exception.video.progress, 40)
        client, _ = client_with(answer(200, video_body("failed", 100, error="Could not finish.")))
        with self.assertRaises(VideoFailedError) as failed:
            client.videos.download(VID, self.dir / "v.mp4")
        self.assertIn("Could not finish.", str(failed.exception))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_broken_download_leaves_no_file_behind(self):
        client, _ = client_with(answer(200, video_body()), *[APIConnectionError("reset")] * 3)
        with self.assertRaises(APIConnectionError):
            client.videos.download(VID, self.dir / "v.mp4")
        self.assertEqual(list(self.dir.iterdir()), [])


class _FakeAPI(http.server.BaseHTTPRequestHandler):
    """A tiny stand-in for the API on 127.0.0.1, to test the standard library transport for real."""

    seen: list = []

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", headers=None, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).seen.append((self.command, self.path, dict(self.headers)))
        port = self.server.server_address[1]
        if self.path == "/api/v1/me":
            self._send(200, json.dumps({"email": "a@b.c", "credits": 60, "plan": "creator"}).encode())
        elif self.path == f"/api/v1/videos/{VID}":
            body = video_body(video_url=f"http://127.0.0.1:{port}/api/v1/files/{VID}/video?sig=1")
            self._send(200, json.dumps(body).encode())
        elif self.path.startswith(f"/api/v1/files/{VID}/video"):
            self._send(302, headers={"Location": f"http://127.0.0.1:{port}/storage/v.mp4"})
        elif self.path == "/storage/v.mp4":
            self._send(200, b"\x00\x01" * 300_000, content_type="video/mp4")
        else:
            self._send(404, json.dumps({"detail": "Video not found.", "error": "not_found"}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).seen.append((self.command, self.path, dict(self.headers), body))
        self._send(402, json.dumps({"detail": "Not enough credits.", "error": "insufficient_credits",
                                    "pricing_url": "https://kolavid.com/pricing"}).encode())


class UrllibTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeAPI)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _FakeAPI.seen = []
        self.client = KolaVid(KEY, base_url=self.base, transport=UrllibTransport(), max_retries=0)

    def test_a_real_round_trip_and_headers(self):
        self.assertEqual(self.client.me().plan, "creator")
        _, path, headers = _FakeAPI.seen[0]
        self.assertEqual(path, "/api/v1/me")
        self.assertEqual(headers["User-Agent"], f"kolavid-python/{kolavid.__version__}")
        self.assertEqual(headers["X-Kolavid-Client"], "sdk-python")

    def test_error_bodies_are_read_from_http_errors(self):
        with self.assertRaises(InsufficientCreditsError) as caught:
            self.client.videos.create(prompt="A topic")
        self.assertEqual(caught.exception.pricing_url, "https://kolavid.com/pricing")
        self.assertEqual(json.loads(_FakeAPI.seen[0][3]), {"prompt": "A topic", "length_minutes": 1,
                                                           "aspect_ratio": "16:9"})
        with self.assertRaises(NotFoundError):
            self.client.videos.get("missing")

    def test_download_streams_through_a_redirect_without_the_key(self):
        with tempfile.TemporaryDirectory() as folder:
            saved = self.client.videos.download(VID, folder)
            self.assertEqual(saved.stat().st_size, 600_000)
        file_requests = [entry for entry in _FakeAPI.seen if "/files/" in entry[1] or "/storage/" in entry[1]]
        self.assertEqual(len(file_requests), 2)
        for _, _, headers in file_requests:
            self.assertNotIn("Authorization", headers)

    def test_nothing_listening_is_a_connection_error(self):
        client = KolaVid(KEY, base_url="http://127.0.0.1:9", transport=UrllibTransport(), max_retries=0, timeout=2)
        with self.assertRaises(APIConnectionError):
            client.me()


try:
    import httpx
except ImportError:  # pragma: no cover - httpx is optional
    httpx = None


@unittest.skipIf(httpx is None, "httpx is not installed")
class HttpxTransportTests(unittest.TestCase):
    def test_requests_errors_and_streams_through_httpx(self):
        seen = []

        def handler(request):
            seen.append(request)
            if request.url.path == "/api/v1/me":
                return httpx.Response(429, json={"detail": "Too many requests."}, headers={"Retry-After": "1"}) \
                    if len(seen) == 1 else httpx.Response(200, json={"email": "a@b.c", "credits": 5, "plan": "free"})
            if request.url.path == f"/api/v1/videos/{VID}":
                return httpx.Response(200, json=video_body(video_url="https://files.example.test/v.mp4"))
            if request.url.host == "files.example.test":
                return httpx.Response(200, content=b"httpx-mp4")
            return httpx.Response(404, json={"detail": "Video not found."})

        transport = kolavid.HttpxTransport(httpx.Client(transport=httpx.MockTransport(handler)))
        client = KolaVid(KEY, transport=transport)
        client._sleep = lambda seconds: None
        self.assertEqual(client.me().credits, 5.0)
        self.assertEqual(seen[0].headers["x-kolavid-client"], "sdk-python")
        with self.assertRaises(NotFoundError):
            client.videos.get("nope")
        with tempfile.TemporaryDirectory() as folder:
            saved = client.videos.download(VID, Path(folder) / "v.mp4")
            self.assertEqual(saved.read_bytes(), b"httpx-mp4")
        self.assertNotIn("authorization", seen[-1].headers)


class PackageTests(unittest.TestCase):
    def test_the_version_matches_the_changelog(self):
        changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()
        self.assertIn(f"## {kolavid.__version__}", changelog)

    def test_retry_after_dates_are_read(self):
        from kolavid._errors import parse_retry_after

        self.assertEqual(parse_retry_after("5"), 5.0)
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT"), 0.0)
        self.assertIsNone(parse_retry_after("soon"))
        self.assertIsNone(parse_retry_after(None))


if __name__ == "__main__":
    unittest.main()
