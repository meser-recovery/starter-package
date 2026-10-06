"""Network failure and publication regressions; no production API calls."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import build_na_html as build


def response(payload=None, status=200):
    result = Mock()
    result.status_code = status
    result.headers = {}
    result.json.return_value = payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class RetryTests(unittest.TestCase):
    def test_timeout_then_success(self):
        with patch.object(build.HTTP, "get", side_effect=[
            requests.Timeout("temporary"), response({"results": []})
        ]) as get, patch.object(build.time, "sleep"):
            self.assertEqual(build.get_json("https://example.test"), {"results": []})
            self.assertEqual(get.call_count, 2)
            self.assertEqual(get.call_args.kwargs["timeout"], (10, 20))

    def test_transient_http_errors_retry(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status), patch.object(build.HTTP, "get", side_effect=[
                response(status=status), response({"ok": True})
            ]) as get, patch.object(build.time, "sleep"):
                self.assertEqual(build.get_json("https://example.test"), {"ok": True})
                self.assertEqual(get.call_count, 2)

    def test_permanent_http_error_does_not_retry(self):
        with patch.object(build.HTTP, "get", return_value=response(status=404)) as get, \
                patch.object(build.time, "sleep"):
            with self.assertRaises(requests.HTTPError):
                build.get_json("https://example.test")
            self.assertEqual(get.call_count, 1)

    def test_persistent_connection_error_fails_after_three_attempts(self):
        with patch.object(build.HTTP, "get", side_effect=requests.ConnectionError("offline")) as get, \
                patch.object(build.time, "sleep") as sleep:
            with self.assertRaises(requests.ConnectionError):
                build.get_json("https://example.test")
            self.assertEqual(get.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 1, 4, 1])

    def test_rate_limit_waits_for_retry_after(self):
        limited = response(status=429)
        limited.headers = {"Retry-After": "45"}
        with patch.object(build.HTTP, "get", side_effect=[limited, response({})]), \
                patch.object(build.time, "sleep") as sleep:
            self.assertEqual(build.get_json("https://example.test"), {})
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 45, 1])

    def test_long_rate_limit_fails_for_next_backup_run(self):
        limited = response(status=429)
        limited.headers = {"Retry-After": "3600"}
        with patch.object(build.HTTP, "get", return_value=limited) as get, \
                patch.object(build.time, "sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                build.get_json("https://example.test")
            self.assertEqual(get.call_count, 1)
            sleep.assert_called_once_with(1)

    def test_invalid_json_is_retried(self):
        invalid = response()
        invalid.json.side_effect = ValueError("invalid JSON")
        with patch.object(build.HTTP, "get", side_effect=[invalid, response({})]), \
                patch.object(build.time, "sleep"):
            self.assertEqual(build.get_json("https://example.test"), {})


class PaginationTests(unittest.TestCase):
    def test_all_pages_are_loaded_with_original_date(self):
        with patch.object(build, "get_json", side_effect=[
            {"results": [{"id": 1}], "next": "https://example.test/page2"},
            {"results": [{"id": 2}], "next": None},
        ]) as get:
            self.assertEqual(build.get_meetings_for_town(10, "2026-10-06"), [{"id": 1}, {"id": 2}])
            self.assertEqual(get.call_args_list[0].kwargs["params"]["exact_date"], "2026-10-06")
            self.assertIsNone(get.call_args_list[1].kwargs["params"])

    def test_repeated_page_fails_instead_of_looping(self):
        with patch.object(build, "get_json", return_value={
            "results": [], "next": f"{build.API_BASE}/scheduled-meetings/merged/"
        }) as get:
            with self.assertRaisesRegex(RuntimeError, "повторяет страницу"):
                build.get_meetings_for_town(10, "2026-10-06")
            self.assertEqual(get.call_count, 1)

    def test_malformed_response_is_not_treated_as_empty_schedule(self):
        for payload in ({}, {"results": None}, []):
            with self.subTest(payload=payload), patch.object(build, "get_json", return_value=payload):
                with self.assertRaisesRegex(RuntimeError, "Некорректный ответ"):
                    build.get_meetings_for_town(10, "2026-10-06")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_directory = os.getcwd()
        os.chdir(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(os.chdir, self.previous_directory)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(build, "CUSTOM_DATE", "2026-10-06"))
        self.stack.enter_context(patch.object(build, "PRINT_CITIES", False))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.output = Path("na_meetings_live.html")
        self.output.write_text("previous complete list", encoding="utf-8")
        self.city = {"id": 1, "name": "Москва"}
        self.meeting = {"online": False, "group": {"id": 1, "name": "Группа", "location": {"town_id": 1}}}

    def test_city_failure_preserves_previous_file(self):
        with patch.object(build, "load_cities", return_value=[self.city, {"id": 2, "name": "Другой"}]), \
                patch.object(build, "get_meetings_for_town", side_effect=[[self.meeting], requests.Timeout("offline")]):
            with self.assertRaisesRegex(RuntimeError, "Другой"):
                build.main()
        self.assertEqual(self.output.read_text(), "previous complete list")

    def test_empty_response_preserves_previous_file(self):
        with patch.object(build, "load_cities", return_value=[self.city]), \
                patch.object(build, "get_meetings_for_town", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "не вернул живых собраний"):
                build.main()
        self.assertEqual(self.output.read_text(), "previous complete list")

    def test_complete_build_gets_marker_and_backup_skips(self):
        with patch.object(build, "load_cities", return_value=[self.city]), \
                patch.object(build, "get_meetings_for_town", return_value=[self.meeting]):
            build.main()
        html = self.output.read_text()
        self.assertIn("РФ, на 2026-10-06", html)
        self.assertIn("<!-- na-meetings-complete: 2026-10-06 -->", html)
        with patch.object(build, "build_data", return_value=({}, {}, {})) as data:
            build.main(skip_if_current=True)
            data.assert_not_called()
            build.main()  # Manual execution still forces a refresh.
            data.assert_called_once()

    def test_old_date_or_missing_marker_does_not_skip(self):
        for html in ("<!-- na-meetings-complete: 2026-10-05 -->", "РФ, на 2026-10-06"):
            self.output.write_text(html)
            with patch.object(build, "build_data", side_effect=RuntimeError("build attempted")):
                with self.assertRaisesRegex(RuntimeError, "build attempted"):
                    build.main(skip_if_current=True)

    def test_atomic_replace_failure_preserves_previous_file(self):
        with patch.object(build, "build_data", return_value=({}, {}, {})), \
                patch.object(build, "build_html", return_value="new list"), \
                patch.object(Path, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                build.main()
        self.assertEqual(self.output.read_text(), "previous complete list")
        self.assertFalse(Path("na_meetings_live.html.tmp").exists())

    def test_online_filter_external_sites_and_real_town_preserved(self):
        cities = [self.city, {"id": 2, "name": "Внешний", "redirect_url": "https://example.test"}]
        meeting = {"online": False, "group": {"location": {"town_id": 3}}}
        with patch.object(build, "load_cities", return_value=cities), \
                patch.object(build, "get_meetings_for_town", return_value=[meeting, {"online": True}]) as get:
            meetings, _, external = build.build_data("2026-10-06")
        self.assertEqual(meetings, {3: [meeting]})
        self.assertEqual(external, {2: "https://example.test"})
        get.assert_called_once_with(1, "2026-10-06")

    def test_cities_cache_fallback(self):
        Path("cities.json").write_text('{"towns": [{"id": 1, "name": "Москва"}]}', encoding="utf-8")
        with patch.object(build, "get_json", side_effect=requests.ConnectionError("offline")):
            self.assertEqual(build.load_cities(), [self.city])

    def test_empty_api_does_not_replace_valid_city_cache(self):
        Path("cities.json").write_text('{"towns": [{"id": 1, "name": "Москва"}]}', encoding="utf-8")
        with patch.object(build, "get_json", return_value={"towns": []}):
            self.assertEqual(build.load_cities(), [self.city])


if __name__ == "__main__":
    unittest.main()
