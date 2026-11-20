import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from morning_news_podcast.extra_log import append_extra_logs


class TestExtraLog(unittest.TestCase):
    def test_appends_only_extra_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log_path = tmp / "logs" / "extra_requests.jsonl"

            extra_path = tmp / "2026-11-20_extra-boj-rate.json"
            extra_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "episode_id": "2026-11-20_extra-boj-rate",
                        "episode_type": "extra",
                        "title": "【号外】日銀の追加利上げ観測",
                        "published_at": "2026-11-20T12:30:00+09:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            daily_path = tmp / "2026-11-20.json"
            daily_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "episode_id": "2026-11-20",
                        "episode_type": "daily",
                        "title": "2026年11月20日 | 通常回",
                        "published_at": "2026-11-20T05:00:00+09:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            utc_extra_path = tmp / "2026-11-21_extra-ai.json"
            utc_extra_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "episode_id": "2026-11-21_extra-ai",
                        "episode_type": "extra",
                        "title": "【号外】AI半導体動向",
                        "published_at": "2026-11-20T20:00:00Z",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            added = append_extra_logs(
                [extra_path, daily_path, utc_extra_path],
                log_path=log_path,
            )
            self.assertEqual(added, 2)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                json.loads(lines[0]),
                {
                    "date": "2026-11-20",
                    "episode_id": "2026-11-20_extra-boj-rate",
                    "title": "【号外】日銀の追加利上げ観測",
                },
            )
            self.assertEqual(
                json.loads(lines[1]),
                {
                    "date": "2026-11-21",
                    "episode_id": "2026-11-21_extra-ai",
                    "title": "【号外】AI半導体動向",
                },
            )

            added_again = append_extra_logs([extra_path, utc_extra_path], log_path=log_path)
            self.assertEqual(added_again, 0)
            self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_fallback_to_episode_id_date_when_published_at_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log_path = tmp / "logs" / "extra_requests.jsonl"

            extra_path = tmp / "2026-11-22_extra-no-pub.json"
            extra_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "episode_id": "2026-11-22_extra-no-pub",
                        "episode_type": "extra",
                        "title": "published_at 欠損テスト",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            added = append_extra_logs([extra_path], log_path=log_path)
            self.assertEqual(added, 1)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                json.loads(lines[0]),
                {
                    "date": "2026-11-22",
                    "episode_id": "2026-11-22_extra-no-pub",
                    "title": "published_at 欠損テスト",
                },
            )

    def test_raises_value_error_when_episode_id_or_title_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log_path = tmp / "logs" / "extra_requests.jsonl"

            empty_id_path = tmp / "empty_id.json"
            empty_id_path.write_text(
                json.dumps(
                    {
                        "episode_id": "   ",
                        "episode_type": "extra",
                        "title": "タイトルあり",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                append_extra_logs([empty_id_path], log_path=log_path)

            empty_title_path = tmp / "empty_title.json"
            empty_title_path.write_text(
                json.dumps(
                    {
                        "episode_id": "2026-11-20_extra-no-title",
                        "episode_type": "extra",
                        "title": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                append_extra_logs([empty_title_path], log_path=log_path)

    def test_skips_missing_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log_path = tmp / "logs" / "extra_requests.jsonl"
            missing_path = tmp / "does_not_exist.json"

            buf = io.StringIO()
            with redirect_stdout(buf):
                added = append_extra_logs([missing_path], log_path=log_path)

            self.assertEqual(added, 0)
            self.assertFalse(log_path.exists())
            self.assertIn("[WARN]", buf.getvalue())

    def test_skips_corrupted_jsonl_lines_safely_and_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log_path = tmp / "logs" / "extra_requests.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                '{"date": "2026-11-19", "episode_id": "2026-11-19_extra-ok", "title": "既存"}\n'
                "{broken json line\n"
                '"just a string"\n',
                encoding="utf-8",
            )

            existing_path = tmp / "2026-11-19_extra-ok.json"
            existing_path.write_text(
                json.dumps(
                    {
                        "episode_id": "2026-11-19_extra-ok",
                        "episode_type": "extra",
                        "title": "既存",
                        "published_at": "2026-11-19T12:00:00+09:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            new_path = tmp / "2026-11-20_extra-new.json"
            new_path.write_text(
                json.dumps(
                    {
                        "episode_id": "2026-11-20_extra-new",
                        "episode_type": "extra",
                        "title": "新規追加",
                        "published_at": "2026-11-20T12:00:00+09:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                added = append_extra_logs([existing_path, new_path], log_path=log_path)

            self.assertEqual(added, 1)
            output = buf.getvalue()
            self.assertIn("[WARN]", output)
            self.assertIn(":2", output)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(
                json.loads(lines[-1]),
                {
                    "date": "2026-11-20",
                    "episode_id": "2026-11-20_extra-new",
                    "title": "新規追加",
                },
            )

    def test_conditionally_records_series_fields_only_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            log_path = tmp / "logs" / "extra_requests.jsonl"

            series_path = tmp / "2026-11-20_extra-series-1.json"
            series_path.write_text(
                json.dumps(
                    {
                        "episode_id": "2026-11-20_extra-series-1",
                        "episode_type": "extra",
                        "title": "社会保障 第1回",
                        "published_at": "2026-11-20T20:00:00+09:00",
                        "series_id": "social-security",
                        "series_title": "日本の社会保障制度シリーズ",
                        "series_episode_number": 1,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            non_series_path = tmp / "2026-11-20_extra-plain.json"
            non_series_path.write_text(
                json.dumps(
                    {
                        "episode_id": "2026-11-20_extra-plain",
                        "episode_type": "extra",
                        "title": "通常の号外",
                        "published_at": "2026-11-20T21:00:00+09:00",
                        "series_id": "   ",
                        "series_episode_number": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            added = append_extra_logs([series_path, non_series_path], log_path=log_path)
            self.assertEqual(added, 2)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                json.loads(lines[0]),
                {
                    "date": "2026-11-20",
                    "episode_id": "2026-11-20_extra-series-1",
                    "title": "社会保障 第1回",
                    "series_id": "social-security",
                    "series_episode_number": 1,
                },
            )
            self.assertEqual(
                json.loads(lines[1]),
                {
                    "date": "2026-11-20",
                    "episode_id": "2026-11-20_extra-plain",
                    "title": "通常の号外",
                },
            )


if __name__ == "__main__":
    unittest.main()
