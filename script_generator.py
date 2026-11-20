"""Gemini 3.8 Flashによる2人掛け合い台本生成（深掘り3ステップ＋今日の1ワード＋VOICEVOX最適化）"""

from typing import List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

import config


class DialogueTurn(BaseModel):
    speaker: str = Field(
        description="話者名。指定されたパーソナリティ名のいずれか（例: ずんだもん / 春日部つむぎ）。"
    )
    text: str = Field(
        description="VOICEVOXで読み上げるセリフ本文。英字略語はカタカナ読みにし、ト書きや記号は含めない。"
    )


class PodcastPartScript(BaseModel):
    part_title: str = Field(description="このパートの短いサブタイトル")
    summary_bullets: List[str] = Field(
        description="取り上げたニュースと背景解説の要約（2〜3行）"
    )
    keyword_of_the_day: Optional[str] = Field(
        default=None,
        description="第2部で解説した『今日のビジネス用語』（例: プライシングパワー）。第1部ではnull。",
    )
    turns: List[DialogueTurn] = Field(
        description="2人の会話ターンリスト（合計文字数1,500〜1,800文字目安）"
    )


def _speaker_instructions() -> str:
    lines = []
    for sp in config.SPEAKERS:
        lines.append(f"- **{sp['name']}**（{sp['role']}）: {sp['persona']}")
    return "\n".join(lines)


def generate_part_script(
    client: genai.Client,
    part_number: int,
    news_briefing: str,
    date_label: str,
    weekly_theme: dict,
    past_context: str,
    used_keywords: List[str],
) -> PodcastPartScript:
    speaker_names = [sp["name"] for sp in config.SPEAKERS]
    used_kw_str = "、".join(used_keywords) if used_keywords else "なし"

    if part_number == 1:
        flow_instruction = (
            f"これは番組の【第1部：経済ニュース】です。{date_label}の朝の挨拶と、本日の曜日テーマ「{weekly_theme['label']}」に軽く触れたオープニングから始め、"
            "厳選した経済トピックを「事実 → なぜそうなるかの背景・仕組み → 私たちの生活や仕事への影響」の3ステップで深掘りしてください。\n"
            "過去エピソードとつながる話題があれば「そういえば数日前に話した〇〇だけど…」と自然に結びつけてください。\n"
            "最後は第2部（ビジネスニュース）へ自然につなげて締めくくってください（`keyword_of_the_day` は null にしてください）。"
        )
    else:
        flow_instruction = (
            "これは番組の【第2部：ビジネスニュース】です。第1部からの流れを受けて自然につなぎ、"
            "厳選したビジネストピックを「事実 → 背景・企業戦略の仕組み → 私たちの仕事や暮らしへの示唆」の3ステップで深掘りしてください。\n"
            f"さらに、番組の締めくくり直前にミニコーナー『今日の1ワード』（約300文字）を入れ、今回のニュースに関連する経済・ビジネス用語を1つ（ただし直近の既出用語「{used_kw_str}」は避ける）取り上げて噛み砕いて解説し、その用語名を `keyword_of_the_day` に設定してください。\n"
            "最後は「今日も一日がんばるのだ！いってらっしゃい！」のような朝のエンディングで締めくくってください。"
        )

    prompt = f"""あなたは聴く人の教養とビジネスセンスを高める朝ラジオ番組の構成作家です。
以下の深掘り資料をもとに、2人のパーソナリティによる明るくテンポの良い掛け合い台本を作成してください。

【パーソナリティ設定】
{_speaker_instructions()}
※ `speaker` フィールドには必ず「{speaker_names[0]}」または「{speaker_names[1]}」のいずれかを正確に設定してください。

【本日の曜日テーマ】
{weekly_theme['label']}：{weekly_theme['instruction']}

【パート構成指示】
{flow_instruction}

【過去の配信履歴（関連話題の連携用）】
{past_context}

【文字数・VOICEVOX読み上げ最適化ルール】
- 台本（全ターンの `text` 合計）は **{config.TARGET_CHARS_PER_PART}**（約5分尺）を目安にすること。
- ただニュースを読み上げるのではなく、{speaker_names[0]}が「なんでそうなるのだ？」「それって僕たちにどう関係あるのだ？」と質問し、{speaker_names[1]}が背景や仕組みを身近な例で答える掛け合いにすること。
- **重要（読み上げエラー防止）**：`text` 内のアルファベット略語や英単語は、音声合成が誤読しないよう **必ずカタカナ読みに開いて書くこと**（例：`GDP` → `ジーディーピー`、`AI` → `エーアイ`、`FRB` → `エフアールビー`、`ROE` → `アールオーイー`、`TOB` → `ティーオービー`）。
- `text` には読み上げる日本語のセリフのみを書き、「（笑）」「(拍手)」「<laugh>」などのト書き・タグ・URL・装飾記号は一切入れないこと。
- 特定のメディア記事の文章をそのままコピーせず、必ず2人の会話として再構成すること。

【ニュース深掘り資料】
{news_briefing}
"""

    response = client.models.generate_content(
        model=config.SCRIPT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PodcastPartScript,
            temperature=0.7,
        ),
    )
    script = PodcastPartScript.model_validate_json(response.text)
    valid_names = set(speaker_names)
    for turn in script.turns:
        if turn.speaker not in valid_names:
            turn.speaker = speaker_names[0]
    return script
