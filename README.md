# earthquake-notify

地震発生時にLINEとメールで自動通知するシステム。
重要システムの運用監視を支援することを目的としています。

---

## 報告義務の定義（業務要件）

対象組織内においてシステム報告が必要となる業務要件は以下の通りです。

| 条件 | 対象エリア | 震度基準 |
|------|-----------|---------|
| ① | 東京23区内 | **震度5強以上** |
| ② | 全国（東京23区を除く） | **震度6弱以上** |

いずれかの条件に該当する場合、対象システムの稼働確認報告を行う必要があります。

---

## システム概要

### 通知条件

#### 警報レベル（システム稼働確認報告が必要）
- **東京23区**: 震度5強以上（`THRESHOLD_ALERT_TOKYO_23KU`、デフォルト `5+`）
- **全国（東京23区を除く）**: 震度6弱以上（`THRESHOLD_ALERT_NATIONWIDE`、デフォルト `6-`）

#### 注意レベル（参考情報として通知）
- **東京23区**: 震度4以上（`THRESHOLD_CAUTION_TOKYO_23KU`、デフォルト `4`）
- **全国**: 震度4以上（`THRESHOLD_CAUTION_NATIONWIDE`、デフォルト `4`）

### 通知内容
1. **震度速報（VXSE51）**: 地震発生直後にLINE・メールで速報
2. **震源・震度情報（VXSE53）**: 詳細情報をLINEで続報

### 通知先
- LINE Messaging API（個人 or グループ）
- Gmail SMTP（メール）

---

## アーキテクチャ

```
気象庁XML（eqvol_l.xml）
     ↓ 5分毎ポーリング
GitHub Actions（cron: */5 * * * *）
     ↓ 震度判定
state/notified_events.json（重複防止・状態管理）
     ↓ 閾値超過時
LINE Messaging API + Gmail SMTP
```

---

## ファイル構成

```
earthquake-notify/
├── main.py              # エントリーポイント
├── config.py            # 環境変数管理
├── fetcher.py           # 気象庁XML取得
├── checker.py           # 震度判定・メッセージ生成
├── notifier/
│   ├── line.py          # LINE Messaging API送信
│   └── email.py         # Gmail SMTP送信
├── state/
│   └── notified_events.json  # 通知済みイベント管理
├── requirements.txt
└── .github/
    └── workflows/
        └── monitor.yml  # GitHub Actions（5分毎自動実行）
```

---

## 環境変数一覧

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャネルアクセストークン | 必須 |
| `LINE_USER_ID` | LINE送信先ユーザーID or グループID | 必須 |
| `THRESHOLD_ALERT_TOKYO_23KU` | 東京23区・警報閾値（業務要件①） | `5+` |
| `THRESHOLD_ALERT_NATIONWIDE` | 全国・警報閾値（業務要件②） | `6-` |
| `THRESHOLD_CAUTION_TOKYO_23KU` | 東京23区・注意閾値 | `4` |
| `THRESHOLD_CAUTION_NATIONWIDE` | 全国・注意閾値 | `4` |
| `EMAIL_ENABLED` | メール通知オン/オフ | `false` |
| `EMAIL_FROM` | 送信元Gmailアドレス | - |
| `EMAIL_TO` | 送信先メールアドレス | - |
| `EMAIL_PASSWORD` | Gmailアプリパスワード | - |
| `LINE_CHANNEL_SECRET` | LINE Webhookの署名検証用シークレット | - |

---

## 環境変数の変更方法

GitHubリポジトリの **Settings → Secrets and variables → Actions** から設定します。

### Secrets（機密情報）

**Settings → Secrets and variables → Actions → Secrets → New repository secret**

| Secret名 | 内容 |
|----------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャネルアクセストークン |
| `LINE_USER_ID` | LINE送信先ユーザーID or グループID |
| `EMAIL_FROM` | 送信元Gmailアドレス（メール通知使用時） |
| `EMAIL_TO` | 送信先メールアドレス（メール通知使用時） |
| `EMAIL_PASSWORD` | Gmailアプリパスワード（メール通知使用時） |

### Variables（非機密設定値）

**Settings → Secrets and variables → Actions → Variables → New repository variable**

| Variable名 | 内容 | 推奨値 |
|------------|------|--------|
| `THRESHOLD_ALERT_TOKYO_23KU` | 東京23区・警報閾値 | `5+` |
| `THRESHOLD_ALERT_NATIONWIDE` | 全国・警報閾値 | `6-` |
| `THRESHOLD_CAUTION_TOKYO_23KU` | 東京23区・注意閾値 | `4` |
| `THRESHOLD_CAUTION_NATIONWIDE` | 全国・注意閾値 | `4` |
| `EMAIL_ENABLED` | メール通知オン/オフ | `false` |

---

## デプロイ方法

```bash
git add .
git commit -m "変更内容"
git push origin main
# GitHub Actionsが自動でmonitor.ymlを実行
```

---

## ローカルテスト

```bash
# 依存パッケージインストール
pip install -r requirements.txt

# PowerShell
$env:LINE_CHANNEL_ACCESS_TOKEN = "トークン"
$env:LINE_USER_ID = "ユーザーID"
$env:THRESHOLD_ALERT_TOKYO_23KU = "1"
$env:THRESHOLD_ALERT_NATIONWIDE = "1"
python main.py

# bash
LINE_CHANNEL_ACCESS_TOKEN="トークン" LINE_USER_ID="ユーザーID" \
THRESHOLD_ALERT_TOKYO_23KU="1" THRESHOLD_ALERT_NATIONWIDE="1" \
python main.py
```

---

## TODO

### 優先度高
- [x] 毎朝9時 日次サマリー通知機能
- [x] LINE「状況は？」サマリー返信機能

### 優先度低
- [ ] 続報（VXSE53）のEventID紐付けバグ修正
  - 現状、VXSE53のevent_idはVXSE51と異なるため、続報判定が機能しない
  - 震源地・地震発生時刻等で同一地震を紐付ける仕組みが必要

- [ ] チームメンバーをLINEグループに追加
  - チームLINEグループを作成し、BotをQRコードで招待
  - `LINE_USER_ID` をグループIDに変更
