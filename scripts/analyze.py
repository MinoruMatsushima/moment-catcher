#!/usr/bin/env python3
"""
analyze.py — MomentCatcher FR-0

使い方:
    python scripts/analyze.py transcripts/2026-02-23_Meeting.txt

環境変数（GitHub Actions Secrets）:
    ANTHROPIC_API_KEY   Anthropic API キー
    SLACK_WEBHOOK_URL   Slack Incoming Webhook URL
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import requests

# ─── 定数 ────────────────────────────────────────────────────────────────────

PROMPT_PATH  = Path(__file__).parent.parent / "prompts" / "moment_catcher_skill.md"
MODEL        = "claude-sonnet-4-6"
MAX_TOKENS   = 2048

# 文字起こしが長すぎる場合のトークン対策（先頭から指定文字数を使用）
MAX_TRANSCRIPT_CHARS = 15_000


# ─── プロンプト読み込み ────────────────────────────────────────────────────────

def load_prompt(transcript_text: str, file_name: str) -> str:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = raw.replace("{transcript_text}", transcript_text)
    prompt = prompt.replace("{file_name}", file_name)
    return prompt


# ─── Claude API 呼び出し ───────────────────────────────────────────────────────

def analyze_transcript(transcript_text: str, file_name: str) -> dict:
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt  = load_prompt(transcript_text[:MAX_TRANSCRIPT_CHARS], file_name)

    message = client.messages.create(
        model      = MODEL,
        max_tokens = MAX_TOKENS,
        messages   = [{"role": "user", "content": prompt}],
    )

    # レスポンスから JSON を抽出
    raw_text = message.content[0].text
    json_match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # コードブロックなしで JSON が返ってきた場合
    return json.loads(raw_text)


# ─── Slack 通知 ───────────────────────────────────────────────────────────────

def build_slack_message(result: dict, file_path: str) -> dict:
    file_name = Path(file_path).name
    date_str  = datetime.now().strftime("%Y-%m-%d %H:%M")

    if result.get("no_moment_found"):
        return {
            "text": f":mag: *MomentCatcher* — 称賛の瞬間は見つかりませんでした",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":mag: *MomentCatcher* — 称賛の瞬間が見つかりませんでした\n"
                            f"*会議ファイル*: `{file_name}`\n"
                            f"*解析日時*: {date_str}\n"
                            f"*会議概要*: {result.get('meeting_summary', '—')}"
                        ),
                    },
                }
            ],
        }

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":tada: MomentCatcher — Unipos 投稿ドラフトを生成しました",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*会議ファイル*\n`{file_name}`"},
                {"type": "mrkdwn", "text": f"*解析日時*\n{date_str}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*会議概要*\n{result.get('meeting_summary', '—')}",
            },
        },
        {"type": "divider"},
    ]

    for draft in result.get("drafts", []):
        rank      = draft.get("rank", "?")
        moment    = draft.get("moment", "")
        recipient = draft.get("recipient", "?")
        text      = draft.get("draft", "")
        reason    = draft.get("reason", "")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*【ドラフト {rank}】{moment}*\n"
                    f":bust_in_silhouette: 称賛相手: *{recipient}*\n\n"
                    f"```{text}```\n"
                    f"_{reason}_"
                ),
            },
        })
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                ":pencil2: *内容を確認・編集して、Unipos に投稿してください。*\n"
                "ドラフトは自動生成です。あなた自身の言葉を添えて送ると、より伝わります。"
            ),
        },
    })

    return {"text": "MomentCatcher: Unipos 投稿ドラフトを生成しました", "blocks": blocks}


def send_to_slack(message: dict) -> None:
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    resp = requests.post(
        webhook_url,
        json=message,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    print(f"Slack 送信完了: {resp.status_code}")


# ─── エントリポイント ──────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze.py <transcript_file>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    transcript_text = Path(file_path).read_text(encoding="utf-8")
    file_name = Path(file_path).name

    print(f"解析開始: {file_name} ({len(transcript_text)} 文字)")

    result = analyze_transcript(transcript_text, file_name)
    print("Claude 解析完了:", json.dumps(result, ensure_ascii=False, indent=2))

    message = build_slack_message(result, file_path)
    send_to_slack(message)


if __name__ == "__main__":
    main()
