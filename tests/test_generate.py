"""generate.py のテスト — フィルタロジック & ダウンロード処理"""

from __future__ import annotations

import json
import textwrap
from datetime import date
from pathlib import Path

import pytest
import yaml

from generate import (
    _build_jobs,
    _content_hash,
    _holiday_year,
    _load_content_hash,
    _unique_years,
    fetch_csv,
    filter_holidays,
    load_config,
    parse_holidays,
    resolve_csv_url,
    write_json,
)

# ---------------------------------------------------------------------------
# テスト用 CSV データ
# ---------------------------------------------------------------------------

SAMPLE_CSV = textwrap.dedent("""\
    国民の祝日・休日月日,国民の祝日・休日名称
    2023/1/1,元日
    2023/1/9,成人の日
    2023/2/11,建国記念の日
    2024/1/1,元日
    2024/1/8,成人の日
    2025/1/1,元日
    2025/1/13,成人の日
""")

SAMPLE_CSV_MULTI_YEAR = textwrap.dedent("""\
    国民の祝日・休日月日,国民の祝日・休日名称
    1990/1/1,元日
    2000/1/1,元日
    2010/1/1,元日
    2020/1/1,元日
    2023/1/1,元日
    2024/1/1,元日
    2025/1/1,元日
""")


# ---------------------------------------------------------------------------
# パース系テスト
# ---------------------------------------------------------------------------


class TestParseHolidays:
    def test_parse_holidays(self):
        """CSV テキスト → dict リストの変換"""
        result = parse_holidays(SAMPLE_CSV)
        assert len(result) == 7
        assert result[0] == {"date": "2023-01-01", "name": "元日"}
        assert result[1] == {"date": "2023-01-09", "name": "成人の日"}
        assert result[3] == {"date": "2024-01-01", "name": "元日"}
        # 全要素が date と name キーを持つ
        for h in result:
            assert "date" in h
            assert "name" in h

    def test_parse_holidays_invalid_date(self):
        """不正日付（13月、32日等）のスキップ"""
        csv_with_invalid = textwrap.dedent("""\
            国民の祝日・休日月日,国民の祝日・休日名称
            2023/1/1,元日
            2023/13/1,不正月
            2023/2/30,不正日
            2023/0/1,ゼロ月
            invalid/date,不正フォーマット
            2023/1/9,成人の日
        """)
        result = parse_holidays(csv_with_invalid)
        assert len(result) == 2
        assert result[0]["name"] == "元日"
        assert result[1]["name"] == "成人の日"

    def test_parse_holidays_empty(self):
        """空CSV / ヘッダーのみ"""
        # ヘッダーのみ
        header_only = "国民の祝日・休日月日,国民の祝日・休日名称\n"
        result = parse_holidays(header_only)
        assert result == []

    def test_parse_holidays_short_row(self):
        """カラムが不足している行のスキップ"""
        csv_short = textwrap.dedent("""\
            国民の祝日・休日月日,国民の祝日・休日名称
            2023/1/1,元日
            2023/1/9
        """)
        result = parse_holidays(csv_short)
        assert len(result) == 1

    def test_parse_holidays_leap_year(self):
        """うるう年の 2/29 は有効、非うるう年は無効"""
        csv_leap = textwrap.dedent("""\
            国民の祝日・休日月日,国民の祝日・休日名称
            2024/2/29,うるう日
            2023/2/29,無効日
        """)
        result = parse_holidays(csv_leap)
        assert len(result) == 1
        assert result[0]["date"] == "2024-02-29"

    def test_parse_holidays_empty_fields(self):
        """日付や名前が空の行のスキップ"""
        csv_empty_fields = textwrap.dedent("""\
            国民の祝日・休日月日,国民の祝日・休日名称
            2023/1/1,元日
            ,名前だけ
            2023/1/9,
        """)
        result = parse_holidays(csv_empty_fields)
        assert len(result) == 1
        assert result[0]["name"] == "元日"


# ---------------------------------------------------------------------------
# フィルタ系テスト
# ---------------------------------------------------------------------------


