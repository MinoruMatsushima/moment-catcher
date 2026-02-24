/**
 * SyncTranscript.gs — MomentCatcher FR-0
 *
 * Google Drive の "マイレコーディング"（My Recordings）フォルダを監視し、
 * 新規文字起こしファイルを GitHub リポジトリの transcripts/ へ Push する。
 *
 * 設定方法:
 *   1. GAS エディタで「プロジェクトの設定」→「スクリプト プロパティ」を開く
 *   2. 以下のキーを登録する
 *      - GITHUB_TOKEN : Fine-grained token（対象リポジトリへの Contents write 権限）
 *      - REPO_OWNER   : GitHub ユーザー名 or Org 名
 *      - REPO_NAME    : moment-catcher
 *   3. トリガー設定: syncTranscriptToGithub を「時間ベース → 1時間ごと」で実行
 */

// ─── 設定（ScriptProperties から取得） ─────────────────────────────────────

function getConfig_() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  const owner = props.getProperty('REPO_OWNER');
  const repo  = props.getProperty('REPO_NAME');

  if (!token || !owner || !repo) {
    throw new Error(
      'ScriptProperties が未設定です。GITHUB_TOKEN / REPO_OWNER / REPO_NAME を登録してください。'
    );
  }
  return { token, owner, repo };
}

// ─── メイン関数（時間トリガーで呼び出す） ────────────────────────────────────

function syncTranscriptToGithub() {
  const config     = getConfig_();
  const processed  = getProcessedIds_();
  pruneProcessedIds_(processed);  // 30日以上前のエントリを削除
  const folders    = ['マイレコーディング', 'My Recordings'];

  let pushCount = 0;

  for (const folderName of folders) {
    const iter = DriveApp.getFoldersByName(folderName);
    if (!iter.hasNext()) continue;

    const folder = iter.next();
    pushCount += processFolder_(folder, config, processed);
  }

  Logger.log('Push 完了: %s 件', pushCount);
}

// ─── フォルダ内ファイルを処理 ────────────────────────────────────────────────

function processFolder_(folder, config, processed) {
  let count = 0;

  // Google ドキュメント（Meet の文字起こし）を処理
  const docFiles = folder.getFilesByType(MimeType.GOOGLE_DOCS);
  while (docFiles.hasNext()) {
    const file = docFiles.next();
    if (shouldProcess_(file, processed)) {
      const text = exportDocAsText_(file);
      if (text) {
        const ok = pushToGithub_(file, text, config);
        if (ok) { markProcessed_(file.getId(), processed); count++; }
      }
    }
  }

  // プレーンテキストファイルも処理（念のため）
  const txtFiles = folder.getFilesByType(MimeType.PLAIN_TEXT);
  while (txtFiles.hasNext()) {
    const file = txtFiles.next();
    if (shouldProcess_(file, processed)) {
      const text = file.getBlob().getDataAsString('UTF-8');
      const ok = pushToGithub_(file, text, config);
      if (ok) { markProcessed_(file.getId(), processed); count++; }
    }
  }

  // FR-1: MP4（録画ファイル）を検知して audio_triggers/ へ Push
  const mp4Files = folder.getFilesByType(MimeType.VIDEO_MP4);
  while (mp4Files.hasNext()) {
    const mp4 = mp4Files.next();
    if (shouldProcess_(mp4, processed)) {
      const transcriptId = findMatchingTranscriptId_(folder, mp4.getName());
      const ok = pushAudioTrigger_(mp4, transcriptId, config);
      if (ok) { markProcessed_(mp4.getId(), processed); count++; }
    }
  }

  return count;
}

// ─── 同フォルダ内の対応する文字起こし Doc を探す ─────────────────────────────

function findMatchingTranscriptId_(folder, mp4Name) {
  // MP4 ファイル名から拡張子を除いた会議名を取得
  // 例: "2026-02-23 15:30 Weekly Sync.mp4" → "2026-02-23 15:30 Weekly Sync"
  const baseName = mp4Name.replace(/\.mp4$/i, '').trim();

  const docFiles = folder.getFilesByType(MimeType.GOOGLE_DOCS);
  while (docFiles.hasNext()) {
    const doc = docFiles.next();
    const docName = doc.getName().trim();
    // 部分一致で照合（Google Meet は文字起こし Doc に会議名を使う）
    if (docName.includes(baseName) || baseName.includes(docName)) {
      return doc.getId();
    }
  }
  return null;
}

// ─── audio_triggers/ に JSON トリガーをPush ───────────────────────────────────

