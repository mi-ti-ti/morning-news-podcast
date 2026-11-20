"""Unit tests for rss_builder.py"""

import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from morning_news_podcast import config, rss_builder


class TestRssBuilder(unittest.TestCase):
    def test_build_rss_feed_sorting_fallback_guid_and_xml_safety(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"

            # Legacy episode without published_at (must fall back to 05:00 JST, ignoring st_mtime)
            legacy_mp3 = ep_dir / "2026-11-19.mp3"
            legacy_mp3.write_bytes(b"FAKE-MP3-1")
            (ep_dir / "2026-11-19.json").write_text(
                json.dumps(
                    {
                        "title": "旧形式\x00タイトル",
                        "description": "説明\x0b本文",
                        "duration_sec": 600,
                    }
                ),
                encoding="utf-8",
            )
            # Set an arbitrarily newer mtime on legacy file to ensure mtime is NOT used
            future_ts = datetime(2026, 11, 25, 0, 0, tzinfo=rss_builder.JST).timestamp()
            os.utime(legacy_mp3, (future_ts, future_ts))

            # Same-day daily and extra episodes on 2026-11-20
            daily_mp3 = ep_dir / "2026-11-20.mp3"
            daily_mp3.write_bytes(b"FAKE-MP3-2")
            (ep_dir / "2026-11-20.json").write_text(
                json.dumps(
                    {
                        "title": "朝の通常回",
                        "description": "朝回説明",
                        "duration_sec": 610,
                        "published_at": "2026-11-20T05:00:00+09:00",
                    }
                ),
                encoding="utf-8",
            )

            extra_mp3 = ep_dir / "2026-11-20_extra-boj.mp3"
            extra_mp3.write_bytes(b"FAKE-MP3-3")
            (ep_dir / "2026-11-20_extra-boj.json").write_text(
                json.dumps(
                    {
                        "title": "昼の号外回",
                        "description": "号外説明",
                        "duration_sec": 240,
                        "published_at": "2026-11-20T12:30:00+09:00",
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
            ):
                rss_builder.build_rss_feed()

            xml_text = feed_path.read_text(encoding="utf-8")
            self.assertNotIn("\x00", xml_text)
            self.assertNotIn("\x0b", xml_text)

            root = ET.fromstring(xml_text)
            items = root.findall("./channel/item")
            self.assertEqual(len(items), 3)

            guids = [item.findtext("guid") for item in items]
            self.assertEqual(
                guids,
                [
                    "podcast-2026-11-20_extra-boj",
                    "podcast-2026-11-20",
                    "podcast-2026-11-19",
                ],
            )
            self.assertEqual(items[2].findtext("title"), "旧形式タイトル")
            self.assertEqual(items[2].findtext("description"), "説明本文")
            self.assertIn("05:00:00 +0900", items[2].findtext("pubDate"))

    def test_cleanup_old_episodes_by_jst_date(self):
        now_jst = datetime.now(rss_builder.JST)
        keep_date = (now_jst.date() - timedelta(days=21)).strftime("%Y-%m-%d")
        old_date = (now_jst.date() - timedelta(days=22)).strftime("%Y-%m-%d")

        with tempfile.TemporaryDirectory() as tmpdir:
            ep_dir = Path(tmpdir)
            for ep_id in (keep_date, old_date):
                (ep_dir / f"{ep_id}.mp3").write_bytes(b"MP3")
                (ep_dir / f"{ep_id}.json").write_text(
                    json.dumps({"title": ep_id}), encoding="utf-8"
                )
            # Old extra episode on old_date should also be removed
            (ep_dir / f"{old_date}_extra-old.mp3").write_bytes(b"MP3")
            (ep_dir / f"{old_date}_extra-old.json").write_text(
                json.dumps({"published_at": f"{old_date}T23:59:59+09:00"}),
                encoding="utf-8",
            )

            with patch.object(config, "EPISODES_DIR", ep_dir):
                rss_builder.cleanup_old_episodes(retention_days=21)

            self.assertTrue((ep_dir / f"{keep_date}.mp3").exists())
            self.assertTrue((ep_dir / f"{keep_date}.json").exists())
            self.assertFalse((ep_dir / f"{old_date}.mp3").exists())
            self.assertFalse((ep_dir / f"{old_date}.json").exists())
            self.assertFalse((ep_dir / f"{old_date}_extra-old.mp3").exists())
            self.assertFalse((ep_dir / f"{old_date}_extra-old.json").exists())

    def test_cleanup_old_episodes_respects_keep_forever_strictly(self):
        now_jst = datetime.now(rss_builder.JST)
        old_date = (now_jst.date() - timedelta(days=30)).strftime("%Y-%m-%d")
        recent_date = now_jst.date().strftime("%Y-%m-%d")

        with tempfile.TemporaryDirectory() as tmpdir:
            ep_dir = Path(tmpdir)

            # Protected old episode (keep_forever=True)
            protected_id = f"{old_date}_extra-series-1"
            (ep_dir / f"{protected_id}.mp3").write_bytes(b"MP3")
            (ep_dir / f"{protected_id}.json").write_text(
                json.dumps({"published_at": f"{old_date}T12:00:00+09:00", "keep_forever": True}),
                encoding="utf-8",
            )

            # Recent protected episode should NOT emit skip log
            recent_protected_id = f"{recent_date}_extra-series-2"
            (ep_dir / f"{recent_protected_id}.mp3").write_bytes(b"MP3")
            (ep_dir / f"{recent_protected_id}.json").write_text(
                json.dumps({"published_at": f"{recent_date}T12:00:00+09:00", "keep_forever": True}),
                encoding="utf-8",
            )

            # Non-protected old episodes: False, legacy omitted, "true" string, int 1, corrupted JSON
            unprotected_cases = [
                (f"{old_date}_extra-false", json.dumps({"keep_forever": False})),
                (f"{old_date}_extra-legacy", json.dumps({"title": "legacy"})),
                (f"{old_date}_extra-str", json.dumps({"keep_forever": "true"})),
                (f"{old_date}_extra-int", json.dumps({"keep_forever": 1})),
                (f"{old_date}_extra-corrupt", "{broken json"),
            ]
            for ep_id, content in unprotected_cases:
                (ep_dir / f"{ep_id}.mp3").write_bytes(b"MP3")
                (ep_dir / f"{ep_id}.json").write_text(content, encoding="utf-8")

            buf = io.StringIO()
            with patch.object(config, "EPISODES_DIR", ep_dir), redirect_stdout(buf):
                rss_builder.cleanup_old_episodes(retention_days=21)

            output = buf.getvalue()
            self.assertIn(f"[INFO] 保持保護 (keep_forever=True) のため削除をスキップ: {protected_id}.mp3", output)
            self.assertNotIn(recent_protected_id, output)

            self.assertTrue((ep_dir / f"{protected_id}.mp3").exists())
            self.assertTrue((ep_dir / f"{protected_id}.json").exists())
            self.assertTrue((ep_dir / f"{recent_protected_id}.mp3").exists())
            for ep_id, _ in unprotected_cases:
                self.assertFalse((ep_dir / f"{ep_id}.mp3").exists())
                self.assertFalse((ep_dir / f"{ep_id}.json").exists())

    def test_build_rss_feed_itunes_episode_and_same_timestamp_sorting(self):
        itunes_ep_tag = f"{{{rss_builder.ITUNES_NS}}}episode"
        itunes_ep_type_tag = f"{{{rss_builder.ITUNES_NS}}}episodeType"
        itunes_type_tag = f"{{{rss_builder.ITUNES_NS}}}type"

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"

            same_ts = "2026-11-20T20:00:00+09:00"
            entries = [
                ("2026-11-20_extra-series-2", {"title": "第2回", "duration_sec": 100, "published_at": same_ts, "series_episode_number": 2}),
                ("2026-11-20_extra-series-10", {"title": "第10回", "duration_sec": 100, "published_at": same_ts, "series_episode_number": 10}),
                ("2026-11-20_extra-series-1", {"title": "第1回", "duration_sec": 100, "published_at": same_ts, "series_episode_number": 1}),
                ("2026-11-20_extra-bool", {"title": "bool不正", "duration_sec": 100, "published_at": "2026-11-20T18:00:00+09:00", "series_episode_number": True}),
                ("2026-11-20_extra-zero", {"title": "0不正", "duration_sec": 100, "published_at": "2026-11-20T17:00:00+09:00", "series_episode_number": 0}),
                ("2026-11-20_extra-neg", {"title": "負数不正", "duration_sec": 100, "published_at": "2026-11-20T16:00:00+09:00", "series_episode_number": -1}),
                ("2026-11-20_extra-str", {"title": "文字列不正", "duration_sec": 100, "published_at": "2026-11-20T15:00:00+09:00", "series_episode_number": "3"}),
                ("2026-11-20", {"title": "通常回", "duration_sec": 200}),
            ]
            for ep_id, meta in entries:
                (ep_dir / f"{ep_id}.mp3").write_bytes(b"FAKE-MP3")
                (ep_dir / f"{ep_id}.json").write_text(json.dumps(meta), encoding="utf-8")

            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
            ):
                rss_builder.build_rss_feed()

            root = ET.fromstring(feed_path.read_text(encoding="utf-8"))
            channel = root.find("./channel")
            self.assertIsNone(channel.find(itunes_type_tag))

            items = root.findall("./channel/item")
            guids = [item.findtext("guid") for item in items]
            self.assertEqual(
                guids[:3],
                [
                    "podcast-2026-11-20_extra-series-10",
                    "podcast-2026-11-20_extra-series-2",
                    "podcast-2026-11-20_extra-series-1",
                ],
            )
            self.assertEqual(
                [item.findtext(itunes_ep_tag) for item in items],
                ["10", "2", "1", None, None, None, None, None],
            )
            for item in items:
                self.assertIsNone(item.find(itunes_ep_type_tag))


if __name__ == "__main__":
    unittest.main()
