"""台本 JSON（EpisodeScript）の共通 Pydantic v2 スキーマ定義と厳格バリデーション"""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

import config

JST = timezone(timedelta(hours=9))

# XML 1.0 で禁止されている制御文字（TAB \x09, LF \x0a, CR \x0d は許可）
XML_FORBIDDEN_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
EPISODE_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(_[a-z0-9-]+)?$")


def strip_xml_control_chars(text: str) -> str:
    """XML 1.0 で禁止されている制御文字を除去する"""
    return XML_FORBIDDEN_CHARS_RE.sub("", text)


class DialogueTurn(BaseModel):
    speaker: str = Field(
        max_length=30,
        description="話者名。指定されたパーソナリティ名のいずれか（例: ずんだもん / 春日部つむぎ）。",
    )
    text: str = Field(
        min_length=1,
        max_length=500,
        description="VOICEVOXで読み上げるセリフ本文。英字略語はカタカナ読みにし、ト書きや記号は含めない。",
    )

    @field_validator("speaker")
    @classmethod
    def validate_speaker(cls, v: str) -> str:
        valid_speakers = [sp["name"] for sp in config.SPEAKERS]
        if v not in valid_speakers:
            raise ValueError(
                f"不正な話者名です: {v!r}（許可されている話者: {', '.join(valid_speakers)}）"
            )
        return v

    @field_validator("text", mode="before")
    @classmethod
    def sanitize_text(cls, v: object) -> object:
        if isinstance(v, str):
            return strip_xml_control_chars(v).strip()
        return v


class EpisodePart(BaseModel):
    part_title: str = Field(
        min_length=1,
        max_length=100,
        description="このパートの短いサブタイトル",
    )
    summary_bullets: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="取り上げたニュースと背景解説の要約（2〜3行）",
    )
    turns: list[DialogueTurn] = Field(
        min_length=1,
        max_length=60,
        description="2人の会話ターンリスト（合計文字数1,500〜1,800文字目安）",
    )

    @field_validator("part_title", mode="before")
    @classmethod
    def sanitize_part_title(cls, v: object) -> object:
        if isinstance(v, str):
            return strip_xml_control_chars(v).strip()
        return v

    @field_validator("summary_bullets")
    @classmethod
    def sanitize_summary_bullets(cls, v: list[str]) -> list[str]:
        cleaned = [strip_xml_control_chars(item).strip() for item in v]
        return [item for item in cleaned if item]


class EpisodeScript(BaseModel):
    schema_version: int = Field(
        description="スキーマバージョン（1固定）",
    )
    episode_id: str = Field(
        max_length=80,
        description="エピソードID（ファイル名ベース）",
    )
    episode_type: Literal["daily", "extra"] = Field(
        description="エピソード区分（daily / extra）",
    )
    title: str = Field(
        min_length=1,
        max_length=120,
        description="エピソードタイトル",
    )
    published_at: datetime = Field(
        description="配信日時（タイムゾーン付き ISO8601、内部で JST に正規化）",
    )
    weekly_theme: str | None = Field(
        default=None,
        description="曜日テーマラベル（追加回は null）",
    )
    keyword_of_the_day: str | None = Field(
        default=None,
        description="今日の1ワード（追加回は null 可）",
    )
    exclude_from_context: bool = Field(
        default=False,
        description="true の場合、翌朝以降の過去回参照および既出キーワード集計から除外",
    )
    parts: list[EpisodePart] = Field(
        min_length=1,
        max_length=2,
        description="パート一覧（1〜2パート）",
    )

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"未対応の schema_version です: {v}（1 のみ対応）")
        return v

    @field_validator("episode_id")
    @classmethod
    def validate_episode_id(cls, v: str) -> str:
        if not EPISODE_ID_RE.fullmatch(v):
            raise ValueError(
                f"episode_id の形式が不正です: {v!r}（YYYY-MM-DD または YYYY-MM-DD_slug の形式で指定してください）"
            )
        try:
            date.fromisoformat(v[:10])
        except ValueError as exc:
            raise ValueError(
                f"episode_id の先頭日付が実在しない日付です: {v[:10]!r}"
            ) from exc
        return v

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: object) -> object:
        if isinstance(v, str):
            return strip_xml_control_chars(v).strip()
        return v

    @field_validator("published_at")
    @classmethod
    def validate_published_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError(
                "published_at はタイムゾーン付き（例: +09:00 や Z）の ISO8601 日時で指定してください"
            )
        return v.astimezone(JST)

    @field_validator("weekly_theme", "keyword_of_the_day", mode="before")
    @classmethod
    def sanitize_optional_text(cls, v: object) -> object:
        if isinstance(v, str):
            cleaned = strip_xml_control_chars(v).strip()
            return cleaned or None
        return v

    @model_validator(mode="after")
    def validate_episode_type_rules(self) -> "EpisodeScript":
        has_suffix = len(self.episode_id) > 10 and self.episode_id[10] == "_"
        if self.episode_type == "extra" and not has_suffix:
            raise ValueError(
                "episode_type が 'extra' の場合、episode_id には 'YYYY-MM-DD_<slug>' 形式のサフィックスが必須です"
            )
        if self.episode_type == "daily" and has_suffix:
            raise ValueError(
                "episode_type が 'daily' の場合、episode_id は 'YYYY-MM-DD' のみ（サフィックス不可）です"
            )
        return self