function pushAudioTrigger_(mp4File, transcriptFileId, config) {
  const datePart   = formatDate_(mp4File.getDateCreated());
  const githubPath = 'audio_triggers/' + datePart + '_' + mp4File.getId().slice(0, 8) + '.json';

  const payload = JSON.stringify({
    audio_file_id    : mp4File.getId(),
    audio_file_name  : mp4File.getName(),
    transcript_file_id: transcriptFileId || null,
    created_at       : new Date().toISOString(),
  }, null, 2);

  const apiUrl = 'https://api.github.com/repos/'
    + config.owner + '/' + config.repo + '/contents/' + githubPath;

  const existing = fetchExistingSha_(apiUrl, config.token);

  const body = {
    message : 'feat: add audio trigger ' + githubPath,
    content : Utilities.base64Encode(payload, Utilities.Charset.UTF_8),
    branch  : 'main',
  };
  if (existing) body.sha = existing;

  const resp = UrlFetchApp.fetch(apiUrl, {
    method      : 'put',
    contentType : 'application/json',
    headers     : {
      Authorization: 'Bearer ' + config.token,
      Accept       : 'application/vnd.github+json',
    },
    payload         : JSON.stringify(body),
    muteHttpExceptions: true,
  });

  const code = resp.getResponseCode();
  if (code === 200 || code === 201) {
    Logger.log('Audio trigger Push 成功: %s', githubPath);
    return true;
  } else {
    Logger.log('Audio trigger Push 失敗: %s (%s)\n%s', githubPath, code, resp.getContentText());
    return false;
  }
}

// ─── 処理対象判定（未処理 かつ 直近24時間以内に更新） ────────────────────────

function shouldProcess_(file, processed) {
  if (processed[file.getId()]) return false;

  const updatedAt  = file.getLastUpdated();
  const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
  return updatedAt > twentyFourHoursAgo;
}

// ─── Google ドキュメント → プレーンテキスト変換 ──────────────────────────────

function exportDocAsText_(file) {
  const url = 'https://docs.google.com/feeds/download/documents/export/Export?id='
    + file.getId() + '&exportFormat=txt';

  const resp = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true,
  });

  if (resp.getResponseCode() !== 200) {
    Logger.log('エクスポート失敗: %s (%s)', file.getName(), resp.getResponseCode());
    return null;
  }
  return resp.getContentText('UTF-8');
}

// ─── GitHub へ Push ───────────────────────────────────────────────────────────

function pushToGithub_(file, content, config) {
  const datePart   = formatDate_(file.getDateCreated());
  const githubPath = 'transcripts/' + datePart + '_' + file.getId().slice(0, 8) + '.txt';

  const apiUrl = 'https://api.github.com/repos/'
    + config.owner + '/' + config.repo + '/contents/' + githubPath;

  // 既存ファイルの SHA を取得（上書き更新に必要）
  const existing = fetchExistingSha_(apiUrl, config.token);

  const body = {
    message : 'feat: add transcript ' + githubPath,
    content : Utilities.base64Encode(content, Utilities.Charset.UTF_8),
    branch  : 'main',
  };
  if (existing) body.sha = existing;

  const resp = UrlFetchApp.fetch(apiUrl, {
    method      : 'put',
    contentType : 'application/json',
    headers     : {
      Authorization: 'Bearer ' + config.token,
      Accept       : 'application/vnd.github+json',
    },
    payload         : JSON.stringify(body),
    muteHttpExceptions: true,
  });

  const code = resp.getResponseCode();
  if (code === 200 || code === 201) {
    Logger.log('Push 成功: %s', githubPath);
    return true;
  } else {
    Logger.log('Push 失敗: %s (%s)\n%s', githubPath, code, resp.getContentText());
    return false;
  }
}

// ─── 既存ファイルの SHA 取得（PUT で上書きするために必要） ─────────────────────

function fetchExistingSha_(apiUrl, token) {
  const resp = UrlFetchApp.fetch(apiUrl, {
    headers: {
      Authorization: 'Bearer ' + token,
      Accept       : 'application/vnd.github+json',
    },
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() === 200) {
    return JSON.parse(resp.getContentText()).sha;
  }
  return null;
}

// ─── 処理済み ID の永続管理 ──────────────────────────────────────────────────

function getProcessedIds_() {
  const raw = PropertiesService.getScriptProperties().getProperty('PROCESSED_IDS');
  return raw ? JSON.parse(raw) : {};
}

function markProcessed_(fileId, processed) {
  processed[fileId] = new Date().toISOString();
  PropertiesService.getScriptProperties().setProperty(
    'PROCESSED_IDS', JSON.stringify(processed)
  );
}

function pruneProcessedIds_(processed) {
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
  let pruned = 0;
  for (const [id, iso] of Object.entries(processed)) {
    if (new Date(iso) < thirtyDaysAgo) {
      delete processed[id];
      pruned++;
    }
  }
  if (pruned > 0) {
    PropertiesService.getScriptProperties().setProperty(
      'PROCESSED_IDS', JSON.stringify(processed)
    );
    Logger.log('PROCESSED_IDS から %s 件を削除しました', pruned);
  }
}

// ─── 日付フォーマット ─────────────────────────────────────────────────────────

function formatDate_(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return y + '-' + m + '-' + d;
}