class TestFilterHolidays:
    @pytest.fixture()
    def holidays(self):
        return parse_holidays(SAMPLE_CSV)

    def test_filter_holidays_year_range(self, holidays):
        """年範囲フィルタの正常系・境界値"""
        result = filter_holidays(holidays, start=2023, end=2024)
        years = {_holiday_year(h) for h in result}
        assert years == {2023, 2024}
        # 2025 年のデータは含まれない
        assert all(_holiday_year(h) <= 2024 for h in result)
        assert all(_holiday_year(h) >= 2023 for h in result)

    def test_filter_holidays_single_year(self, holidays):
        """単一年フィルタ（start=end）"""
        result = filter_holidays(holidays, start=2024, end=2024)
        assert len(result) == 2
        assert all(_holiday_year(h) == 2024 for h in result)

    def test_filter_holidays_start_only(self, holidays):
        """start のみ指定"""
        result = filter_holidays(holidays, start=2024)
        assert all(_holiday_year(h) >= 2024 for h in result)
        # 2024 と 2025 のデータが含まれる
        years = {_holiday_year(h) for h in result}
        assert years == {2024, 2025}

    def test_filter_holidays_end_only(self, holidays):
        """end のみ指定"""
        result = filter_holidays(holidays, end=2023)
        assert all(_holiday_year(h) <= 2023 for h in result)
        years = {_holiday_year(h) for h in result}
        assert years == {2023}

    def test_filter_holidays_no_match(self, holidays):
        """該当なしの場合"""
        result = filter_holidays(holidays, start=2030, end=2040)
        assert result == []

    def test_filter_holidays_no_args(self, holidays):
        """引数なし: 全件返却"""
        result = filter_holidays(holidays)
        assert len(result) == len(holidays)

    def test_filter_holidays_start_greater_than_end(self, holidays):
        """start > end: 空リストを返す"""
        result = filter_holidays(holidays, start=2025, end=2023)
        assert result == []


# ---------------------------------------------------------------------------
# _unique_years テスト
# ---------------------------------------------------------------------------


