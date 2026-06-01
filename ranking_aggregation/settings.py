from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_COMPETITION_ID = "2056635464310784000"
DEFAULT_RUNNING_INTERVAL_SECONDS = 10
DEFAULT_ENDED_INTERVAL_SECONDS = 300
DEFAULT_OUTPUT_DIR = "rankings"
DEFAULT_COOKIE_FILE = "cookies.txt"
DEFAULT_CONFIG_FILE = "config.json"
DEFAULT_DISCOVER_INTERVAL_SECONDS = 300
DEFAULT_NOWCODER_DISCOVERY_OUTPUT = "nowcoder_running_contests.json"
DEFAULT_XCPCIO_DISCOVERY_OUTPUT = "xcpcio_running_contests.json"
NOWCODER_SCORE_RANK_TYPES = {"IOI", "OI", "NOIP", "WEEKLY"}



def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取 XCPC 榜单，导出 CSV/JSON/HTML，并可定时更新。",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "pintia", "nowcoder", "xcpcio"),
        default="auto",
        help="榜单来源，默认 auto；可选 pintia 或 nowcoder。",
    )
    parser.add_argument(
        "--ranking-url",
        default=None,
        help="榜单页面或接口 URL；设置后会自动识别来源和比赛 ID。",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"多比赛配置文件路径，默认 {DEFAULT_CONFIG_FILE}。",
    )
    parser.add_argument(
        "--competition-id",
        default=DEFAULT_COMPETITION_ID,
        help=f"竞赛 ID，默认 Pintia {DEFAULT_COMPETITION_ID}；牛客可填 136164。",
    )
    parser.add_argument(
        "--cookie",
        default=None,
        help="直接传入 Cookie 请求头内容；优先级高于 PINTIA_COOKIE 和 cookies.txt。",
    )
    parser.add_argument(
        "--cookie-file",
        default=DEFAULT_COOKIE_FILE,
        help=f"Cookie 文件路径，默认 {DEFAULT_COOKIE_FILE}",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录，默认 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--team-excluded",
        default="NO_FILTER",
        choices=("NO_FILTER", "FALSE", "TRUE"),
        help="队伍过滤：NO_FILTER=全部，FALSE=正式队，TRUE=打星队。",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="兼容旧参数：同时设置进行中和已结束榜单刷新间隔秒数。",
    )
    parser.add_argument(
        "--running-interval",
        type=int,
        default=None,
        help=f"有未结束比赛时的刷新间隔秒数，默认 {DEFAULT_RUNNING_INTERVAL_SECONDS}。",
    )
    parser.add_argument(
        "--ended-interval",
        type=int,
        default=None,
        help=f"全部比赛已结束时的刷新间隔秒数，默认 {DEFAULT_ENDED_INTERVAL_SECONDS}。",
    )
    parser.add_argument(
        "--discover-nowcoder",
        dest="discover_nowcoder",
        action="store_true",
        default=True,
        help="多比赛配置模式下定时发现牛客正在进行的 ICPC 比赛并同步 config.json，默认开启。",
    )
    parser.add_argument(
        "--no-discover-nowcoder",
        dest="discover_nowcoder",
        action="store_false",
        help="不自动发现牛客正在进行的比赛。",
    )
    parser.add_argument(
        "--discover-xcpcio",
        dest="discover_xcpcio",
        action="store_true",
        default=True,
        help="多比赛配置模式下定时发现 XCPCIO 正在进行的比赛并同步 config.json，默认开启。",
    )
    parser.add_argument(
        "--no-discover-xcpcio",
        dest="discover_xcpcio",
        action="store_false",
        help="不自动发现 XCPCIO 正在进行的比赛。",
    )
    parser.add_argument(
        "--discover-interval",
        type=int,
        default=DEFAULT_DISCOVER_INTERVAL_SECONDS,
        help=f"比赛发现刷新间隔秒数，默认 {DEFAULT_DISCOVER_INTERVAL_SECONDS}。",
    )
    parser.add_argument(
        "--discover-url",
        action="append",
        dest="discover_urls",
        help="牛客比赛列表 URL，可重复传入；默认抓取 topCategoryFilter=13 和 14。",
    )
    parser.add_argument(
        "--discover-output",
        default=DEFAULT_NOWCODER_DISCOVERY_OUTPUT,
        help=f"牛客比赛发现结果 JSON 路径，默认 {DEFAULT_NOWCODER_DISCOVERY_OUTPUT}。",
    )
    parser.add_argument(
        "--discover-xcpcio-output",
        default=DEFAULT_XCPCIO_DISCOVERY_OUTPUT,
        help=f"XCPCIO 比赛发现结果 JSON 路径，默认 {DEFAULT_XCPCIO_DISCOVERY_OUTPUT}。",
    )
    parser.add_argument(
        "--discover-keep-ended-hours",
        type=int,
        default=48,
        help="自动发现的牛客已结束比赛保留小时数，默认 48。",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="持续运行并定时更新 latest.csv/latest.json。",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="每次更新同时保存一份带时间戳的历史快照。",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="启动本地网页服务，前端可无刷新读取 latest.json 更新表格。",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="--serve 监听地址，默认 127.0.0.1。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7877,
        help="--serve 监听端口，默认 7877。",
    )
    return parser.parse_args()


