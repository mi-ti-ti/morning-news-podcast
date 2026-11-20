# 複数エピソード・シリーズ運用に向けた仕組み改善 引き継ぎ書

## 背景・目的

`scripts/pending/<episode_id>.json` を使った追加（号外）エピソード機能において、基礎教養や深掘りテーマを複数回シリーズ（例：全3回）として配信する運用が始まった。
現行実装でも配信自体は可能だが、以下の課題がある。

1. **自動削除**: `RETENTION_DAYS = 21` により、基礎解説などのストック型エピソードも21日後に自動削除されてしまう。
2. **シリーズ管理**: 複数回をシリーズとして束ねるメタデータや Podcast RSS の `<itunes:episode>` 等が未対応。
3. **CI 実行効率**: `scripts/pending/*.json` に複数ファイルを同時 push した際、ファイルごとに全 MP3 スキャンと `feed.xml` 再生成が走っている。

本ドキュメントは、これら3点の改善を別エージェントが実装・テスト・ドキュメント更新まで完結できるようにまとめた引き継ぎ仕様書である。

---

## 改善項目 1: ストック型／シリーズ回の自動削除保護（`keep_forever`）

### 現状
- `src/morning_news_podcast/rss_builder.py` の `cleanup_old_episodes()` が `docs/episodes/*.mp3` を走査し、`published_at.date() < cutoff_date` のエピソードを一律削除している。

### 変更仕様
1. **`src/morning_news_podcast/schema.py`**
   - `EpisodeScript` に任意フィールドを追加する（既存 JSON との後方互換性維持のためデフォルト `False`）。
     ```python
     keep_forever: bool = Field(
         default=False,
         description="true の場合、RETENTION_DAYS による自動削除の対象外とする（基礎解説・シリーズ回向け）",
     )
     ```
2. **`src/morning_news_podcast/main.py`**
   - `_synthesize_and_publish()` で保存するメタデータ JSON（`docs/episodes/<episode_id>.json`）に `"keep_forever": script.keep_forever` を出力する。
   - 保持期間超過の警告ログ出力判定も `not script.keep_forever` を条件に加える。
3. **`src/morning_news_podcast/rss_builder.py`**
   - `cleanup_old_episodes()` 内で `meta.get("keep_forever") is True` のエピソードを削除対象からスキップする（スキップ時に `[INFO]` ログを出してもよい）。

### テスト観点
- `keep_forever=True` かつ `published_at` が `RETENTION_DAYS` より古いエピソードが削除されないこと。
- `keep_forever=False` または未設定（旧メタデータ JSON）の古いエピソードは従来通り削除されること。

---

## 改善項目 2: シリーズ用メタデータと RSS（iTunes）タグ対応

### 現状
- シリーズ回はタイトル文字列（例：`【号外・第1回】...`）と `published_at` の1分ずらしで順序表現している。
- `build_rss_feed()` では `<itunes:episode>` や `<itunes:episodeType>` などを出力していない。

### 変更仕様
1. **`src/morning_news_podcast/schema.py`**
   - `EpisodeScript` にシリーズ用の任意フィールドを追加する（すべてデフォルト `None` で後方互換性を維持）。
     ```python
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
     ```
   - 必要に応じて `series_episode_number` が指定された場合は `series_id` または `series_title` との整合性バリデーションを検討する（厳しすぎない範囲で）。
2. **`src/morning_news_podcast/main.py`**
   - `_synthesize_and_publish()` のメタデータ JSON に `series_id` / `series_title` / `series_episode_number` を保存する（`None` の場合はそのまま出力または省略、既存の `weekly_theme` / `keyword_of_the_day` の流儀に合わせる）。
   - `_build_description()` で `series_title` がある場合に冒頭へ `【シリーズ】{series_title}（第{n}回）` のように表記するかも検討する。
3. **`src/morning_news_podcast/rss_builder.py`**
   - `build_rss_feed()` でメタデータに `series_episode_number`（正の整数）がある場合、`<itunes:episode>{n}</itunes:episode>` を `<item>` に出力する。
   - 既存の `episodes.sort(key=lambda item: (item[0], item[1].stem), reverse=True)` による並び順は維持しつつ、同一 `published_at` のケースでも順序が安定することを確認する。
4. **`src/morning_news_podcast/extra_log.py`**（任意）
   - `logs/extra_requests.jsonl` に `series_id` 等を記録するかは既存スキーマとテストを確認のうえ判断する。

### テスト観点
- `series_*` フィールド未指定の既存台本 JSON・既存メタデータ JSON が問題なくバリデーション・RSS 生成できること。
- `series_episode_number` 指定時に `feed.xml` に `<itunes:episode>` が出力されること。
- `series_episode_number <= 0` でバリデーションエラーになること。

---

## 改善項目 3: 複数ファイル一括処理時のワークフロー効率化

### 現状
- `.github/workflows/publish_script.yml` では `for f in "${pending_files[@]}"; do uv run morning-news-podcast --from-script "$f"; done` とループ実行している。
- `main.py` の `_synthesize_and_publish()` が毎回 `_refresh_feed()`（`cleanup_old_episodes()` + `build_rss_feed()`）を実行するため、N 件同時 push するとフィード再構築が N 回走る。

### 変更仕様（推奨案：`--skip-feed` と `--refresh-feed-only` の追加、または `--from-script` の複数指定対応）
- **案 A（シンプル・変更最小）**:
  - `src/morning_news_podcast/main.py` の CLI に `--skip-feed`（音声合成とメタデータ保存のみ行い `_refresh_feed()` をスキップ）および `--refresh-feed-only`（`cleanup_old_episodes()` と `build_rss_feed()` のみ実行）を追加する。
  - `.github/workflows/publish_script.yml` のループ内では `--from-script "$f" --skip-feed` を実行し、ループ完了後に1回だけ `uv run morning-news-podcast --refresh-feed-only` を呼ぶ。
- **案 B（CLI 側で一括処理）**:
  - `--from-script` を `nargs="+"` または複数回指定可能にし、全ファイル合成後に1回だけ `_refresh_feed()` を実行する。
  - 案 B の場合、1件失敗したときにどこまで `processed_list` に入れるかのハンドリングに注意が必要（案 A なら既存の bash ループ構造を維持しやすい）。

### テスト観点
- `--skip-feed` 指定時に MP3 とメタデータ JSON は生成されるが `feed.xml` は更新されないこと。
- `--refresh-feed-only` 指定時に `cleanup_old_episodes()` と `build_rss_feed()` が実行されること。
- 既存の単発実行（`--from-script <file>`）の挙動が変わらないこと。

---

## 関連ドキュメントの更新

実装に合わせて以下も更新すること。
- `scripts/README.md`: 新規フィールド（`keep_forever`, `series_id`, `series_title`, `series_episode_number`）の仕様表・テンプレート例を追記。
- `README.md`: CLI オプションや保持期間ルールの記載があれば更新。

---

## 推奨実装順序と確認コマンド

1. `schema.py` → `main.py` → `rss_builder.py` の順で改善項目 1・2 を実装し、単体テストを追加。
2. `main.py` と `.github/workflows/publish_script.yml` で改善項目 3 を実装し、CLI テストを追加。
3. `scripts/README.md` 等のドキュメントを更新。
4. 既存テストを含めて実行・確認：
   ```bash
   uv run pytest
   ```