class TestUniqueYears:
    @pytest.fixture()
    def holidays(self):
        return parse_holidays(SAMPLE_CSV_MULTI_YEAR)

    def test_unique_years_empty(self):
        """空の祝日リスト"""
        result = _unique_years([])
        assert result == []

    def test_unique_years(self, holidays):
        """年の抽出"""
        result = _unique_years(holidays)
        assert result == [1990, 2000, 2010, 2020, 2023, 2024, 2025]

    def test_unique_years_decades(self, holidays):
        """年代の抽出（group_fn 使用）"""
        result = _unique_years(holidays, group_fn=lambda y: y // 10 * 10)
        assert result == [1990, 2000, 2010, 2020]

    def test_unique_years_with_start(self, holidays):
        """start フィルタ"""
        result = _unique_years(holidays, start=2010)
        assert result == [2010, 2020, 2023, 2024, 2025]

    def test_unique_years_decades_with_start(self, holidays):
        """年代 + start フィルタ"""
        result = _unique_years(holidays, group_fn=lambda y: y // 10 * 10, start=2000)
        assert result == [2000, 2010, 2020]


# ---------------------------------------------------------------------------
# _build_jobs テスト
# ---------------------------------------------------------------------------


class TestBuildJobs:
    @pytest.fixture()
    def holidays(self):
        return parse_holidays(SAMPLE_CSV)

    def test_build_jobs_all_enabled(self, holidays):
        """全エンドポイント有効時のジョブリスト構築"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": True,
            "decade": {"enabled": True, "start": 2020},
            "yearly": {"enabled": True, "start": 2023},
            "last_n_years": [3],
            "thisyear": True,
            "nextyear": True,
        }
        config: dict = {}
        jobs = _build_jobs(holidays, today, endpoints, config)
        filenames = [j[0] for j in jobs]
        assert "all.json" in filenames
        assert "2020s.json" in filenames
        assert "thisyear.json" in filenames
        assert "nextyear.json" in filenames
        assert "last3years.json" in filenames

    def test_build_jobs_all_disabled(self, holidays):
        """all エンドポイント無効"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": False},
            "last_n_years": [],
            "thisyear": False,
            "nextyear": False,
        }
        config: dict = {}
        jobs = _build_jobs(holidays, today, endpoints, config)
        assert jobs == []

    def test_build_jobs_yearly_with_start(self, holidays):
        """yearly の start 設定"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": True, "start": 2024},
            "last_n_years": [],
            "thisyear": False,
            "nextyear": False,
        }
        config: dict = {}
        jobs = _build_jobs(holidays, today, endpoints, config)
        filenames = [j[0] for j in jobs]
        assert "2024.json" in filenames
        assert "2025.json" in filenames
        assert "2023.json" not in filenames

    def test_build_jobs_last_n_years(self, holidays):
        """last_n_years のジョブ生成"""
        today = date(2025, 1, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": False},
            "last_n_years": [3, 5],
            "thisyear": False,
            "nextyear": False,
        }
        config: dict = {}
        jobs = _build_jobs(holidays, today, endpoints, config)
        filenames = [j[0] for j in jobs]
        assert "last3years.json" in filenames
        assert "last5years.json" in filenames

    def test_build_jobs_default_last_n_years_from_config(self, holidays):
        """last_n_years 未指定時の config デフォルト使用"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": False},
            "thisyear": False,
            "nextyear": False,
        }
        config = {"last_n_years": [3, 5]}
        jobs = _build_jobs(holidays, today, endpoints, config)
        filenames = [j[0] for j in jobs]
        assert "last3years.json" in filenames
        assert "last5years.json" in filenames

    def test_build_jobs_thisyear_filter(self, holidays):
        """thisyear は当年のみ含む"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": False},
            "last_n_years": [],
            "thisyear": True,
            "nextyear": False,
        }
        config: dict = {}
        jobs = _build_jobs(holidays, today, endpoints, config)
        assert len(jobs) == 1
        filename, filtered, label = jobs[0]
        assert filename == "thisyear.json"
        assert all(_holiday_year(h) == 2024 for h in filtered)

    def test_build_jobs_last_n_years_invalid(self, holidays, capsys):
        """last_n_years に 0 や負数が含まれる場合、警告してスキップ"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": False},
            "last_n_years": [3, 0, -5],
            "thisyear": False,
            "nextyear": False,
        }
        jobs = _build_jobs(holidays, today, endpoints, {})
        assert len(jobs) == 1
        assert jobs[0][0] == "last3years.json"
        captured = capsys.readouterr()
        assert "警告" in captured.out

    def test_build_jobs_nextyear_filter(self, holidays):
        """nextyear は翌年のみ含む"""
        today = date(2024, 6, 1)
        endpoints = {
            "all": False,
            "decade": {"enabled": False},
            "yearly": {"enabled": False},
            "last_n_years": [],
            "thisyear": False,
            "nextyear": True,
        }
        config: dict = {}
        jobs = _build_jobs(holidays, today, endpoints, config)
        assert len(jobs) == 1
        filename, filtered, label = jobs[0]
        assert filename == "nextyear.json"
        assert all(_holiday_year(h) == 2025 for h in filtered)


# ---------------------------------------------------------------------------
# ダウンロード系テスト（実サーバー）
# ---------------------------------------------------------------------------


class TestDownload:
    @pytest.mark.network
    def test_resolve_csv_url(self):
        """CKAN API から CSV URL を取得できること"""
        url = resolve_csv_url()
        assert url.startswith("https://")
        assert "csv" in url.lower() or "syukujitsu" in url.lower()

    @pytest.mark.network
    def test_fetch_csv_returns_utf8(self):
        """ダウンロードした CSV が UTF-8 文字列であること"""
        url = resolve_csv_url()
        csv_text = fetch_csv(url)
        assert isinstance(csv_text, str)
        # 日本語の祝日名が含まれる
        assert "元日" in csv_text
        # UTF-8 でエンコード可能であること
        csv_text.encode("utf-8")