def normalize_cookie(cookie: str | None) -> str | None:
    if not cookie:
        return None
    lines = [line.strip() for line in cookie.splitlines() if line.strip()]
    if not lines:
        return None
    cookie = "; ".join(lines)
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    return cookie or None


def load_cookie(args: argparse.Namespace) -> str | None:
    if args.cookie:
        return normalize_cookie(args.cookie)

    env_cookie = os.environ.get("PINTIA_COOKIE") or os.environ.get("NOWCODER_COOKIE")
    if env_cookie:
        return normalize_cookie(env_cookie)

    cookie_file = Path(args.cookie_file)
    if cookie_file.exists():
        return normalize_cookie(cookie_file.read_text(encoding="utf-8"))

    return None


def resolve_running_interval(args: argparse.Namespace) -> int:
    value = args.running_interval if args.running_interval is not None else args.interval
    if value is None:
        value = DEFAULT_RUNNING_INTERVAL_SECONDS
    return max(int(value), 1)


def resolve_ended_interval(args: argparse.Namespace) -> int:
    value = args.ended_interval if args.ended_interval is not None else args.interval
    if value is None:
        value = DEFAULT_ENDED_INTERVAL_SECONDS
    return max(int(value), 1)



def slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    chars = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    slug = "".join(chars).strip("-")
    return slug or "contest"


def resolve_source(args: argparse.Namespace) -> str:
    if args.source != "auto":
        return args.source
    if args.ranking_url and "nowcoder.com" in args.ranking_url.lower():
        return "nowcoder"
    if args.ranking_url and "board.xcpcio.com" in args.ranking_url.lower():
        return "xcpcio"
    return "pintia"


def resolve_competition_id(args: argparse.Namespace, source: str) -> str:
    if args.ranking_url:
        parsed = urllib.parse.urlparse(args.ranking_url)
        if source == "xcpcio":
            path = parsed.path.strip("/")
            if path.startswith("data/"):
                path = path[5:]
            if path.endswith(".json"):
                path = path.rsplit("/", 1)[0]
            return path
        if source == "nowcoder":
            match = parsed.path.rstrip("/").split("/")
            for index, part in enumerate(match):
                if part == "contest" and index + 1 < len(match):
                    return match[index + 1]
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("id"):
                return query["id"][0]
        if source == "pintia":
            parts = parsed.path.rstrip("/").split("/")
            for index, part in enumerate(parts):
                if part == "competitions" and index + 1 < len(parts):
                    return parts[index + 1]
            if parts:
                return parts[-1]
    return str(args.competition_id)


def resolve_source_from_values(source: str, ranking_url: str | None) -> str:
    if source and source != "auto":
        return source
    if ranking_url and "nowcoder.com" in ranking_url.lower():
        return "nowcoder"
    if ranking_url and "board.xcpcio.com" in ranking_url.lower():
        return "xcpcio"
    return "pintia"


