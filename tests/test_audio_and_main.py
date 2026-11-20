"""Unit tests for audio_generator.py and main.py"""

import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydub import AudioSegment

from morning_news_podcast import audio_generator, config, rss_builder
from morning_news_podcast import main as main_module
from morning_news_podcast.schema import DialogueTurn
from morning_news_podcast.script_generator import PodcastPartScript


def _silent_wav_bytes(duration_ms: int = 100) -> bytes:
    buf = io.BytesIO()
    AudioSegment.silent(duration=duration_ms).export(buf, format="wav")
    return buf.getvalue()


class TestAudioGenerator(unittest.TestCase):
    def test_build_episode_mp3_one_and_two_parts(self):
        wav_bytes = _silent_wav_bytes(100)
        fake_synth = MagicMock()
        fake_synth.create_audio_query.return_value = MagicMock()
        fake_synth.synthesis.return_value = wav_bytes

        turns1 = [DialogueTurn(speaker="ずんだもん", text="パート1なのだ。")]
        turns2 = [DialogueTurn(speaker="春日部つむぎ", text="パート2だよ。")]

        with tempfile.TemporaryDirectory() as tmpdir:
            out_1 = Path(tmpdir) / "one_part.mp3"
            out_2 = Path(tmpdir) / "two_parts.mp3"

            with patch.object(audio_generator, "_init_synthesizer", return_value=fake_synth):
                with patch.object(AudioSegment, "export") as mock_export:
                    dur1 = audio_generator.build_episode_mp3([turns1], out_1)
                    dur2 = audio_generator.build_episode_mp3([turns1, turns2], out_2)

        self.assertEqual(mock_export.call_count, 2)
        self.assertGreaterEqual(dur2, dur1)
        # 1 part = ~100ms (0s); 2 parts = 100ms + 800ms + 100ms = 1000ms (1s)
        self.assertEqual(dur1, 0)
        self.assertEqual(dur2, 1)


