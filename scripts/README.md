# 追加エピソード台本（`scripts/pending/`）作成ガイド

`scripts/pending/<episode_id>.json` を作成して `main` ブランチへ push すると、GitHub Actions（`.github/workflows/publish_script.yml`）が自動で VOICEVOX 音声合成・RSS 更新・`gh-pages` 公開を行い、公開完了後に `logs/extra_requests.jsonl` への履歴追記・コミットおよび処理済み JSON の `main` からの自動削除を行います（Gemini API は一切使用しません）。
複数の JSON ファイルを同時に push した場合も、各ファイルを `--skip-feed` で順次合成したあと、最後に `--refresh-feed-only` で 1 回だけクリーンアップと `feed.xml` 再生成を実行します。

---

## 1. ファイル名・`episode_id` 規約

- 配置場所：`scripts/pending/<episode_id>.json`
- **`episode_id` の制約**（最大 80 文字）：
  - 正規表現：`^[0-9]{4}-[0-9]{2}-[0-9]{2}(_[a-z0-9-]+)?$`
  - 先頭 `YYYY-MM-DD` は実在するカレンダー日付であること
  - `episode_type == "extra"` の場合は **`YYYY-MM-DD_<slug>` のようにサフィックス必須**（例：`2026-11-20_extra-boj-rate`）
  - `episode_type == "daily"` の場合は **`YYYY-MM-DD` のみ**（サフィックス不可）
- 出力先ファイル名には CLI 引数のファイル名ではなく、JSON 内の検証済み `episode_id` が使われます（ファイル名も `<episode_id>.json` に揃えてください）。

---

## 2. JSON スキーマ（`EpisodeScript`）

| フィールド | 型 | 必須 | 説明・制約 |
|---|---|---|---|
| `schema_version` | `int` | 必須 | `1` 固定 |
| `episode_id` | `str` | 必須 | `YYYY-MM-DD_<slug>`（例：`YYYY-MM-DD_extra-...`）（追加回）または `YYYY-MM-DD`（通常回） |
| `episode_type` | `"extra" \| "daily"` | 必須 | 追加回は `"extra"` |
| `title` | `str` | 必須 | 最大 120 文字（空白のみ不可、XML 1.0 禁止制御文字は除去） |
| `published_at` | `string` (ISO8601) | 必須 | **タイムゾーン必須**（例：`"2026-11-20T12:30:00+09:00"`）。naive 日時は拒否されます。内部で JST に正規化され、RSS の `pubDate`・並び順・保持判定に使用されます。同日に複数回のシリーズを配信する場合は 1 分ずつずらす（例：`20:00:00+09:00`, `20:01:00+09:00`, `20:02:00+09:00`）と並び順が明確になります |
| `weekly_theme` | `string \| null` | 任意 | 追加回は通常 `null` |
| `keyword_of_the_day` | `string \| null` | 任意 | 解説した用語名、または `null` |
| `exclude_from_context` | `bool` | 任意 | `true` にすると翌朝以降の過去回参照・既出キーワード集計から除外（デフォルト `false`）。自動削除の保護は行いません |
| `keep_forever` | `bool` | 任意 | `true` にすると `RETENTION_DAYS`（21日）超過後も自動削除しません（基礎解説・シリーズ回向け、デフォルト `false`）。`exclude_from_context` とは独立して指定できます |
| `series_id` | `string \| null` | 任意 | シリーズ識別子（最大 80 文字、半角英小文字・数字・ハイフン `^[a-z0-9-]+$` のみ、例：`"social-security"`） |
| `series_title` | `string \| null` | 任意 | シリーズ名（最大 120 文字、例：`"日本の社会保障制度シリーズ"`）。指定時は概要欄冒頭に `【シリーズ】{series_title}（第{n}回）`（話数なしの場合は `【シリーズ】{series_title}`）が自動追記されます |
| `series_episode_number` | `int \| null` | 任意 | シリーズ内の話数（1 以上の整数、真偽値不可）。指定時は RSS の `<itunes:episode>` に出力されます。指定する場合は `series_id` または `series_title` のいずれかが必須です |
| `parts` | `list[EpisodePart]` | 必須 | 1〜2 パート（追加回は 1 パート推奨） |

> **補足：`keep_forever` と `exclude_from_context` の使い分け**
> - `keep_forever`: **配信ファイル（`.mp3` / `.json`）の 21 日後自動削除を防ぐ**ためのフラグ（ストック型・基礎解説・シリーズ回向け）。
> - `exclude_from_context`: **翌朝以降の通常ニュース回での AI 過去回参照・既出キーワード集計から除外する**ためのフラグ（通常ニュースと切り離したい単発企画など向け）。シリーズ回でも過去回参照に含めたい場合は `exclude_from_context: false` とします。

