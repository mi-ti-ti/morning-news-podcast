"""Unit tests for audio_generator.py and main.py"""

import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydub import AudioSegment

from morning_news_podcast import audio_generator, config
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
                self.assertEqual(meta["keyword_of_the_day"], "プライシングパワー")
                self.assertEqual(meta["duration_sec"], 620)
                self.assertEqual(meta["published_at"], f"{date_str}T05:00:00+09:00")
                self.assertIn("【第1部：経済ニュース】", meta["description"])
                self.assertIn("【第2部：ビジネスニュース】", meta["description"])
                self.assertIn("【今日の1ワード】プライシングパワー", meta["description"])


if __name__ == "__main__":
    unittest.main()
