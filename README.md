# MomentCatcher FR-0

Google Meet の文字起こしから「称賛すべき瞬間」を自動検出し、
Unipos 投稿ドラフトを生成して Slack に送信するパイプライン。

## アーキテクチャ

```
Google Meet 終了
  ↓（自動）
Google Drive "マイレコーディング" に文字起こしが保存される
  ↓（GAS 時間トリガー：1時間ごと）
SyncTranscript.gs が新規ファイルを検知 → GitHub に Push
  ↓（GitHub Actions 自動起動）
analyze.py が文字起こしを読み込み Claude API を呼び出す
  ↓
Unipos 投稿ドラフト生成
  ↓
Slack に通知（送信者が確認・編集してポスト）
```

## ファイル構成

```
moment-catcher/
├── src/
│   └── gas/
│       └── SyncTranscript.gs       # GAS：Drive 監視 → GitHub Push
├── .github/
│   └── workflows/
│       └── analyze.yml             # GitHub Actions：Push 検知 → Claude 解析
├── scripts/
│   └── analyze.py                  # Claude API 呼び出し + Slack 通知
├── prompts/
│   └── moment_catcher_skill.md     # Claude プロンプト（FR-0 版）
├── transcripts/                    # GAS が Push する文字起こし格納先
└── README.md
```

---

## セットアップ手順

### Step 1: GitHub リポジトリを作成する

1. GitHub で `moment-catcher` という名前のリポジトリを作成（Public / Private どちらでも可）
2. このディレクトリの内容を Push する

```bash
cd /path/to/moment-catcher
git init
git remote add origin https://github.com/<YOUR_USERNAME>/moment-catcher.git
git add .
git commit -m "feat: initial MomentCatcher FR-0 setup"
git push -u origin main
```

### Step 2: GitHub Actions シークレットを設定する

GitHub リポジトリの「Settings → Secrets and variables → Actions」で以下を登録する。

| シークレット名 | 値 | 取得方法 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API キー | https://console.anthropic.com |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL | 下記 Step 4 参照 |

### Step 3: Slack Incoming Webhook を作成する

1. https://api.slack.com/apps にアクセスし「Create New App」→「From scratch」
2. App 名: `MomentCatcher`、ワークスペースを選択して作成
3. 「Incoming Webhooks」を有効化
4. 「Add New Webhook to Workspace」でチャンネルを選択（例: `#moment-catcher`）
5. 発行された Webhook URL を `SLACK_WEBHOOK_URL` シークレットに登録

### Step 4: GAS プロジェクトを作成する

1. https://script.google.com にアクセスし「新しいプロジェクト」を作成
2. `src/gas/SyncTranscript.gs` の内容をエディタに貼り付ける
3. 「プロジェクトの設定」→「スクリプト プロパティ」で以下を登録

| キー | 値 |
|---|---|
| `GITHUB_TOKEN` | Fine-grained token（Contents: Read & Write） |
| `REPO_OWNER` | GitHub ユーザー名 or Org 名 |
| `REPO_NAME` | `moment-catcher` |

#### GitHub Fine-grained Token の発行方法

1. https://github.com/settings/tokens?type=beta にアクセス
2. 「Generate new token」
3. Repository access: `moment-catcher` のみ選択
4. Permissions: `Contents` → `Read and write`
5. 発行されたトークンを `GITHUB_TOKEN` スクリプトプロパティに登録

### Step 5: GAS 時間トリガーを設定する

1. GAS エディタ左側の「トリガー」（時計アイコン）をクリック
2. 「トリガーを追加」
3. 設定:
   - 実行する関数: `syncTranscriptToGithub`
   - イベントのソース: 時間主導型
   - 時間ベースのトリガーのタイプ: 時間ベースのタイマー
   - 時間の間隔: 1時間おき

---

## 動作確認方法

### 1. GAS の手動テスト

GAS エディタで `syncTranscriptToGithub` を選択して「実行」をクリック。
エラーなく完了し、GitHub の `transcripts/` にファイルが作成されれば成功。

### 2. GitHub Actions のログ確認

GitHub リポジトリの「Actions」タブを開き、`MomentCatcher — Analyze Transcript`
ワークフローが成功しているか確認する。

### 3. Slack 通知の確認

設定したチャンネルに Unipos 投稿ドラフトが届けば完了。

---

## ローカル動作テスト（analyze.py）

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

python scripts/analyze.py transcripts/sample.txt
```

---

## ロードマップ

| Phase | 内容 |
|---|---|
| **FR-0**（現在） | テキスト文字起こし → Claude 解析 → Slack 通知 |
| **FR-1** | 音声ファイルから熱量スパイクを検出（librosa） |
| **FR-2** | 音声スパイクと文字起こしのタイムスタンプを突合 |
| **FR-3** | Salesforce / Gmail の成果ログと紐付け |
