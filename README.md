# 個人用・毎朝自動配信ニュースポッドキャスト（VOICEVOX 版）

毎朝 5:00（JST）までに最新の経済・ビジネスニュースを収集し、**VOICEVOX:ずんだもん** と **VOICEVOX:春日部つむぎ** による掛け合い音声（約10分・2部構成）を自動生成して GitHub Pages 経由で配信するシステムです。

## 番組の特徴（知見を深める5つの仕組み）

1. **1〜2件に絞った構造・メカニズム深掘り**：速報を浅く並べるのではなく、各部1〜2件の重要ニュースを厳選して背景まで解説します。
2. **「事実 → 背景 → 生活・仕事への影響」の3ステップ構成**：聴き手が自分事として理解できる流れで掛け合いを進めます。
3. **過去エピソード連携（「点と線」のストーリー）**：直近7日分の配信履歴（`docs/episodes/*.json`）を参照し、続報や関連トピックを自然につなげて解説します。
4. **「今日の1ワード」ミニコーナー**：第2部の終盤に、ニュースに登場した経済・ビジネス用語を1つ噛み砕いて解説します（直近の既出用語は自動回避）。
5. **曜日別テーマ編成**：月曜（今週の予定予習）、水曜（テック・新ビジネス）、金曜（週間総括）、土日（業界構造・経済基礎教養）など曜日ごとの切り口で配信します。

## 構成ファイル

```text
.
├── .github/
│   ├── actions/
│   │   ├── publish-gh-pages/            # 生成物（MP3・feed.xml）の gh-pages 公開用 Composite Action
│   │   └── setup-podcast-env/           # Python/uv・ffmpeg・VOICEVOXアセット・既存配信データ復元 Action
│   └── workflows/
│       ├── daily_podcast.yml            # 毎日自動実行＆GitHub Pages更新ワークフロー
│       ├── publish_script.yml           # 追加エピソード公開ワークフロー
│       └── test.yml                     # 単体テストCIワークフロー
├── .python-version                      # 使用Pythonバージョン固定（3.13）
├── Dockerfile                           # 環境非依存のコンテナ実行用定義
├── compose.yaml                         # Docker Compose 実行定義
├── docs/                                # 静的テンプレート＆ローカル出力先（自動配信時は gh-pages ブランチへ公開）
│   ├── episodes/                        # 生成されたMP3・メタデータ（最新21日分を保持・main上はGit追跡外）
│   ├── cover.png                        # ポッドキャスト番組カバー画像
│   └── index.html                       # 公開確認用ページ（クレジット表記入り）
├── logs/
│   └── extra_requests.jsonl             # 追加エピソード配信履歴ログ（JSONL）
├── scripts/                             # 追加エピソード台本配置用
│   ├── pending/                         # 配信待ち台本JSON配置ディレクトリ（公開後に自動削除）
│   └── README.md                        # 追加エピソード台本の作成ガイド・JSONスキーマ仕様
├── src/
│   └── morning_news_podcast/            # コアモジュール
│       ├── __init__.py                  # パッケージ初期化
│       ├── __main__.py                  # モジュール実行エントリーポイント（python -m）
│       ├── audio_generator.py           # VOICEVOX Core音声合成 + pydub MP3結合
│       ├── config.py                    # モデル・番組設定・曜日別テーマ・VOICEVOX話者設定
│       ├── extra_log.py                 # 追加エピソード依頼履歴のJSONL追記ユーティリティ
│       ├── main.py                      # メインエントリーポイント
│       ├── news_collector.py            # RSS取得 + 過去回参照 + Gemini検索グラウンディング
│       ├── rss_builder.py               # 古いMP3削除 + feed.xml再生成
│       ├── schema.py                    # 台本・エピソードデータのスキーマ定義
│       ├── script_generator.py          # 深掘り掛け合い台本生成（今日の1ワード含む）
│       └── voicevox_setup.py            # OS・CPU自動判別によるVOICEVOXアセット自動取得
├── tests/                               # 単体テスト
├── feeds.yaml                           # 購読する経済・ビジネスニュースRSS一覧
└── pyproject.toml                       # uv / Python 3.13 依存パッケージ管理（OS別Wheel対応）
```

> **VOICEVOX クレジット表記について**  
> 本システムでは GitHub Pages（Public）経由で配信するため、`docs/feed.xml` の番組説明欄および `docs/index.html` に `VOICEVOX:ずんだもん` / `VOICEVOX:春日部つむぎ` のクレジット表記を自動で含めています。

---

## セットアップ手順

### 1. Google AI Studio で API キーを取得（特典クレジット連携）