class TestMainFromScript(unittest.TestCase):
    def test_from_script_skips_gemini_uses_episode_id_and_formats_metadata(self):
        now_jst = datetime.now(main_module.JST)
        ep_date = now_jst.strftime("%Y-%m-%d")
        ep_id = f"{ep_date}_extra-boj-rate"

        script_payload = {
            "schema_version": 1,
            "episode_id": ep_id,
            "episode_type": "extra",
            "title": "【号外】日銀の追加利上げ観測",
            "published_at": f"{ep_date}T12:30:00+09:00",
            "weekly_theme": None,
            "keyword_of_the_day": None,
            "exclude_from_context": True,
            "parts": [
                {
                    "part_title": "日銀の利上げ観測を深掘り",
                    "summary_bullets": ["背景の解説", "住宅ローンへの影響"],
                    "turns": [
                        {"speaker": "ずんだもん", "text": "号外なのだ！"},
                        {"speaker": "春日部つむぎ", "text": "詳しく見ていくよ。"},
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "docs"
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"

            # Intentionally name input file differently from episode_id
            script_file = root / "arbitrary_filename.json"
            script_file.write_text(
                json.dumps(script_payload, ensure_ascii=False), encoding="utf-8"
            )

            def fake_build_mp3(parts, output_mp3_path):
                output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
                output_mp3_path.write_bytes(b"FAKE-MP3")
                return 185

            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module.genai, "Client", side_effect=AssertionError("Must not call genai.Client")),
                patch.object(main_module, "build_episode_mp3", side_effect=fake_build_mp3) as mock_build,
                patch.object(sys, "argv", ["main.py", "--from-script", str(script_file)]),
            ):
                main_module.main()

                self.assertEqual(mock_build.call_count, 1)
                expected_mp3 = ep_dir / f"{ep_id}.mp3"
                expected_meta = ep_dir / f"{ep_id}.json"
                self.assertTrue(expected_mp3.exists())
                self.assertTrue(expected_meta.exists())
                self.assertFalse((ep_dir / "arbitrary_filename.mp3").exists())

                meta = json.loads(expected_meta.read_text(encoding="utf-8"))
                self.assertEqual(meta["title"], "【号外】日銀の追加利上げ観測")
                self.assertEqual(meta["duration_sec"], 185)
                self.assertEqual(meta["episode_type"], "extra")
                self.assertTrue(meta["exclude_from_context"])
                self.assertEqual(meta["published_at"], f"{ep_date}T12:30:00+09:00")
                self.assertNotIn("None", meta["description"])
                self.assertNotIn("【本日のテーマ】", meta["description"])
                self.assertNotIn("【第1部：経済ニュース】", meta["description"])
                self.assertIn("【日銀の利上げ観測を深掘り】", meta["description"])
                self.assertTrue(feed_path.exists())

                # Second run without --force must skip synthesis
                mock_build.reset_mock()
                main_module.main()
                self.assertEqual(mock_build.call_count, 0)

                # Third run with --force must re-synthesize
                with patch.object(
                    sys, "argv", ["main.py", "--from-script", str(script_file), "--force"]
                ):
                    main_module.main()
                self.assertEqual(mock_build.call_count, 1)


class TestMainDailyMode(unittest.TestCase):
    def test_daily_mode_generates_two_part_script_and_metadata(self):
        now_jst = datetime.now(main_module.JST)
        date_str = now_jst.strftime("%Y-%m-%d")

        part1 = PodcastPartScript(
            part_title="経済トピック",
            summary_bullets=["経済の要約1"],
            keyword_of_the_day=None,
            turns=[DialogueTurn(speaker="ずんだもん", text="第1部なのだ。")],
        )
        part2 = PodcastPartScript(
            part_title="ビジネストピック",
            summary_bullets=["ビジネスの要約1"],
            keyword_of_the_day="プライシングパワー",
            turns=[DialogueTurn(speaker="春日部つむぎ", text="第2部だよ。")],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "docs"
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"

            def fake_build_mp3(parts, output_mp3_path):
                self.assertEqual(len(parts), 2)
                output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
                output_mp3_path.write_bytes(b"FAKE-DAILY-MP3")
                return 620

            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module.genai, "Client", return_value=MagicMock()) as mock_client_cls,
                patch.object(
                    main_module,
                    "collect_all_news",
                    return_value={
                        "economy": "econ briefing",
                        "business": "biz briefing",
                        "past_context": "past",
                        "used_keywords": ["既出ワード"],
                    },
                ) as mock_collect,
                patch.object(
                    main_module,
                    "generate_part_script",
                    side_effect=[part1, part2],
                ) as mock_gen_part,
                patch.object(main_module, "build_episode_mp3", side_effect=fake_build_mp3) as mock_build,
                patch.object(sys, "argv", ["main.py"]),
            ):
                main_module.main()

                mock_client_cls.assert_called_once()
                mock_collect.assert_called_once()
                self.assertEqual(mock_gen_part.call_count, 2)
                mock_build.assert_called_once()

                mp3_path = ep_dir / f"{date_str}.mp3"
                meta_path = ep_dir / f"{date_str}.json"
                self.assertTrue(mp3_path.exists())
                self.assertTrue(meta_path.exists())
                self.assertTrue(feed_path.exists())

                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                self.assertEqual(meta["episode_type"], "daily")
                self.assertFalse(meta["exclude_from_context"])
                self.assertFalse(meta["keep_forever"])
                self.assertIsNone(meta["series_id"])
                self.assertIsNone(meta["series_title"])
                self.assertIsNone(meta["series_episode_number"])
                self.assertEqual(meta["keyword_of_the_day"], "プライシングパワー")
                self.assertEqual(meta["duration_sec"], 620)
                self.assertEqual(meta["published_at"], f"{date_str}T05:00:00+09:00")
                self.assertIn("【第1部：経済ニュース】", meta["description"])
                self.assertIn("【第2部：ビジネスニュース】", meta["description"])
                self.assertIn("【今日の1ワード】プライシングパワー", meta["description"])
                self.assertFalse(meta["description"].startswith("【シリーズ】"))

    def test_daily_mode_skip_if_existing_respects_skip_feed(self):
        now_jst = datetime.now(main_module.JST)
        date_str = now_jst.strftime("%Y-%m-%d")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "docs"
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"
            (ep_dir / f"{date_str}.mp3").write_bytes(b"EXISTING-MP3")

            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module, "_refresh_feed") as mock_refresh,
                patch.object(main_module.genai, "Client", side_effect=AssertionError("Must not call genai.Client")),
                patch.object(sys, "argv", ["main.py", "--skip-feed"]),
            ):
                main_module.main()
                mock_refresh.assert_not_called()
                self.assertFalse(feed_path.exists())


