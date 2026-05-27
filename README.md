# japan-holidays

日本の祝日一覧を返す静的 JSON API です。GitHub Pages を利用して配信します。

## データソース

内閣府が公開している「国民の祝日」CSV データを使用しています。

- 提供元: [内閣府「国民の祝日」について](https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html)
- 取得方法: CKAN API 経由
- ライセンス: CC-BY

## ローカル実行方法

### 前提条件

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/) (パッケージマネージャー)

### セットアップ

```bash
# 依存パッケージのインストール
uv sync
```

### データの取得と生成

```bash
# 取得と生成を一括実行
python generate.py all

# 個別に実行する場合
python generate.py fetch     # 内閣府 CSV を取得
python generate.py generate  # JSON ファイルを生成
```

生成された JSON ファイルは `docs/api/v1/` ディレクトリに出力されます。

## config.yaml による設定

`config.yaml` で生成するエンドポイントや範囲を制御できます。

| 設定項目 | 説明 |
|---|---|
| `endpoints` セクション | 各エンドポイント（decade, yearly, last_n_years, thisyear, nextyear）の有効/無効を制御 |
| `decade.start` | 年代別ファイルの生成開始年代（例: 2000）|
| `yearly.start` | 年別ファイルの生成開始年（例: 2020）|
| `last_n_years` | 直近年数リストの定義（例: [3, 5]）|

## API エンドポイント一覧

| パス | 内容 |
|---|---|
| `/api/v1/all.json` | 全祝日データ |
| `/api/v1/{decade}s.json` | 年代別（2000s, 2010s, 2020s）config.yaml で範囲設定可 |
| `/api/v1/{year}.json` | 年別（2020, 2021, ...）config.yaml で開始年設定可 |
| `/api/v1/last{N}years.json` | 直近 N 年＋来年（config.yaml で定義、デフォルト: 3年, 5年） |
| `/api/v1/thisyear.json` | 今年のみ |
| `/api/v1/nextyear.json` | 来年のみ |

### 使用例

```
https://<username>.github.io/japan-holidays/api/v1/all.json
https://<username>.github.io/japan-holidays/api/v1/2020s.json
https://<username>.github.io/japan-holidays/api/v1/2026.json
https://<username>.github.io/japan-holidays/api/v1/last3years.json
https://<username>.github.io/japan-holidays/api/v1/thisyear.json
https://<username>.github.io/japan-holidays/api/v1/nextyear.json
```

## GitHub Pages 設定手順

1. GitHub リポジトリの **Settings** を開く
2. 左メニューから **Pages** を選択
3. **Source** で「Deploy from a branch」を選択
4. **Branch** で `main` ブランチ、フォルダを `docs/` に設定
5. **Save** をクリック

設定後、`https://<username>.github.io/japan-holidays/` で API にアクセスできるようになります。

## GitHub Actions による自動更新

GitHub Actions ワークフローにより、毎月1日に以下の処理が自動実行されます。

1. 内閣府 CSV の再取得
2. JSON ファイルの再生成
3. 差分がある場合、自動コミット

これにより、祝日データが更新された場合でも手動操作なしで API が最新の状態に保たれます。

## ライセンス

データの出典: 内閣府「国民の祝日」（CC-BY ライセンス）
