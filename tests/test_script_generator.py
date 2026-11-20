"""Unit tests for script_generator.py"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from google.genai import _transformers as genai_transformers
from pydantic import ValidationError

from morning_news_podcast import config
from morning_news_podcast.script_generator import PodcastPartScript, _RawPodcastPartScript, generate_part_script


def _make_mock_client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text=json.dumps(payload, ensure_ascii=False)
    )
    return client


class TestScriptGenerator(unittest.TestCase):
    def test_raw_schema_includes_speaker_enum_for_gemini(self):
        gemini_schema = genai_transformers.t_schema(None, _RawPodcastPartScript).model_dump(
            exclude_none=True
        )
        speaker_prop = gemini_schema["properties"]["turns"]["items"]["properties"]["speaker"]
        self.assertEqual(speaker_prop["enum"], [sp["name"] for sp in config.SPEAKERS])

    def test_generate_part_script_fallbacks_invalid_speaker_and_drops_empty_turns(self):
        payload = {
            "part_title": "今日の経済ニュース",
            "summary_bullets": ["要約1"],
            "keyword_of_the_day": None,
            "turns": [
                {"speaker": "つむぎ", "text": "表記揺れの話者名なのだ。"},
                {"speaker": "ずんだもん", "text": "   \n\t  "},
                {"speaker": "春日部つむぎ", "text": "\x00\x0b"},
                {"speaker": "春日部つむぎ", "text": "有効なセリフだよ。"},
            ],
        }
        client = _make_mock_client(payload)

        result = generate_part_script(
            client=client,
            part_number=1,
            news_briefing="ニュース資料",
            date_label="2026年11月20日",
            weekly_theme=config.WEEKLY_THEMES[4],
            past_context="",
            used_keywords=[],
        )

        self.assertIsInstance(result, PodcastPartScript)
        self.assertEqual(len(result.turns), 2)
        self.assertEqual(result.turns[0].speaker, config.SPEAKERS[0]["name"])
        self.assertEqual(result.turns[0].text, "表記揺れの話者名なのだ。")
        self.assertEqual(result.turns[1].speaker, "春日部つむぎ")
        self.assertEqual(result.turns[1].text, "有効なセリフだよ。")

    def test_generate_part_script_raises_when_all_turns_empty(self):
        payload = {
            "part_title": "空ターンテスト",
            "summary_bullets": [],
            "keyword_of_the_day": None,
            "turns": [
                {"speaker": "ずんだもん", "text": "   "},
                {"speaker": "春日部つむぎ", "text": "\x00"},
            ],
        }
        client = _make_mock_client(payload)

        with self.assertRaises(ValidationError):
            generate_part_script(
                client=client,
                part_number=1,
                news_briefing="ニュース資料",
                date_label="2026年11月20日",
                weekly_theme=config.WEEKLY_THEMES[4],
                past_context="",
                used_keywords=[],
            )


if __name__ == "__main__":
    unittest.main()
