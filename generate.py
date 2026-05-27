"""generate.py - 日本の祝日データ生成ツール

サブコマンド:
  fetch      CKAN API 経由で内閣府の祝日 CSV を取得し data/ にキャッシュ保存
  generate   CSV → JSON 変換、API ファイル生成
  all        fetch → generate を連続実行
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import sys
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

DATASET_ID = "cao_20190522_0002"
CATALOG_API = (
    f"https://data.e-gov.go.jp/data/api/action/package_show?id={DATASET_ID}"
)
DATA_DIR = Path(__file__).resolve().parent / "data"
METADATA_FILE = DATA_DIR / "metadata.json"
CSV_FILE = DATA_DIR / "syukujitsu.csv"
CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
OUTPUT_DIR = Path(__file__).resolve().parent / "docs" / "api" / "v1"
DOCS_DIR = Path(__file__).resolve().parent / "docs"
SOURCE_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"


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
# generate サブコマンドの実装
# ---------------------------------------------------------------------------


def parse_holidays(csv_text: str) -> list[dict]:
    """CSV テキストをパースし [{"date": "YYYY-MM-DD", "name": "..."}] を返す。"""
    holidays: list[dict] = []
    reader = csv.reader(io.StringIO(csv_text))
    next(reader)  # ヘッダー行をスキップ
    for row in reader:
        if len(row) < 2:
            continue
        raw_date, name = row[0].strip(), row[1].strip()
        if not raw_date or not name:
            continue
        # YYYY/M/D → YYYY-MM-DD
        parts = raw_date.split("/")
        if len(parts) != 3:
            continue
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            date(y, m, d)
        except (ValueError, OverflowError):
            continue
        iso_date = f"{y:04d}-{m:02d}-{d:02d}"
        holidays.append({"date": iso_date, "name": name})
    return holidays


def _holiday_year(h: dict) -> int:
    return int(h["date"][:4])


def filter_holidays(
    holidays: list[dict], *, start: int | None = None, end: int | None = None
) -> list[dict]:
    """年範囲で祝日をフィルタする。start/end は両端含む。"""
    return [
        h for h in holidays
        if (start is None or _holiday_year(h) >= start)
        and (end is None or _holiday_year(h) <= end)
    ]


def _unique_years(
    holidays: list[dict], *, group_fn: Callable[[int], int] = lambda y: y, start: int = 0
) -> list[int]:
    """祝日データからユニークな年（または年代）を抽出する。"""
    return sorted({v for h in holidays if (v := group_fn(_holiday_year(h))) >= start})


def write_json(path: Path, holidays: list[dict], filter_label: str) -> None:
    """JSON ファイルを書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": SOURCE_URL,
        "generated_at": date.today().isoformat(),
        "filter": filter_label,
        "count": len(holidays),
        "holidays": holidays,
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def generate_index_html(output_dir: Path) -> None:
    """docs/index.html を生成する。"""
    api_dir = output_dir / "api" / "v1"
    json_files: list[str] = []
    if api_dir.exists():
        json_files = sorted(
            f.name for f in api_dir.iterdir()
            if f.is_file() and not f.is_symlink() and f.suffix == ".json"
        )

    items = "\n".join(
        f'        <li><a href="api/v1/{html.escape(f)}">{html.escape(f)}</a></li>'
        for f in json_files
    )

    page = f"""\
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>日本の祝日 API</title>
    <style>
        body {{ font-family: sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
        h1 {{ color: #333; }}
        ul {{ line-height: 2; }}
        a {{ color: #0366d6; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        footer {{ margin-top: 2rem; color: #666; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <h1>日本の祝日 API</h1>
    <p>内閣府が公開する「国民の祝日」データを JSON 形式で提供します。</p>
    <h2>エンドポイント一覧</h2>
    <ul>
{items}
    </ul>
    <footer>
        <p>データ出典: <a href="https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html">内閣府「国民の祝日」について</a></p>
    </footer>
</body>
</html>
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(page, encoding="utf-8")


def load_config(config_path: Path = CONFIG_FILE) -> dict:
    """config.yaml を読み込んで辞書として返す。"""
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}


def _endpoint_enabled(endpoints: dict, key: str, default: bool = True) -> bool:
    """エンドポイント設定から有効/無効を判定する。"""
    val = endpoints.get(key, default)
    if isinstance(val, dict):
        return val.get("enabled", default)
    return bool(val)


def _conf_start(endpoints: dict, key: str) -> int:
    conf = endpoints.get(key, {})
    return conf.get("start", 0) if isinstance(conf, dict) else 0


def _build_jobs(
    holidays: list[dict], today: date, endpoints: dict, config: dict
) -> list[tuple[str, list[dict], str]]:
    """(filename, filtered_holidays, filter_label) のジョブリストを構築する。"""
    jobs: list[tuple[str, list[dict], str]] = []

    if _endpoint_enabled(endpoints, "all"):
        jobs.append(("all.json", holidays, "all"))

    if _endpoint_enabled(endpoints, "decade"):
        start = _conf_start(endpoints, "decade") // 10 * 10
        for d in _unique_years(holidays, group_fn=lambda y: y // 10 * 10, start=start):
            jobs.append((f"{d}s.json", filter_holidays(holidays, start=d, end=d + 9), f"{d}s"))

    if _endpoint_enabled(endpoints, "yearly"):
        start = _conf_start(endpoints, "yearly")
        for y in _unique_years(holidays, start=start):
            jobs.append((f"{y}.json", filter_holidays(holidays, start=y, end=y), str(y)))

    for n in endpoints.get("last_n_years", config.get("last_n_years", [3, 5])):
        if not isinstance(n, int) or n <= 0:
            print(f"  警告: last_n_years の値 {n!r} は正の整数ではありません。スキップ。")
            continue
        start_year = today.year - n + 1
        jobs.append((f"last{n}years.json", filter_holidays(holidays, start=start_year), f"last{n}years"))

    if _endpoint_enabled(endpoints, "thisyear"):
        y = today.year
        jobs.append(("thisyear.json", filter_holidays(holidays, start=y, end=y), f"thisyear ({y})"))

    if _endpoint_enabled(endpoints, "nextyear"):
        y = today.year + 1
        jobs.append(("nextyear.json", filter_holidays(holidays, start=y, end=y), f"nextyear ({y})"))

    return jobs


def cmd_generate(args: argparse.Namespace) -> None:
    """generate サブコマンドのエントリーポイント。"""
    if not CSV_FILE.exists():
        print(f"エラー: {CSV_FILE} が見つかりません。先に fetch を実行してください。")
        sys.exit(1)

    holidays = parse_holidays(CSV_FILE.read_text(encoding="utf-8"))
    print(f"CSV パース完了: {len(holidays)} 件の祝日データ")

    config = load_config()
    jobs = _build_jobs(holidays, date.today(), config.get("endpoints", {}), config)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, filtered, label in jobs:
        write_json(OUTPUT_DIR / filename, filtered, label)
        print(f"  生成: {filename} ({len(filtered)} 件)")

    generate_index_html(DOCS_DIR)
    print("JSON 生成完了。")


def cmd_all(args: argparse.Namespace) -> None:
    """all サブコマンド: fetch → generate を連続実行する。"""
    cmd_fetch(args)
    cmd_generate(args)


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

    # generate サブコマンド
    generate_parser = subparsers.add_parser(
        "generate",
        help="CSV → JSON 変換、API ファイル生成",
    )
    generate_parser.set_defaults(func=cmd_generate)

    # all サブコマンド
    all_parser = subparsers.add_parser(
        "all",
        help="fetch → generate を連続実行",
    )
    all_parser.set_defaults(func=cmd_all)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
