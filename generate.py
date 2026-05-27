"""generate.py - 日本の祝日データ生成ツール

サブコマンド:
  fetch    CKAN API 経由で内閣府の祝日 CSV を取得し data/ にキャッシュ保存
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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
            url = r["url"]
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"Invalid URL scheme: {url}")
            return url

    raise RuntimeError("CSV resource not found in CKAN dataset")


def fetch_csv(url: str) -> str:
    """CSV をダウンロードし UTF-8 テキストとして返す。"""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    return raw.decode("cp932")


def _content_hash(text: str) -> str:
    """テキストの SHA-256 ハッシュを返す。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_content_hash(data_dir: Path = DATA_DIR) -> str | None:
    """metadata.json から前回の content_hash を読み込む。"""
    meta_path = data_dir / "metadata.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("content_hash")
    except (json.JSONDecodeError, OSError):
        return None


def save_data(
    csv_text: str,
    url: str,
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
        "content_hash": _content_hash(csv_text),
    }
    metadata_path = data_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cmd_fetch(args: argparse.Namespace) -> None:
    """fetch サブコマンドのエントリーポイント。"""
    print("CSV URL を解決中...")
    csv_url = resolve_csv_url()
    print(f"  URL: {csv_url}")

    print("CSV をダウンロード中...")
    csv_text = fetch_csv(csv_url)
    print(f"  取得完了 ({len(csv_text)} 文字)")

    new_hash = _content_hash(csv_text)
    old_hash = _load_content_hash()
    if old_hash and old_hash == new_hash:
        print("  コンテンツに変更なし。更新スキップ。")
        return

    save_data(csv_text, csv_url)
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
