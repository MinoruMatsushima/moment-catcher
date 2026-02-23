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
        pushToGithub_(file, text, config);
        markProcessed_(file.getId(), processed);
        count++;
      }
    }
  }

  // プレーンテキストファイルも処理（念のため）
  const txtFiles = folder.getFilesByType(MimeType.PLAIN_TEXT);
  while (txtFiles.hasNext()) {
    const file = txtFiles.next();
    if (shouldProcess_(file, processed)) {
      const text = file.getBlob().getDataAsString('UTF-8');
      pushToGithub_(file, text, config);
      markProcessed_(file.getId(), processed);
      count++;
    }
  }

  return count;
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
  const safeName   = file.getName().replace(/[^\w\-]/g, '_');
  const githubPath = 'transcripts/' + datePart + '_' + safeName + '.txt';

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
  } else {
    Logger.log('Push 失敗: %s (%s)\n%s', githubPath, code, resp.getContentText());
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

// ─── 日付フォーマット ─────────────────────────────────────────────────────────

function formatDate_(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return y + '-' + m + '-' + d;
}
