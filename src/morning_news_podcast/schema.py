"""台本 JSON（EpisodeScript）の共通 Pydantic v2 スキーマ定義と厳格バリデーション"""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from . import config

JST = timezone(timedelta(hours=9))
MAX_TURNS_PER_PART = 60
MAX_CHARS_PER_TURN = 500

# XML 1.0 で禁止されている制御文字（TAB \x09, LF \x0a, CR \x0d は許可）
XML_FORBIDDEN_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
EPISODE_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(_[a-z0-9-]+)?$")
SERIES_ID_RE = re.compile(r"^[a-z0-9-]+$")
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def strip_xml_control_chars(text: str) -> str:
    """XML 1.0 で禁止されている制御文字を除去する"""
    return XML_FORBIDDEN_CHARS_RE.sub("", text)


def _sanitize_str(v: object) -> object:
    return strip_xml_control_chars(v).strip() if isinstance(v, str) else v


SanitizedStr = Annotated[str, BeforeValidator(_sanitize_str)]


def resolve_published_at(stem: str, meta: dict) -> datetime | None:
    """メタデータの published_at を優先し、未設定時はファイル名先頭YYYY-MM-DD→05:00 JST にフォールバックする"""
    raw_pub = meta.get("published_at")
    if isinstance(raw_pub, str) and raw_pub.strip():
        try:
            dt = datetime.fromisoformat(raw_pub.strip())
            if dt.tzinfo is None or dt.utcoffset() is None:
                dt = dt.replace(tzinfo=JST)
            return dt.astimezone(JST)
        except ValueError:
            pass

    m = _DATE_PREFIX_RE.match(stem)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                hour=5, minute=0, second=0, tzinfo=JST
            )
        except ValueError:
            pass
    return None


class DialogueTurn(BaseModel):
    speaker: str = Field(
        max_length=30,
        description="話者名。指定されたパーソナリティ名のいずれか（例: ずんだもん / 春日部つむぎ）。",
        json_schema_extra={"enum": [sp["name"] for sp in config.SPEAKERS]},
    )
    text: SanitizedStr = Field(
        min_length=1,
        max_length=MAX_CHARS_PER_TURN,
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


class EpisodePart(BaseModel):
    part_title: SanitizedStr = Field(
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
        max_length=MAX_TURNS_PER_PART,
        description="2人の会話ターンリスト（合計文字数1,500〜1,800文字目安）",
    )

    @field_validator("summary_bullets")
    @classmethod
    def sanitize_summary_bullets(cls, v: list[str]) -> list[str]:
        cleaned = [strip_xml_control_chars(item).strip() for item in v]
        return [item for item in cleaned if item]


class EpisodeScript(BaseModel):
    schema_version: Literal[1] = Field(
        description="スキーマバージョン（1固定）",
    )
    episode_id: str = Field(
        max_length=80,
        description="エピソードID（ファイル名ベース）",
    )
    episode_type: Literal["daily", "extra"] = Field(
        description="エピソード区分（daily / extra）",
    )
    title: SanitizedStr = Field(
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
    keep_forever: bool = Field(
        default=False,
        description="true の場合、RETENTION_DAYS による自動削除の対象外とする（基礎解説・シリーズ回向け）",
    )
    series_id: str | None = Field(
        default=None,
        max_length=80,
        description="シリーズ識別子（例: social-security）",
    )
    series_title: str | None = Field(
        default=None,
        max_length=120,
        description="シリーズ名（例: 日本の社会保障制度シリーズ）",
    )
    series_episode_number: int | None = Field(
        default=None,
        ge=1,
        description="シリーズ内の話数（1始まり）",
    )
    parts: list[EpisodePart] = Field(
        min_length=1,
        max_length=2,
        description="パート一覧（1〜2パート）",
    )

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

    @field_validator("published_at")
    @classmethod
    def validate_published_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError(
                "published_at はタイムゾーン付き（例: +09:00 や Z）の ISO8601 日時で指定してください"
            )
        return v.astimezone(JST)

    @field_validator(
        "weekly_theme", "keyword_of_the_day", "series_id", "series_title", mode="before"
    )
    @classmethod
    def sanitize_optional_text(cls, v: object) -> object:
        if isinstance(v, str):
            cleaned = strip_xml_control_chars(v).strip()
            return cleaned or None
        return v

    @field_validator("series_id")
    @classmethod
    def validate_series_id(cls, v: str | None) -> str | None:
        if v is not None and not SERIES_ID_RE.fullmatch(v):
            raise ValueError(
                f"series_id の形式が不正です: {v!r}（英小文字・数字・ハイフンのみ指定可能です）"
            )
        return v

    @field_validator("series_episode_number", mode="before")
    @classmethod
    def reject_bool_for_series_episode_number(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("series_episode_number に真偽値は指定できません")
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
        if self.series_episode_number is not None and not (
            self.series_id or self.series_title
        ):
            raise ValueError(
                "series_episode_number を指定する場合は series_id または series_title のいずれかを指定してください"
            )
        return self