# ---------------------------------------------------------------------------
# ハッシュ系テスト
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_content_hash_deterministic(self):
        """同一テキストで同じハッシュ"""
        text = "テスト文字列"
        h1 = _content_hash(text)
        h2 = _content_hash(text)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest length

    def test_content_hash_different(self):
        """異なるテキストで異なるハッシュ"""
        h1 = _content_hash("テスト1")
        h2 = _content_hash("テスト2")
        assert h1 != h2

    def test_load_content_hash_missing(self, tmp_path):
        """metadata.json が存在しない場合"""
        result = _load_content_hash(tmp_path)
        assert result is None

    def test_load_content_hash_valid(self, tmp_path):
        """metadata.json から正常にハッシュを読み込む"""
        meta = {"content_hash": "abc123"}
        (tmp_path / "metadata.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )
        result = _load_content_hash(tmp_path)
        assert result == "abc123"

    def test_load_content_hash_invalid_json(self, tmp_path):
        """不正な JSON の場合 None を返す"""
        (tmp_path / "metadata.json").write_text("not json", encoding="utf-8")
        result = _load_content_hash(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# ファイル I/O 系テスト
# ---------------------------------------------------------------------------


class TestWriteJson:
    def test_write_json(self, tmp_path):
        """JSON ファイルの書き出しとフォーマット"""
        path = tmp_path / "api" / "v1" / "test.json"
        holidays = [
            {"date": "2024-01-01", "name": "元日"},
            {"date": "2024-01-08", "name": "成人の日"},
        ]
        write_json(path, holidays, "test")
        assert path.exists()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["filter"] == "test"
        assert data["count"] == 2
        assert len(data["holidays"]) == 2
        assert data["holidays"][0]["name"] == "元日"
        assert data["holidays"][0]["date"] == "2024-01-01"
        assert data["holidays"][1]["date"] == "2024-01-08"
        assert "source" in data
        assert "generated_at" in data

    def test_write_json_empty_holidays(self, tmp_path):
        """空の祝日リストでの書き出し"""
        path = tmp_path / "empty.json"
        write_json(path, [], "empty")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["count"] == 0
        assert data["holidays"] == []

    def test_write_json_creates_parent_dirs(self, tmp_path):
        """親ディレクトリが自動作成される"""
        path = tmp_path / "deep" / "nested" / "dir" / "test.json"
        write_json(path, [], "test")
        assert path.exists()


class TestLoadConfig:
    def test_load_config(self, tmp_path):
        """config.yaml の読み込み"""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "endpoints": {
                "all": True,
                "decade": {"enabled": True, "start": 2000},
            }
        }
        config_path.write_text(
            yaml.dump(config_data, allow_unicode=True), encoding="utf-8"
        )
        result = load_config(config_path)
        assert result["endpoints"]["all"] is True
        assert result["endpoints"]["decade"]["start"] == 2000

    def test_load_config_missing(self, tmp_path):
        """存在しないファイルの場合"""
        config_path = tmp_path / "nonexistent.yaml"
        result = load_config(config_path)
        assert result == {}

    def test_load_config_invalid_yaml(self, tmp_path):
        """不正 YAML の場合"""
        config_path = tmp_path / "bad.yaml"
        config_path.write_text(":\n  :\n    - ][invalid", encoding="utf-8")
        result = load_config(config_path)
        assert result == {}

    def test_load_config_empty_file(self, tmp_path):
        """空ファイルの場合"""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("", encoding="utf-8")
        result = load_config(config_path)
        assert result == {}


# ---------------------------------------------------------------------------
# _holiday_year テスト
# ---------------------------------------------------------------------------


class TestHolidayYear:
    def test_holiday_year(self):
        """祝日の年を返す"""
        assert _holiday_year({"date": "2024-01-01", "name": "元日"}) == 2024
        assert _holiday_year({"date": "1990-12-23", "name": "天皇誕生日"}) == 1990
