"""Unit tests for schema.py"""

import unittest
from datetime import timedelta, timezone

from pydantic import ValidationError

from morning_news_podcast.schema import DialogueTurn, EpisodePart, EpisodeScript, JST, resolve_published_at


def _make_turn(speaker: str = "ずんだもん", text: str = "テスト発話なのだ。") -> dict:
    return {"speaker": speaker, "text": text}


def _make_part(part_title: str = "テストパート") -> dict:
    return {
        "part_title": part_title,
        "summary_bullets": ["要約1"],
        "turns": [_make_turn()],
    }


def _make_script(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "episode_id": "2026-11-20_extra-boj-rate",
        "episode_type": "extra",
        "title": "【号外】日銀の追加利上げ観測",
        "published_at": "2026-11-20T12:30:00+09:00",
        "weekly_theme": None,
        "keyword_of_the_day": None,
        "exclude_from_context": False,
        "parts": [_make_part()],
    }
    base.update(overrides)
    return base


class TestSchemaValidation(unittest.TestCase):
    def test_valid_extra_and_daily_scripts(self):
        extra = EpisodeScript.model_validate(_make_script())
        self.assertEqual(extra.episode_id, "2026-11-20_extra-boj-rate")
        self.assertEqual(extra.published_at.tzinfo, JST)

        daily = EpisodeScript.model_validate(
            _make_script(
                episode_id="2026-11-20",
                episode_type="daily",
                title="2026年11月20日 | 経済ニュース ほか",
                published_at="2026-11-19T20:00:00Z",  # UTC -> JST 05:00
                weekly_theme="金曜・今週の総括＆振り返り",
                keyword_of_the_day="プライシングパワー",
                parts=[_make_part("第1部"), _make_part("第2部")],
            )
        )
        self.assertEqual(daily.published_at.utcoffset(), timedelta(hours=9))
        self.assertEqual(daily.published_at.hour, 5)
        self.assertEqual(daily.published_at.day, 20)

    def test_invalid_episode_id_patterns_and_path_traversal(self):
        bad_ids = [
            "../evil",
            "2026-11-20/../../etc/passwd",
            "2026-11-20_UpperCase",
            "2026-11-20_bad_underscore",
            "2026-11-20_" + ("a" * 80),
            "2026-02-30_extra-bad-date",
        ]
        for bad_id in bad_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValidationError):
                    EpisodeScript.model_validate(_make_script(episode_id=bad_id))

    def test_extra_requires_suffix_and_daily_forbids_suffix(self):
        with self.assertRaises(ValidationError):
            EpisodeScript.model_validate(
                _make_script(episode_id="2026-11-20", episode_type="extra")
            )
        with self.assertRaises(ValidationError):
            EpisodeScript.model_validate(
                _make_script(episode_id="2026-11-20_extra-slug", episode_type="daily")
            )

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValidationError):
            EpisodeScript.model_validate(
                _make_script(published_at="2026-11-20T12:30:00")
            )

    def test_invalid_speaker_rejected_strictly(self):
        with self.assertRaises(ValidationError):
            DialogueTurn.model_validate({"speaker": "四国めたん", "text": "こんにちは"})

    def test_empty_or_whitespace_turn_rejected(self):
        with self.assertRaises(ValidationError):
            DialogueTurn.model_validate({"speaker": "ずんだもん", "text": "   \n\t  "})

    def test_xml_control_chars_stripped_from_title_part_and_turns(self):
        script = EpisodeScript.model_validate(
            _make_script(
                title="テスト\x00タイトル\x0b\x1f",
                parts=[
                    {
                        "part_title": "パート\x01名\x0c",
                        "summary_bullets": ["箇条書き\x02テスト"],
                        "turns": [
                            {"speaker": "春日部つむぎ", "text": "セリフ\x07本文\x7fだよ"}
                        ],
                    }
                ],
            )
        )
        self.assertEqual(script.title, "テストタイトル")
        self.assertEqual(script.parts[0].part_title, "パート名")
        self.assertEqual(script.parts[0].summary_bullets, ["箇条書きテスト"])
        self.assertEqual(script.parts[0].turns[0].text, "セリフ本文だよ")

    def test_max_length_constraints(self):
        with self.assertRaises(ValidationError):
            EpisodeScript.model_validate(_make_script(title="あ" * 121))
        with self.assertRaises(ValidationError):
            DialogueTurn.model_validate({"speaker": "ずんだもん", "text": "あ" * 501})
        with self.assertRaises(ValidationError):
            EpisodePart.model_validate(
                {
                    "part_title": "テスト",
                    "summary_bullets": [],
                    "turns": [_make_turn() for _ in range(61)],
                }
            )


    def test_missing_schema_version_rejected(self):
        payload = _make_script()
        del payload["schema_version"]
        with self.assertRaises(ValidationError):
            EpisodeScript.model_validate(payload)

    def test_blank_summary_bullets_filtered(self):
        part = EpisodePart.model_validate(
            {
                "part_title": "テスト",
                "summary_bullets": ["  ", "\x00\x0b", "有効な要約", "\t\n"],
                "turns": [_make_turn()],
            }
        )
        self.assertEqual(part.summary_bullets, ["有効な要約"])

    def test_resolve_published_at_priority_and_fallbacks(self):
        # tz-aware UTC -> JST
        dt = resolve_published_at("2026-11-20", {"published_at": "2026-11-19T20:00:00Z"})
        self.assertIsNotNone(dt)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour), (2026, 11, 20, 5))
        self.assertEqual(dt.utcoffset(), timedelta(hours=9))

        # naive ISO8601 -> treated as JST
        dt_naive = resolve_published_at("2026-11-20", {"published_at": "2026-11-20T12:30:00"})
        self.assertIsNotNone(dt_naive)
        self.assertEqual((dt_naive.hour, dt_naive.minute), (12, 30))
        self.assertEqual(dt_naive.utcoffset(), timedelta(hours=9))

        # missing/invalid published_at -> stem YYYY-MM-DD at 05:00 JST
        dt_stem = resolve_published_at("2026-11-19_extra-foo", {"published_at": "not-a-date"})
        self.assertIsNotNone(dt_stem)
        self.assertEqual((dt_stem.year, dt_stem.month, dt_stem.day, dt_stem.hour), (2026, 11, 19, 5))

        # both invalid -> None
        self.assertIsNone(resolve_published_at("no-date-here", {}))


if __name__ == "__main__":
    unittest.main()