1. [Google AI Studio](https://aistudio.google.com/) にログインし、**Get API key** から API キーを発行します。
2. 台本生成と検索グラウンディングに `gemini-3.8-flash` を使用します（音声合成は VOICEVOX Core を使用するため API 課金は発生しません）。
3. Google AI Pro プランの特典クレジット（毎月 $10 分）を API に適用する場合は、AI Studio の **Billing** 画面でプリペイド請求を設定（初回のみ最低 $5 のデポジットが必要）し、Google Developer Program の特典ページからクレジットを連携してください。

### 2. GitHub リポジトリの作成とファイルのアップロード

1. GitHub で新しい **Public（公開）** リポジトリを作成します（例: `morning-news-podcast`）。
   ※ GitHub の無料プランで GitHub Pages を利用するには **Public リポジトリ** である必要があります。
2. このフォルダ一式をリポジトリにプッシュします（`voicevox_assets/` はワークフロー実行時に自動取得されるためコミット不要です）。

```bash
git init
git add .
git commit -m "feat: initial VOICEVOX podcast generator setup"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
git push -u origin main
```

### 3. GitHub Secrets に API キーを登録

1. リポジトリの **Settings** > **Secrets and variables** > **Actions** を開きます。
2. **New repository secret** をクリックし、以下を登録します。
   - Name: `GEMINI_API_KEY`
   - Secret: 手順 1 で取得した API キー

### 4. GitHub Pages の有効化

1. リポジトリの **Settings** > **Pages** を開きます。
2. **Build and deployment** の Source で **Deploy from a branch** を選択します。
3. Branch に **gh-pages**、フォルダに **/ (root)** を選択して **Save** をクリックします（※ 初回実行前に `gh-pages` ブランチが無い場合は、手順 5 を先に実行したあと設定してください）。

### 5. 手動テスト実行（初回エピソード＆`feed.xml` 生成）

1. リポジトリの **Actions** タブを開き、左側の **Daily Morning News Podcast** を選択します。
2. **Run workflow** ボタンをクリックして手動実行します（VOICEVOX の CPU 合成を含め 5〜10 分程度で完了します）。
3. 完了後、`gh-pages` ブランチに `episodes/YYYY-MM-DD.mp3` と `feed.xml` が自動コミットされていることを確認します（`main` ブランチにはコードのみが残り、自動コミットで競合しない構成です）。
4. ブラウザで `https://<あなたのユーザー名>.github.io/<リポジトリ名>/feed.xml` にアクセスし、XML が表示されれば配信準備完了です。

### 6. スマホの Podcast アプリで購読する

発行された RSS URL（`https://<あなたのユーザー名>.github.io/<リポジトリ名>/feed.xml`）をアプリに登録します。

- **Apple Podcast（iOS）**: 「ライブラリ」> 右上の「…（メニュー）」>「URLで番組をフォロー」に RSS URL を貼り付け
- **Pocket Casts**: 「検索（Discover）」タブの検索バーに RSS URL をそのまま貼り付けて検索 > 購読

---

## ローカル環境でテスト実行する場合

以下のいずれかの方法で、macOS / Linux / Windows を問わず同じ手順で実行できます。

### 方法 A: Docker Compose で実行（ホスト環境への Python / ffmpeg 導入不要・推奨）

Docker（または Colima + Docker）が利用できる環境であれば、ローカル環境に依存せずコンテナ内で完結して実行できます。生成された MP3 や `feed.xml` は `./docs` に出力されます。

```bash
# 1. 環境変数を設定（.env ファイルに書いても可）
export GEMINI_API_KEY="your-api-key-here"
export PODCAST_BASE_URL="https://<あなたのユーザー名>.github.io/<リポジトリ名>"

# 2. ビルド＆実行（再生成したい場合は docker compose run --rm podcast uv run morning-news-podcast --force を実行）
docker compose run --rm podcast
```

### 方法 B: `uv` を使ってローカルで直接実行（OS・CPU 自動判別）

`uv` が `pyproject.toml` と `.python-version`（Python 3.13）をもとに仮想環境と OS 別の `voicevox_core` を自動導入し、初回実行時に `voicevox_setup.py` が現在の OS に合った VOICEVOX アセットを自動取得します。

```bash
# 1. uv と ffmpeg をインストール（初回のみ）
# macOS (Homebrew) の例:
brew install uv ffmpeg
# Ubuntu / Debian の例:
# curl -LsSf https://astral.sh/uv/install.sh | sh && sudo apt-get install -y ffmpeg

# 2. 仮想環境の構築＆依存パッケージ導入
uv sync

# 3. 環境変数を設定して実行（VOICEVOX アセット未配置時は自動でダウンロードされます）
export GEMINI_API_KEY="your-api-key-here"
export PODCAST_BASE_URL="https://<あなたのユーザー名>.github.io/<リポジトリ名>"
uv run morning-news-podcast
```

## 追加エピソードの配信方法

毎朝の自動配信（`daily`）とは別に、号外や任意の特集回（`extra`）を手動作成した台本 JSON から配信できます。

- **GitHub Actions での自動配信**: `scripts/pending/<episode_id>.json` を配置して `main` ブランチへ push すると、`.github/workflows/publish_script.yml` が起動し、Gemini API を使わずに VOICEVOX 音声合成・RSS 更新・`gh-pages` 公開を実行します。
- **履歴記録と自動クリーンアップ**: 公開完了後、`extra` エピソードの配信履歴が `logs/extra_requests.jsonl` に自動追記・コミットされ、処理済みの `scripts/pending/*.json` は `main` ブランチから削除されます。
- **ローカルでの手動合成**: CLI オプション `--from-script` を指定すると、ローカル環境でも台本 JSON から直接音声合成と RSS 更新を実行できます。

```bash
uv run morning-news-podcast --from-script scripts/pending/2026-11-20_extra-boj-rate.json
```

台本 JSON の詳細なスキーマ仕様・命名規約・テンプレート例については、[scripts/README.md](scripts/README.md) を参照してください。

---

## カスタマイズ方法

- **曜日別テーマの編集**: `src/morning_news_podcast/config.py` の `WEEKLY_THEMES` を編集すると、曜日ごとの特集内容を自由に変更できます。
- **ニュースソースの追加・変更**: `feeds.yaml` の `economy` / `business` リストに RSS URL を追加・編集してください。
- **話速・声のスタイル変更**: `src/morning_news_podcast/config.py` の `SPEAKERS` にある `style_id` や `speed_scale`（初期値: `1.05`）を調整してください。
- **保持日数の変更**: `src/morning_news_podcast/config.py` の `RETENTION_DAYS`（初期値: `21` 日分）を変更してください。
- **配信時刻の調整**: `.github/workflows/daily_podcast.yml` の `cron` を変更してください（初期値 `10 19 * * *` ＝ 毎日 04:10 JST に起動）。
