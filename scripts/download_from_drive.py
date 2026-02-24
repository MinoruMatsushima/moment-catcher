#!/usr/bin/env python3
"""
download_from_drive.py — Google Drive から音声ファイルをダウンロードする

使い方:
    python scripts/download_from_drive.py <file_id> <output_path>

環境変数:
    GOOGLE_SERVICE_ACCOUNT_KEY  サービスアカウント JSON の内容（文字列）
"""

import json
import os
import sys
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: download_from_drive.py <file_id> <output_path>", file=sys.stderr)
        sys.exit(1)

    file_id     = sys.argv[1]
    output_path = sys.argv[2]

    sa_key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not sa_key_json:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_KEY is not set", file=sys.stderr)
        sys.exit(1)

    sa_key_path = "/tmp/sa_key.json"
    Path(sa_key_path).write_text(sa_key_json, encoding="utf-8")

    creds = Credentials.from_service_account_file(
        sa_key_path,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    service = build("drive", "v3", credentials=creds)

    request = service.files().get_media(fileId=file_id)
    with open(output_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"Download {int(status.progress() * 100)}%", file=sys.stderr)

    print(f"Downloaded to {output_path}", file=sys.stderr)
    Path(sa_key_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