class TestSeriesRetentionAndBatchCli(unittest.TestCase):
    def _write_script(self, path: Path, **overrides) -> None:
        now_jst = datetime.now(main_module.JST)
        ep_date = now_jst.strftime("%Y-%m-%d")
        payload = {
            "schema_version": 1,
            "episode_id": f"{ep_date}_extra-series-1",
            "episode_type": "extra",
            "title": "【シリーズ】テスト回",
            "published_at": f"{ep_date}T20:00:00+09:00",
            "weekly_theme": None,
            "keyword_of_the_day": None,
            "exclude_from_context": False,
            "keep_forever": True,
            "series_id": "test-series",
            "series_title": "経済入門シリーズ",
            "series_episode_number": 1,
            "parts": [
                {
                    "part_title": "第1回の概要",
                    "summary_bullets": ["要点A"],
                    "turns": [{"speaker": "ずんだもん", "text": "解説なのだ。"}],
                }
            ],
        }
        payload.update(overrides)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_series_metadata_description_and_retention_warn_suppression(self):
        old_date = (datetime.now(main_module.JST).date() - timedelta(days=30)).strftime("%Y-%m-%d")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "docs"
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"

            def fake_build_mp3(parts, output_mp3_path):
                output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
                output_mp3_path.write_bytes(b"FAKE-MP3")
                return 120

            # 1) keep_forever=True + old published_at -> no [WARN], protected from cleanup, description has series + episode number
            protected_script = root / "protected.json"
            self._write_script(
                protected_script,
                episode_id=f"{old_date}_extra-protected",
                published_at=f"{old_date}T12:00:00+09:00",
                keep_forever=True,
                series_episode_number=2,
            )

            buf1 = io.StringIO()
            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module, "build_episode_mp3", side_effect=fake_build_mp3),
                patch.object(sys, "argv", ["main.py", "--from-script", str(protected_script)]),
                redirect_stdout(buf1),
            ):
                main_module.main()

            self.assertNotIn("[WARN]", buf1.getvalue())
            protected_meta_path = ep_dir / f"{old_date}_extra-protected.json"
            self.assertTrue(protected_meta_path.exists())
            meta = json.loads(protected_meta_path.read_text(encoding="utf-8"))
            self.assertTrue(meta["keep_forever"])
            self.assertEqual(meta["series_id"], "test-series")
            self.assertEqual(meta["series_title"], "経済入門シリーズ")
            self.assertEqual(meta["series_episode_number"], 2)
            self.assertTrue(meta["description"].startswith("【シリーズ】経済入門シリーズ（第2回）\n\n【第1回の概要】"))

            # 2) series_title without series_episode_number -> 【シリーズ】{title} without （第N回）
            no_num_script = root / "no_num.json"
            now_date = datetime.now(main_module.JST).strftime("%Y-%m-%d")
            self._write_script(
                no_num_script,
                episode_id=f"{now_date}_extra-nonum",
                published_at=f"{now_date}T12:00:00+09:00",
                series_episode_number=None,
            )
            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module, "build_episode_mp3", side_effect=fake_build_mp3),
                patch.object(sys, "argv", ["main.py", "--from-script", str(no_num_script), "--skip-feed"]),
            ):
                main_module.main()
            no_num_meta = json.loads((ep_dir / f"{now_date}_extra-nonum.json").read_text(encoding="utf-8"))
            self.assertTrue(no_num_meta["description"].startswith("【シリーズ】経済入門シリーズ\n\n【第1回の概要】"))

            # 3) keep_forever=False + old published_at -> [WARN] IS emitted
            unprotected_script = root / "unprotected.json"
            self._write_script(
                unprotected_script,
                episode_id=f"{old_date}_extra-unprotected",
                published_at=f"{old_date}T12:00:00+09:00",
                keep_forever=False,
                series_id=None,
                series_title=None,
                series_episode_number=None,
            )
            buf2 = io.StringIO()
            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module, "build_episode_mp3", side_effect=fake_build_mp3),
                patch.object(sys, "argv", ["main.py", "--from-script", str(unprotected_script)]),
                redirect_stdout(buf2),
            ):
                main_module.main()
            self.assertIn("[WARN]", buf2.getvalue())

    def test_skip_feed_and_refresh_feed_only_batch_workflow(self):
        ep_date = datetime.now(main_module.JST).strftime("%Y-%m-%d")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "docs"
            ep_dir = docs_dir / "episodes"
            ep_dir.mkdir(parents=True)
            feed_path = docs_dir / "feed.xml"

            scripts = []
            for idx in (1, 2, 3):
                p = root / f"ep_{idx}.json"
                self._write_script(
                    p,
                    episode_id=f"{ep_date}_extra-social-{idx}",
                    title=f"第{idx}回テスト",
                    published_at=f"{ep_date}T20:0{idx - 1}:00+09:00",
                    series_id="social-security",
                    series_title="社会保障シリーズ",
                    series_episode_number=idx,
                )
                scripts.append(p)

            def fake_build_mp3(parts, output_mp3_path):
                output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
                output_mp3_path.write_bytes(b"FAKE-MP3")
                return 100

            with (
                patch.object(config, "DOCS_DIR", docs_dir),
                patch.object(config, "EPISODES_DIR", ep_dir),
                patch.object(config, "FEED_XML_PATH", feed_path),
                patch.object(main_module.genai, "Client", side_effect=AssertionError("Must not call genai.Client")),
                patch.object(main_module, "build_episode_mp3", side_effect=fake_build_mp3) as mock_build,
            ):
                # Run 3 scripts with --skip-feed
                for p in scripts:
                    with patch.object(sys, "argv", ["main.py", "--from-script", str(p), "--skip-feed"]):
                        main_module.main()

                self.assertEqual(mock_build.call_count, 3)
                self.assertFalse(feed_path.exists())

                # Re-running an already-existing MP3 with --skip-feed must also skip _refresh_feed()
                with patch.object(sys, "argv", ["main.py", "--from-script", str(scripts[0]), "--skip-feed"]):
                    main_module.main()
                self.assertEqual(mock_build.call_count, 3)
                self.assertFalse(feed_path.exists())

                # Now run --refresh-feed-only once -> no build_episode_mp3, feed.xml generated with 3 items
                with patch.object(sys, "argv", ["main.py", "--refresh-feed-only"]):
                    main_module.main()
                self.assertEqual(mock_build.call_count, 3)
                self.assertTrue(feed_path.exists())

            root_xml = ET.fromstring(feed_path.read_text(encoding="utf-8"))
            items = root_xml.findall("./channel/item")
            self.assertEqual(len(items), 3)
            itunes_ep_tag = f"{{{rss_builder.ITUNES_NS}}}episode"
            self.assertEqual([item.findtext(itunes_ep_tag) for item in items], ["3", "2", "1"])

    def test_conflicting_cli_flags_rejected(self):
        for argv in (
            ["main.py", "--refresh-feed-only", "--from-script", "foo.json"],
            ["main.py", "--refresh-feed-only", "--skip-feed"],
        ):
            with self.subTest(argv=argv):
                err_buf = io.StringIO()
                with (
                    patch.object(sys, "argv", argv),
                    redirect_stderr(err_buf),
                    self.assertRaises(SystemExit) as ctx,
                ):
                    main_module.main()
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("--refresh-feed-only", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
