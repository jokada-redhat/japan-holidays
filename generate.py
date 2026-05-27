"""generate.py - 日本の祝日データ生成ツール

サブコマンド:
  fetch    CKAN API 経由で内閣府の祝日 CSV を取得し data/ にキャッシュ保存
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATASET_ID = "cao_20190522_0002"
CATALOG_API = (
    f"https://data.e-gov.go.jp/data/api/action/package_show?id={DATASET_ID}"
)
DATA_DIR = Path(__file__).resolve().parent / "data"
METADATA_FILE = DATA_DIR / "metadata.json"
CSV_FILE = DATA_DIR / "syukujitsu.csv"


# ---------------------------------------------------------------------------
# fetch サブコマンドの実装
# ---------------------------------------------------------------------------


def resolve_csv_url() -> str:
    """CKAN API で CSV リソースの URL を動的に取得する。"""
    req = urllib.request.Request(CATALOG_API)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if not body.get("success"):
        raise RuntimeError("CKAN API returned success=false")

    resources = body["result"]["resources"]
    for r in resources:
        if r.get("format", "").upper() == "CSV":
            return r["url"]

    raise RuntimeError("CSV resource not found in CKAN dataset")


def fetch_csv(url: str, etag: str | None = None) -> tuple[str, str] | None:
    """CSV をダウンロードする。

    304 Not Modified の場合は None を返す。
    200 OK の場合は (csv_text, new_etag) を返す。
    """
    req = urllib.request.Request(url)
    if etag:
        req.add_header("If-None-Match", etag)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            new_etag = resp.headers.get("ETag", "")
            # Shift_JIS (CP932) → UTF-8
            csv_text = raw.decode("cp932")
            return csv_text, new_etag
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None
        raise


def save_data(
    csv_text: str,
    url: str,
    etag: str,
    data_dir: Path = DATA_DIR,
) -> None:
    """CSV と metadata.json を書き出す。"""
    data_dir.mkdir(parents=True, exist_ok=True)

    csv_path = data_dir / "syukujitsu.csv"
    csv_path.write_text(csv_text, encoding="utf-8")

    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "dataset_id": DATASET_ID,
        "catalog_api": CATALOG_API,
        "etag": etag,
    }
    metadata_path = data_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_etag(data_dir: Path = DATA_DIR) -> str | None:
    """metadata.json から前回の ETag を読み込む。"""
    meta_path = data_dir / "metadata.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("etag")
    except (json.JSONDecodeError, OSError):
        return None


def cmd_fetch(args: argparse.Namespace) -> None:
    """fetch サブコマンドのエントリーポイント。"""
    print("CSV URL を解決中...")
    csv_url = resolve_csv_url()
    print(f"  URL: {csv_url}")

    etag = _load_etag()
    if etag:
        print(f"  前回の ETag: {etag}")

    print("CSV をダウンロード中...")
    result = fetch_csv(csv_url, etag=etag)

    if result is None:
        print("  304 Not Modified — キャッシュは最新です。更新不要。")
        return

    csv_text, new_etag = result
    print(f"  取得完了 ({len(csv_text)} 文字)")
    if new_etag:
        print(f"  ETag: {new_etag}")

    save_data(csv_text, csv_url, new_etag)
    print(f"  保存先: {CSV_FILE}")
    print(f"  メタデータ: {METADATA_FILE}")
    print("完了。")


# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="日本の祝日データ生成ツール",
    )
    subparsers = parser.add_subparsers(dest="command")

    # fetch サブコマンド
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="CKAN API 経由で祝日 CSV を取得",
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
