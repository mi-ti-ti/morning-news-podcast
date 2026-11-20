import json
import tempfile
import unittest
from pathlib import Path

from extra_log import append_extra_logs


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


if __name__ == "__main__":
    unittest.main()