### `EpisodePart`

- `part_title`（必須, 1〜100 文字）：パートのサブタイトル
- `summary_bullets`（任意, 最大 6 件）：要約箇条書きリスト
- `turns`（必須, 1〜60 ターン）：会話ターンリスト

### `DialogueTurn`

- `speaker`（必須）：`config.py` の `SPEAKERS` 定義名のみ許可（`"ずんだもん"` または `"春日部つむぎ"`。誤記時はバリデーションエラー）
- `text`（必須, 1〜500 文字, 空白のみ不可）：VOICEVOX で読み上げるセリフ本文

---

## 3. VOICEVOX 読み上げ最適化ルール・文字数目安

- **尺の目安（追加回・1 パート構成）**：全ターンの `text` 合計 **900〜1,400 文字**（約 3〜5 分）
- **英字略語・英単語のカタカナ化**：VOICEVOX の誤読を防ぐため、必ずカタカナ読みに開いて書くこと。
  - 例：`GDP` → `ジーディーピー`、`AI` → `エーアイ`、`FRB` → `エフアールビー`、`BOJ` → `ビーオージェー`（または `日銀`）、`ROE` → `アールオーイー`、`SaaS` → `サース`
- **ト書き・装飾記号の禁止**：`（笑）` `(拍手)` `<laugh>` URL・マークダウン記号などは入れず、音声としてそのまま読める日本語のみを記述すること。
- **構成の目安（3 ステップ深掘り）**：
  1. 何が起きたか（事実・数値）
  2. なぜ起きたか（背景・メカニズム）
  3. 私たちの生活・仕事への影響

---

## 4. テンプレート例（追加エピソード）

### 単発の号外エピソード

```json
{
  "schema_version": 1,
  "episode_id": "2026-11-20_extra-boj-rate",
  "episode_type": "extra",
  "title": "【号外】日銀の追加利上げ観測と住宅ローンへの影響",
  "published_at": "2026-11-20T12:30:00+09:00",
  "weekly_theme": null,
  "keyword_of_the_day": null,
  "exclude_from_context": false,
  "keep_forever": false,
  "parts": [
    {
      "part_title": "日銀の利上げ観測を深掘り",
      "summary_bullets": [
        "日銀の次回会合での追加利上げ観測が強まっている背景",
        "変動金利型住宅ローンや預金金利への具体的な影響"
      ],
      "turns": [
        {
          "speaker": "ずんだもん",
          "text": "こんにちはなのだ！今日は気になるニュースをさくっと深掘りする号外回なのだ！"
        },
        {
          "speaker": "春日部つむぎ",
          "text": "こんにちは、春日部つむぎだよ。今日は日銀の利上げ観測について、みんなの生活にどう関わるか整理していくね。"
        }
      ]
    }
  ]
}
```

### ストック型・シリーズ回（`keep_forever` + `series_*`）

```json
{
  "schema_version": 1,
  "episode_id": "2026-11-20_extra-social-security-1",
  "episode_type": "extra",
  "title": "【号外・第1回】日本の社会保障制度とは？4つの柱と社会保険のしくみ",
  "published_at": "2026-11-20T20:00:00+09:00",
  "weekly_theme": null,
  "keyword_of_the_day": "国民皆保険",
  "exclude_from_context": false,
  "keep_forever": true,
  "series_id": "social-security",
  "series_title": "日本の社会保障制度シリーズ",
  "series_episode_number": 1,
  "parts": [
    {
      "part_title": "社会保障の4つの柱を整理しよう",
      "summary_bullets": [
        "社会保険・社会福祉・公的扶助・保健医療の4本柱",
        "税金方式と社会保険方式の違い"
      ],
      "turns": [
        {
          "speaker": "ずんだもん",
          "text": "社会保障制度を第1回から基礎から整理していくのだ！"
        },
        {
          "speaker": "春日部つむぎ",
          "text": "第1回は全体像として4つの柱から見ていこうね。"
        }
      ]
    }
  ]
}
```

---

## 5. ローカル検証コマンド

push 前に台本 JSON のスキーマ検証のみを行う場合：

```bash
uv run python -c "from pathlib import Path; from morning_news_podcast.schema import EpisodeScript; s = EpisodeScript.model_validate_json(Path('scripts/pending/2026-11-20_extra-boj-rate.json').read_text(encoding='utf-8')); print('OK:', s.episode_id, f'keep_forever={s.keep_forever}', f'series={s.series_id}#{s.series_episode_number}', len(s.parts), sum(len(t.text) for p in s.parts for t in p.turns))"
```