def resolve_competition_id_from_values(
    competition_id: Any,
    source: str,
    ranking_url: str | None,
) -> str:
    if ranking_url:
        parsed = urllib.parse.urlparse(ranking_url)
        if source == "xcpcio":
            path = parsed.path.strip("/")
            if path.startswith("data/"):
                path = path[5:]
            if path.endswith(".json"):
                path = path.rsplit("/", 1)[0]
            return path
        if source == "nowcoder":
            parts = parsed.path.rstrip("/").split("/")
            for index, part in enumerate(parts):
                if part == "contest" and index + 1 < len(parts):
                    return parts[index + 1]
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("id"):
                return query["id"][0]
        if source == "pintia":
            parts = parsed.path.rstrip("/").split("/")
            for index, part in enumerate(parts):
                if part == "competitions" and index + 1 < len(parts):
                    return parts[index + 1]
            if parts:
                return parts[-1]
    return str(competition_id)


def single_contest_from_args(args: argparse.Namespace) -> dict[str, Any]:
    source = resolve_source(args)
    competition_id = resolve_competition_id(args, source)
    contest_id = slugify(f"{source}-{competition_id}")
    return {
        "id": contest_id,
        "name": "",
        "source": source,
        "competition_id": competition_id,
        "ranking_url": args.ranking_url,
        "team_excluded": args.team_excluded,
    }


def normalize_contest_config(raw: dict[str, Any], index: int) -> dict[str, Any]:
    ranking_url = raw.get("ranking_url") or raw.get("url")
    source = resolve_source_from_values(str(raw.get("source", "auto")), ranking_url)
    competition_id = resolve_competition_id_from_values(
        raw.get("competition_id") or raw.get("competitionId") or raw.get("id"),
        source,
        ranking_url,
    )
    contest_id = str(raw.get("key") or raw.get("slug") or slugify(f"{source}-{competition_id}"))
    return {
        "id": contest_id,
        "name": raw.get("name", ""),
        "source": source,
        "competition_id": competition_id,
        "ranking_url": ranking_url,
        "team_excluded": raw.get("team_excluded", raw.get("teamExcluded", "NO_FILTER")),
        "data_url": raw.get("data_url") or raw.get("dataUrl"),
        "output_prefix": raw.get("output_prefix") or raw.get("outputPrefix") or contest_id,
        "start_at": raw.get("start_at") or raw.get("startAt") or "",
        "end_at": raw.get("end_at") or raw.get("endAt") or "",
    }


def load_contest_configs(args: argparse.Namespace) -> list[dict[str, Any]]:
    config_path = Path(args.config)
    explicit_single = is_explicit_single_contest(args)
    if config_path.exists() and not explicit_single:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        contests = raw_config.get("contests", raw_config if isinstance(raw_config, list) else [])
        if not isinstance(contests, list):
            raise ValueError("config.json 中 contests 必须是数组。")
        normalized = [
            normalize_contest_config(contest, index)
            for index, contest in enumerate(contests, start=1)
            if isinstance(contest, dict)
        ]
        if normalized:
            return normalized
    return [single_contest_from_args(args)]


def is_explicit_single_contest(args: argparse.Namespace) -> bool:
    return bool(args.ranking_url) or args.source != "auto" or (
        args.competition_id != DEFAULT_COMPETITION_ID
    )


def contest_json_name(contest: dict[str, Any]) -> str:
    return f"latest-{slugify(contest.get('output_prefix') or contest.get('id'))}.json"


def contest_csv_name(contest: dict[str, Any]) -> str:
    return f"latest-{slugify(contest.get('output_prefix') or contest.get('id'))}.csv"


def contest_history_name(contest: dict[str, Any], timestamp: str, suffix: str) -> str:
    return f"{timestamp}-{slugify(contest.get('output_prefix') or contest.get('id'))}.{suffix}"


def parse_datetime_value(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()


def contest_start_sort_value(contest: dict[str, Any]) -> float:
    start_at = parse_datetime_value(contest.get("start_at") or contest.get("startAt"))
    return start_at.timestamp() if start_at is not None else float("-inf")


def contest_options(contests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": contest["id"],
            "name": contest.get("display_name")
            or contest.get("name")
            or f'{contest["source"]} {contest["competition_id"]}',
            "source": contest["source"],
            "competition_id": contest["competition_id"],
            "json": contest_json_name(contest),
            "start_at": contest.get("start_at") or "",
        }
        for contest in sorted(
            contests,
            key=lambda item: (contest_start_sort_value(item), str(item.get("id", ""))),
            reverse=True,
        )
    ]
