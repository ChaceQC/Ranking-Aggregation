from __future__ import annotations

import argparse
import csv
import functools
import gzip
import html
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
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


@dataclass(frozen=True)
class OutputPaths:
    latest_csv: Path
    latest_json: Path
    latest_html: Path
    snapshot_csv: Path | None
    snapshot_json: Path | None
    snapshot_html: Path | None


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


def build_pintia_rankings_url(competition_id: str, team_excluded: str) -> str:
    query_filter = {"teamExcluded": team_excluded}
    query = urllib.parse.urlencode(
        {"filter": json.dumps(query_filter, ensure_ascii=False, separators=(",", ":"))},
    )
    return (
        f"https://pintia.cn/api/competitions/{competition_id}"
        f"/xcpc-rankings/public?{query}"
    )


def build_nowcoder_rankings_url(competition_id: str, page: int = 1) -> str:
    query = urllib.parse.urlencode(
        {
            "token": "",
            "id": competition_id,
            "page": page,
            "limit": 0,
            "_": int(time.time() * 1000),
        },
    )
    return (
        "https://ac.nowcoder.com/acm-heavy/acm/contest/real-time-rank-data?"
        f"{query}"
    )


def fetch_json(
    url: str,
    competition_id: str,
    cookie: str | None,
    referer: str | None = None,
) -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Referer": referer or f"https://pintia.cn/rankings/{competition_id}",
    }
    if cookie:
        headers["Cookie"] = cookie

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            encoding = response.headers.get("content-encoding", "").lower()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc

    if encoding == "gzip" or raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)

    return json.loads(raw.decode("utf-8"))


def sorted_problems(problem_info: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[str, str]:
        problem_id, info = item
        return (str(info.get("label", "")), problem_id)

    return sorted(problem_info.items(), key=sort_key)


def as_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_score_value(value: Any) -> str:
    score = as_float(value)
    if score.is_integer():
        return str(int(score))
    return f"{score:.2f}".rstrip("0").rstrip(".")


def is_nowcoder_score_rank_type(rank_type: Any) -> bool:
    return str(rank_type or "").strip().upper() in NOWCODER_SCORE_RANK_TYPES


def display_rank_type(rank_type: Any) -> str:
    rank_type_text = str(rank_type or "").strip().upper()
    return "IOI" if rank_type_text == "WEEKLY" else rank_type_text


def split_submit_counts(detail: dict[str, Any] | None) -> tuple[int, int, int]:
    if not detail:
        return 0, 0, 0

    valid_count = as_count(detail.get("validSubmitCount"))
    snapshot_count = detail.get("submitCountSnapshot")
    if snapshot_count is None:
        return valid_count, valid_count, 0

    snapshot_count = as_count(snapshot_count)
    public_submit_count = min(valid_count, snapshot_count)
    total_submit_count = max(valid_count, snapshot_count)
    sealed_submit_count = abs(valid_count - snapshot_count)
    return total_submit_count, public_submit_count, sealed_submit_count


def format_problem_cell(detail: dict[str, Any] | None) -> str:
    if not detail:
        return ""

    accept_time = detail.get("acceptTime")
    submit_count, public_submit_count, sealed_submit_count = split_submit_counts(detail)

    def failed_text() -> str:
        if not submit_count:
            return ""
        if sealed_submit_count and public_submit_count == 0:
            return f"? {sealed_submit_count}"
        text = f"+{public_submit_count}"
        return f"{text} ? {sealed_submit_count}" if sealed_submit_count else text

    if accept_time is None:
        return failed_text()
    if isinstance(accept_time, (int, float)) and accept_time < 0:
        return failed_text()

    public_wrong_count = max(0, public_submit_count - 1)
    if sealed_submit_count:
        public_wrong_text = f" (+{public_wrong_count})" if public_wrong_count else ""
        return f"{accept_time}{public_wrong_text} ? {sealed_submit_count}"
    if public_wrong_count:
        return f"{accept_time} (+{public_wrong_count})"
    return str(accept_time)


def minutes_from_milliseconds(value: Any) -> int:
    try:
        return int(value) // 60000
    except (TypeError, ValueError):
        return 0


def duration_from_milliseconds(value: Any) -> str:
    try:
        total_seconds = max(0, int(value) // 1000)
    except (TypeError, ValueError):
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def nowcoder_contest_minute(accepted_time: Any, contest_begin_time: Any) -> int | None:
    try:
        accepted_ms = int(accepted_time)
        begin_ms = int(contest_begin_time)
    except (TypeError, ValueError):
        return None
    if accepted_ms < 0 or begin_ms <= 0:
        return None
    return max(0, (accepted_ms - begin_ms) // 60000)


def format_nowcoder_cell(
    cell: dict[str, Any] | None,
    contest_begin_time: Any,
) -> tuple[str, int, int, int, bool]:
    if not cell:
        return "", 0, 0, 0, False

    failed_count = as_count(cell.get("failedCount"))
    waiting_count = as_count(cell.get("waitingJudgeCount"))
    accepted = bool(cell.get("accepted"))
    submit_count = failed_count + waiting_count + (1 if accepted else 0)

    suffix = f" ? {waiting_count}" if waiting_count else ""
    if accepted:
        accepted_minute = nowcoder_contest_minute(
            cell.get("acceptedTime"),
            cell.get("contestBeginTime") or contest_begin_time,
        )
        if accepted_minute is None:
            text = ""
        else:
            text = str(accepted_minute)
        if failed_count:
            text += f" (+{failed_count})"
        return f"{text}{suffix}", submit_count, submit_count - waiting_count, waiting_count, True

    if failed_count:
        return (
            f"+{failed_count}{suffix}",
            submit_count,
            failed_count,
            waiting_count,
            False,
        )
    if waiting_count:
        return f"? {waiting_count}", submit_count, 0, waiting_count, False
    return "", submit_count, 0, 0, False


def format_nowcoder_score_cell(
    cell: dict[str, Any] | None,
    fallback_full_score: Any = None,
) -> tuple[str, int, int, int, bool, float | None, float | None, float, bool]:
    if not cell:
        full_score = as_float(fallback_full_score) if fallback_full_score is not None else None
        return "", 0, 0, 0, False, None, full_score, 0.0, False

    failed_count = as_count(cell.get("failedCount"))
    waiting_count = as_count(cell.get("waitingJudgeCount"))
    raw_score = as_float(cell.get("score")) if cell.get("score") is not None else 0.0
    submitted = (
        bool(cell.get("submit"))
        or bool(cell.get("accepted"))
        or failed_count > 0
        or waiting_count > 0
        or raw_score > 0
    )
    score = as_float(cell.get("score")) if submitted else None
    full_score = as_float(cell.get("fullScore")) if cell.get("fullScore") is not None else None
    if (full_score is None or full_score <= 0) and fallback_full_score is not None:
        full_score = as_float(fallback_full_score)
    accepted = bool(cell.get("accepted")) or (
        score is not None and full_score is not None and full_score > 0 and score >= full_score
    )
    submit_count = failed_count + waiting_count + (1 if submitted else 0)
    public_submit_count = max(0, submit_count - waiting_count)

    if not submitted:
        return "", 0, 0, 0, False, None, full_score, 0.0, False

    if score is None:
        text = f"? {waiting_count}" if waiting_count else ""
    else:
        text = format_score_value(score)
        if waiting_count:
            text += f" ? {waiting_count}"

    score_ratio = 0.0
    if score is not None and full_score is not None and full_score > 0:
        score_ratio = max(0.0, min(1.0, score / full_score))

    return (
        text,
        submit_count,
        public_submit_count,
        waiting_count,
        accepted,
        score,
        full_score,
        score_ratio,
        submitted,
    )


def normalize_pintia_rankings(data: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    xcpc = data.get("xcpcRankings") or {}
    rankings = xcpc.get("rankings") or []
    problem_info = xcpc.get("problemInfoByProblemSetProblemId") or {}
    problems = sorted_problems(problem_info)

    rows: list[dict[str, Any]] = []
    for display_no, item in enumerate(rankings, start=1):
        team_info = item.get("teamInfo") or {}
        details = item.get("detailsByProblemSetProblemId") or {}
        team_fid = item.get("teamFid", "")
        team_no = team_info.get("remark") or team_fid

        row = {
            "fetched_at": fetched_at,
            "display_no": display_no,
            "rank": item.get("rank", ""),
            "display_rank": "*" if team_info.get("excluded") else item.get("rank", ""),
            "school_rank": item.get("schoolRank", ""),
            "team_no": team_no,
            "team_fid": team_fid,
            "school_name": team_info.get("schoolName", ""),
            "team_name": team_info.get("teamName", ""),
            "members": " / ".join(team_info.get("memberNames") or []),
            "solved_count": item.get("solvedCount", ""),
            "solving_time": item.get("solvingTime", ""),
            "penalty_time": item.get("penaltyTime", ""),
            "ranking_update_at": item.get("updateAt", ""),
            "excluded": team_info.get("excluded", ""),
        }

        for problem_id, info in problems:
            label = str(info.get("label") or problem_id)
            detail = details.get(problem_id)
            submit_count, public_submit_count, sealed_submit_count = split_submit_counts(detail)
            accept_time = (detail or {}).get("acceptTime")
            accepted = isinstance(accept_time, (int, float)) and accept_time >= 0
            row[label] = format_problem_cell(detail)
            row[f"{label}_submits"] = submit_count
            row.setdefault("problem_cells", {})[label] = {
                "text": row[label],
                "accepted": accepted,
                "submit_count": submit_count,
                "public_submit_count": public_submit_count,
                "sealed_submit_count": sealed_submit_count,
                "sealed": sealed_submit_count > 0,
                "first_accept": accepted
                and str(info.get("firstAcceptTeamFid", "")) == str(team_fid),
            }

        rows.append(row)

    return {
        "fetched_at": fetched_at,
        "competition": data.get("competitionBasicInfo") or {},
        "problem_info": problem_info,
        "rows": rows,
    }


def normalize_nowcoder_rankings(
    pages: list[dict[str, Any]],
    fetched_at: str,
    fallback_competition_id: str,
) -> dict[str, Any]:
    first_payload = pages[0] if pages else {}
    first_data = first_payload.get("data") or {}
    basic_info = first_data.get("basicInfo") or {}
    contest_id = basic_info.get("contestId") or fallback_competition_id
    raw_rank_type = str(basic_info.get("rankType") or "").upper()
    rank_type = display_rank_type(raw_rank_type)
    score_mode = is_nowcoder_score_rank_type(raw_rank_type)
    problem_data = first_data.get("problemData") or []

    problem_info: dict[str, dict[str, Any]] = {}
    for index, problem in enumerate(problem_data):
        problem_id = str(problem.get("problemId") or index + 1)
        label = str(problem.get("name") or chr(ord("A") + index))
        problem_info[problem_id] = {
            "label": label,
            "acceptCount": problem.get("acceptedCount", 0),
            "submitCount": problem.get("submitCount", 0),
            "fullScore": problem.get("score"),
            "balloonRgb": "#999",
            "firstAcceptTeamFid": "",
        }

    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for page in pages:
        page_data = page.get("data") or {}
        contest_begin_time = (
            (page_data.get("basicInfo") or {}).get("contestBeginTime")
            or basic_info.get("contestBeginTime")
        )
        for item in page_data.get("rankData") or []:
            team_fid = str(item.get("uid", ""))
            row_key = team_fid or str(len(rows) + 1)
            if row_key in seen_keys:
                continue
            seen_keys.add(row_key)
            display_no = len(rows) + 1
            rank = item.get("ranking", "")
            row = {
                "fetched_at": fetched_at,
                "display_no": display_no,
                "rank": rank,
                "display_rank": rank,
                "school_rank": "",
                "team_no": team_fid,
                "team_fid": team_fid,
                "school_name": item.get("school", ""),
                "team_name": item.get("userName", ""),
                "members": "",
                "solved_count": item.get("acceptedCount", ""),
                "total_score": format_score_value(item.get("totalScore"))
                if item.get("totalScore") is not None
                else "",
                "full_score": format_score_value(item.get("fullScore"))
                if item.get("fullScore") is not None
                else "",
                "solving_time": duration_from_milliseconds(item.get("reachTime"))
                if score_mode
                else minutes_from_milliseconds(item.get("penaltyTime")),
                "penalty_time": minutes_from_milliseconds(item.get("penaltyTime")),
                "ranking_update_at": "",
                "excluded": False,
            }
            score_by_problem_id = {
                str(cell.get("problemId")): cell
                for cell in item.get("scoreList") or []
                if isinstance(cell, dict)
            }

            for problem_id, info in sorted_problems(problem_info):
                label = str(info.get("label") or problem_id)
                cell = score_by_problem_id.get(problem_id)
                if score_mode:
                    (
                        text,
                        submit_count,
                        public_submit_count,
                        sealed_submit_count,
                        accepted,
                        score,
                        full_score,
                        score_ratio,
                        submitted,
                    ) = format_nowcoder_score_cell(cell, info.get("fullScore"))
                else:
                    text, submit_count, public_submit_count, sealed_submit_count, accepted = (
                        format_nowcoder_cell(cell, contest_begin_time)
                    )
                    score = None
                    full_score = None
                    score_ratio = 0.0
                    submitted = submit_count > 0
                row[label] = text
                row[f"{label}_submits"] = submit_count
                row.setdefault("problem_cells", {})[label] = {
                    "text": text,
                    "accepted": accepted,
                    "submitted": submitted,
                    "submit_count": submit_count,
                    "public_submit_count": public_submit_count,
                    "sealed_submit_count": sealed_submit_count,
                    "sealed": sealed_submit_count > 0,
                    "first_accept": bool((cell or {}).get("firstBlood")),
                    "score_mode": score_mode,
                    "score": score,
                    "full_score": full_score,
                    "score_ratio": score_ratio,
                }

            rows.append(row)

    competition = {
        "name": first_payload.get("competitionName")
        or basic_info.get("contestName")
        or f"Nowcoder {contest_id}",
        "startAt": "",
        "endAt": "",
        "rankType": rank_type,
        "rawRankType": raw_rank_type,
        "scoreMode": score_mode,
        "nowcoder_basic_info": basic_info,
    }
    if basic_info.get("contestBeginTime"):
        competition["startAt"] = datetime.fromtimestamp(
            int(basic_info["contestBeginTime"]) / 1000,
        ).astimezone().isoformat(timespec="seconds")
    if basic_info.get("contestEndTime"):
        competition["endAt"] = datetime.fromtimestamp(
            int(basic_info["contestEndTime"]) / 1000,
        ).astimezone().isoformat(timespec="seconds")

    return {
        "fetched_at": fetched_at,
        "competition": competition,
        "problem_info": problem_info,
        "rank_type": rank_type,
        "score_mode": score_mode,
        "rows": rows,
    }


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


def add_runtime_config(
    payload: dict[str, Any],
    args: argparse.Namespace,
    refresh_interval: int,
    contests: list[dict[str, Any]] | None = None,
    current_contest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload["config"] = {
        "refresh_interval_seconds": refresh_interval,
        "running_interval_seconds": resolve_running_interval(args),
        "ended_interval_seconds": resolve_ended_interval(args),
    }
    if contests and current_contest:
        payload["config"]["contests"] = contest_options(contests)
        payload["config"]["current_contest_id"] = current_contest["id"]
    return payload


def csv_headers(rows: list[dict[str, Any]], problem_info: dict[str, Any]) -> list[str]:
    base_headers = [
        "更新时间",
        "序号",
        "排名",
        "学校排名",
        "队伍序号",
        "队伍FID",
        "学校",
        "队名",
        "队员",
        "总分",
        "满分",
        "过题数",
        "总用时",
        "罚时",
        "榜单更新时间",
        "是否打星",
    ]
    problem_headers: list[str] = []
    for _, info in sorted_problems(problem_info):
        label = str(info.get("label", ""))
        if label:
            problem_headers.extend([label, f"{label}提交数"])
    return base_headers + problem_headers


def row_to_csv(row: dict[str, Any], problem_info: dict[str, Any]) -> dict[str, Any]:
    csv_row = {
        "更新时间": row["fetched_at"],
        "序号": row["display_no"],
        "排名": row["display_rank"],
        "学校排名": row["school_rank"],
        "队伍序号": row["team_no"],
        "队伍FID": row["team_fid"],
        "学校": row["school_name"],
        "队名": row["team_name"],
        "队员": row["members"],
        "总分": row.get("total_score", ""),
        "满分": row.get("full_score", ""),
        "过题数": row["solved_count"],
        "总用时": row["solving_time"],
        "罚时": row["penalty_time"],
        "榜单更新时间": row["ranking_update_at"],
        "是否打星": row["excluded"],
    }
    for _, info in sorted_problems(problem_info):
        label = str(info.get("label", ""))
        if label:
            csv_row[label] = row.get(label, "")
            csv_row[f"{label}提交数"] = row.get(f"{label}_submits", "")
    return csv_row


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_problem_summary(problem_info: dict[str, Any]) -> str:
    items = []
    for _, info in sorted_problems(problem_info):
        label = html_escape(info.get("label", ""))
        accept_count = html_escape(info.get("acceptCount", 0))
        submit_count = html_escape(info.get("submitCount", 0))
        color = html_escape(info.get("balloonRgb", "#999"))
        items.append(
            f'<span class="problem-pill">'
            f'<i style="background:{color}"></i>{label} '
            f'<b>{accept_count}</b>/<span>{submit_count}</span>'
            f"</span>"
        )
    return "".join(items)


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


def payload_is_running(payload: dict[str, Any], now: datetime | None = None) -> bool:
    competition = payload.get("competition") or {}
    start_at = parse_datetime_value(competition.get("startAt") or competition.get("start_at"))
    end_at = parse_datetime_value(competition.get("endAt") or competition.get("end_at"))
    current_time = now or datetime.now().astimezone()
    if start_at is not None and current_time < start_at:
        return False
    if end_at is not None and current_time >= end_at:
        return False
    return True


def refresh_interval_for_payload(
    payload: dict[str, Any],
    args: argparse.Namespace,
    now: datetime | None = None,
) -> int:
    if payload_is_running(payload, now):
        return resolve_running_interval(args)
    return resolve_ended_interval(args)


def script_json(payload: dict[str, Any]) -> str:
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        content.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html(payload: dict[str, Any]) -> str:
    competition = payload["competition"]
    problem_info = payload["problem_info"]
    rows = payload["rows"]
    refresh_interval = payload.get("config", {}).get(
        "refresh_interval_seconds",
        DEFAULT_RUNNING_INTERVAL_SECONDS,
    )
    title = competition.get("name") or "Pintia 榜单"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)} - 榜单</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --line: #d8dee8;
      --text: #18212f;
      --muted: #687489;
      --accent: #0f6abf;
      --rank: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 5;
      padding: 14px 20px 12px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 20px;
      line-height: 1.35;
      font-weight: 700;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      color: var(--muted);
      font-size: 13px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 12px;
      margin-top: 12px;
      font-size: 13px;
    }}
    .search-box {{
      width: min(360px, 100%);
      height: 32px;
      padding: 5px 10px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #fff;
      color: var(--text);
      font: inherit;
      outline: none;
    }}
    .search-box:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(15, 106, 191, 0.14);
    }}
    .toolbar button {{
      height: 32px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #fff;
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }}
    .toolbar button:hover {{ border-color: var(--accent); }}
    .contest-select {{
      margin-left: auto;
      height: 32px;
      max-width: min(440px, 100%);
      padding: 4px 28px 4px 8px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }}
    .contest-select:focus {{
      border-color: var(--accent);
      outline: none;
      box-shadow: 0 0 0 3px rgba(15, 106, 191, 0.14);
    }}
    .auto-refresh {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--muted);
      user-select: none;
    }}
    .toolbar-status {{
      color: var(--muted);
    }}
    main {{ padding: 16px 20px 24px; }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      background: var(--panel);
      max-height: calc(100vh - 190px);
    }}
    table {{
      width: max-content;
      min-width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px 10px;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
      text-align: center;
      vertical-align: middle;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: #eef3f9;
      color: #2e3a4d;
      font-weight: 700;
    }}
    tbody tr:nth-child(even) {{ background: #fafcff; }}
    tbody tr:hover {{ background: #eaf4ff; }}
    tbody tr.pinned-row > td {{
      position: sticky;
      top: var(--sticky-row-top, 34px);
      z-index: 6;
      background: #fff7ed;
      box-shadow: inset 0 -1px 0 var(--line);
    }}
    tbody tr.pinned-row > td:first-child {{ z-index: 9; }}
    tbody tr.pinned-row:hover > td {{ background: #ffedd5; }}
    th:first-child, td:first-child {{
      position: sticky;
      left: 0;
      z-index: 2;
      background: inherit;
    }}
    th:first-child {{ z-index: 12; background: #eef3f9; }}
    .school-name, .team-name {{
      text-align: left;
    }}
    .rank {{
      color: var(--rank);
      font-weight: 700;
    }}
    .team-name {{
      font-weight: 700;
    }}
    .team-name-text {{
      border-bottom: 1px dotted rgba(15, 106, 191, 0.45);
      cursor: help;
    }}
    .solved {{
      font-weight: 700;
      color: #067647;
    }}
    .problem-cell {{
      position: relative;
      min-width: 58px;
      font-weight: 600;
      --submits: 0;
      --intensity: max(0.18, calc(0.72 - min(var(--submits), 10) * 0.05));
    }}
    .problem-cell.accepted {{
      background: rgba(22, 163, 74, var(--intensity));
      color: #063f24;
    }}
    .problem-cell.score-positive {{
      background: rgba(22, 163, 74, var(--score-alpha, 0.42));
      color: #063f24;
    }}
    .problem-cell.rejected {{
      background: rgba(220, 38, 38, var(--intensity));
      color: #5f1111;
    }}
    .problem-cell.sealed {{
      background: rgba(37, 99, 235, var(--intensity));
      color: #102a60;
    }}
    .problem-cell.empty {{
      color: var(--muted);
    }}
    .problem-cell.first-accept::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 0;
      height: 0;
      border-top: 11px solid #f59e0b;
      border-right: 11px solid transparent;
    }}
    .problem-cell.first-accept::after {{
      content: "★";
      position: absolute;
      left: 1px;
      top: -1px;
      width: 10px;
      height: 10px;
      color: #fff;
      font-size: 7px;
      line-height: 10px;
      transform: scale(0.8);
      transform-origin: left top;
    }}
    .member-popover {{
      position: fixed;
      z-index: 30;
      max-width: 280px;
      padding: 9px 11px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #101828;
      color: #fff;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.22);
      font-size: 13px;
      line-height: 1.6;
      pointer-events: none;
    }}
    .member-popover[hidden] {{ display: none; }}
    .member-popover-title {{
      margin-bottom: 4px;
      color: #dbeafe;
      font-weight: 700;
    }}
    .member-popover-members {{
      color: #f8fafc;
      white-space: normal;
    }}
    .problem-header {{
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      line-height: 1.15;
    }}
    .problem-header-label {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-weight: 800;
    }}
    .problem-header-label i {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      border: 1px solid rgba(0, 0, 0, 0.18);
    }}
    .problem-header-count {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
    }}
    tbody tr.changed-row > td {{
      animation: row-flash 1.6s ease-in-out 2;
    }}
    @keyframes row-flash {{
      0%, 100% {{ box-shadow: inset 0 0 0 9999px rgba(255, 255, 255, 0); }}
      35% {{ box-shadow: inset 0 0 0 9999px rgba(250, 204, 21, 0.38); }}
      70% {{ box-shadow: inset 0 0 0 9999px rgba(14, 165, 233, 0.18); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{html_escape(title)}</h1>
    <div class="meta">
      <span id="updateTime">更新时间：{html_escape(payload["fetched_at"])}</span>
      <span id="contestClock">比赛用时：--:--:--</span>
      <span id="teamCount">队伍数：{len(rows)}</span>
      <span id="refreshStatus">{html_escape(refresh_interval)} 秒后自动刷新</span>
    </div>
    <div class="toolbar">
      <input id="rankFilter" class="search-box" type="search" placeholder="输入多个学校或队名置顶，用空格/逗号分隔" autocomplete="off">
      <button id="clearFilter" type="button">清空</button>
      <button id="refreshNow" type="button">刷新</button>
      <select id="contestSelect" class="contest-select" aria-label="选择榜单"></select>
      <label class="auto-refresh">
        <input id="autoRefresh" type="checkbox" checked>
        自动刷新
      </label>
      <span id="filterStatus" class="toolbar-status">置顶 0 / {len(rows)} 支队伍</span>
    </div>
  </header>
  <main>
    <div class="table-wrap">
      <table>
        <thead>
          <tr id="tableHeader"></tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </main>
  <div id="memberPopover" class="member-popover" hidden></div>
  <script id="initialPayload" type="application/json">{script_json(payload)}</script>
  <script>
    (function () {{
      var filterInput = document.getElementById("rankFilter");
      var clearButton = document.getElementById("clearFilter");
      var refreshNow = document.getElementById("refreshNow");
      var contestSelect = document.getElementById("contestSelect");
      var autoRefresh = document.getElementById("autoRefresh");
      var filterStatus = document.getElementById("filterStatus");
      var refreshStatus = document.getElementById("refreshStatus");
      var updateTimeNode = document.getElementById("updateTime");
      var contestClockNode = document.getElementById("contestClock");
      var teamCountNode = document.getElementById("teamCount");
      var titleNode = document.querySelector("h1");
      var tableHeader = document.getElementById("tableHeader");
      var tbody = document.querySelector("tbody");
      var memberPopover = document.getElementById("memberPopover");
      var rows = [];
      var currentPayload = JSON.parse(document.getElementById("initialPayload").textContent);
      var refreshSeconds = Math.max(
        1,
        Number((currentPayload.config || {{}}).refresh_interval_seconds || {DEFAULT_RUNNING_INTERVAL_SECONDS})
      );
      var previousRowSignatures = null;
      var filterKey = "pintia-ranking-filter:" + location.pathname;
      var autoKey = "pintia-ranking-auto-refresh:" + location.pathname;
      var contestKey = "pintia-ranking-contest:" + location.pathname;
      var secondsLeft = refreshSeconds;
      var refreshInFlight = false;
      var refreshAbortController = null;
      var refreshTimeoutId = null;

      function escapeHtml(value) {{
        return String(value == null ? "" : value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }}

      function normalize(value) {{
        return String(value || "").trim().toLocaleLowerCase();
      }}

      function parseKeywords(value) {{
        return normalize(value)
          .split(/[\\s,，;；|｜]+/)
          .map(function (keyword) {{ return keyword.trim(); }})
          .filter(Boolean);
      }}

      function sortedProblems(problemInfo) {{
        return Object.entries(problemInfo || {{}}).sort(function (left, right) {{
          var leftLabel = String((left[1] && left[1].label) || "");
          var rightLabel = String((right[1] && right[1].label) || "");
          return leftLabel.localeCompare(rightLabel) || left[0].localeCompare(right[0]);
        }});
      }}

      function pad2(value) {{
        return String(value).padStart(2, "0");
      }}

      function formatDuration(seconds) {{
        seconds = Math.max(0, Math.floor(seconds || 0));
        var hours = Math.floor(seconds / 3600);
        var minutes = Math.floor((seconds % 3600) / 60);
        var secs = seconds % 60;
        return hours + ":" + pad2(minutes) + ":" + pad2(secs);
      }}

      function formatDateTime(value) {{
        var date = new Date(value);
        if (Number.isNaN(date.getTime())) {{
          return value || "--";
        }}
        return date.toLocaleString("zh-CN", {{
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false
        }});
      }}

      function formatRelativeTime(value) {{
        var date = new Date(value);
        if (Number.isNaN(date.getTime())) {{
          return "";
        }}
        var seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
        if (seconds < 60) {{
          return seconds + " 秒前";
        }}
        var minutes = Math.floor(seconds / 60);
        if (minutes < 60) {{
          return minutes + " 分钟前";
        }}
        var hours = Math.floor(minutes / 60);
        return hours + " 小时前";
      }}

      function updateTimeDisplays() {{
        updateTimeNode.textContent = "更新时间：" + formatDateTime(currentPayload.fetched_at)
          + "（" + formatRelativeTime(currentPayload.fetched_at) + "）";

        var competition = currentPayload.competition || {{}};
        var startAt = new Date(competition.startAt || "");
        var endAt = new Date(competition.endAt || "");
        if (Number.isNaN(startAt.getTime())) {{
          contestClockNode.textContent = "比赛用时：--:--:--";
          return;
        }}
        var now = Date.now();
        if (now < startAt.getTime()) {{
          contestClockNode.textContent = "比赛用时：未开始";
          return;
        }}
        var effectiveNow = Number.isNaN(endAt.getTime()) ? now : Math.min(now, endAt.getTime());
        contestClockNode.textContent = "比赛用时：" + formatDuration((effectiveNow - startAt.getTime()) / 1000)
          + (!Number.isNaN(endAt.getTime()) && now > endAt.getTime() ? "（已结束）" : "");
      }}

      function rowSignature(row) {{
        var cells = row.problem_cells || {{}};
        var submitState = {{}};
        Object.keys(cells).sort().forEach(function (label) {{
          var cell = cells[label] || {{}};
            submitState[label] = {{
              text: cell.text || "",
              accepted: Boolean(cell.accepted),
              score: cell.score == null ? null : Number(cell.score),
              submit_count: Number(cell.submit_count || 0),
              sealed_submit_count: Number(cell.sealed_submit_count || 0)
            }};
        }});
        return JSON.stringify(submitState);
      }}

      function buildRowSignatures(payload) {{
        var signatures = {{}};
        (payload.rows || []).forEach(function (row) {{
          signatures[row.team_fid || row.team_no || row.display_no] = rowSignature(row);
        }});
        return signatures;
      }}

      function getContestOptions() {{
        return (currentPayload.config && currentPayload.config.contests) || [];
      }}

      function getCurrentContestId() {{
        return (currentPayload.config && currentPayload.config.current_contest_id) || "";
      }}

      function currentContestJson() {{
        var contestId = getCurrentContestId();
        var selected = getContestOptions().find(function (item) {{
          return item.id === contestId;
        }});
        return (selected && selected.json) || "latest.json";
      }}

      function renderContestSelect() {{
        var options = getContestOptions();
        if (!options.length) {{
          contestSelect.hidden = true;
          return;
        }}
        contestSelect.hidden = options.length <= 1;
        contestSelect.innerHTML = options.map(function (item) {{
          return '<option value="' + escapeHtml(item.id) + '">'
            + escapeHtml(item.name || item.id)
            + '</option>';
        }}).join("");
        contestSelect.value = getCurrentContestId();
      }}

      function renderTable(payload, changedTeamIds) {{
        var problemInfo = payload.problem_info || {{}};
        var problemEntries = sortedProblems(problemInfo);
        var changed = changedTeamIds || new Set();
        var scoreMode = Boolean(payload.score_mode || (payload.competition || {{}}).scoreMode);
        var baseLabels = scoreMode
          ? ["序号", "排名", "学校", "队名", "总分", "满分题", "用时"]
          : ["序号", "排名", "学校", "队名", "过题数", "总用时", "罚时"];
        var baseHeaders = baseLabels.map(function (label) {{
          return {{ html: escapeHtml(label) }};
        }});
        var problemHeaders = problemEntries.map(function (entry) {{
          var info = entry[1] || {{}};
          var label = info.label || entry[0];
          var fullScore = info.fullScore == null || info.fullScore === "" ? "" : " / " + escapeHtml(info.fullScore);
          return {{ html: '<span class="problem-header">'
            + '<span class="problem-header-label"><i style="background:' + escapeHtml(info.balloonRgb || "#999") + '"></i>'
            + escapeHtml(label) + '</span>'
            + '<span class="problem-header-count">' + escapeHtml(info.acceptCount || 0)
            + (scoreMode ? fullScore : ' / ' + escapeHtml(info.submitCount || 0)) + '</span>'
            + '</span>' }};
        }});
        tableHeader.innerHTML = baseHeaders.concat(problemHeaders).map(function (header) {{
          return "<th>" + header.html + "</th>";
        }}).join("");

        tbody.innerHTML = (payload.rows || []).map(function (row) {{
          var problemCells = problemEntries.map(function (entry) {{
            var label = entry[1] && entry[1].label || entry[0];
            var cell = (row.problem_cells || {{}})[label] || {{}};
            var submits = Number(cell.submit_count || 0);
            var classes = ["problem-cell"];
            var scoreCell = Boolean(cell.score_mode || scoreMode);
            var cellStyle = "--submits:" + submits;
            if (cell.sealed) {{
              classes.push("sealed");
            }} else if (scoreCell && cell.submitted) {{
              var score = Number(cell.score || 0);
              var ratio = Number(cell.score_ratio || 0);
              if (score > 0) {{
                classes.push(cell.accepted ? "accepted" : "score-positive");
                cellStyle += ";--score-alpha:" + (0.24 + Math.max(0, Math.min(1, ratio)) * 0.5).toFixed(3);
              }} else {{
                classes.push("rejected");
              }}
            }} else if (cell.accepted) {{
              classes.push("accepted");
            }} else if (submits > 0) {{
              classes.push("rejected");
            }} else {{
              classes.push("empty");
            }}
            if (cell.first_accept) {{
              classes.push("first-accept");
            }}
            return '<td class="' + classes.join(" ") + '" style="' + cellStyle + '">'
              + escapeHtml(cell.text || row[label] || "")
              + '</td>';
          }}).join("");
          var rowKey = row.team_fid || row.team_no || row.display_no;
          var rowClasses = changed.has(String(rowKey)) ? ' class="changed-row"' : '';
          return '<tr' + rowClasses + ' data-team-fid="' + escapeHtml(rowKey)
            + '" data-school="' + escapeHtml(row.school_name) + '" data-team="' + escapeHtml(row.team_name) + '">'
            + '<td class="number">' + escapeHtml(row.display_no) + '</td>'
            + '<td class="rank">' + escapeHtml(row.display_rank || row.rank) + '</td>'
            + '<td class="school-name">' + escapeHtml(row.school_name) + '</td>'
            + '<td class="team-name"><span class="team-name-text" data-members="'
            + escapeHtml(row.members) + '">' + escapeHtml(row.team_name) + '</span></td>'
            + '<td class="solved">' + escapeHtml(scoreMode ? (row.total_score || "") : row.solved_count) + '</td>'
            + '<td class="time">' + escapeHtml(scoreMode ? row.solved_count : row.solving_time) + '</td>'
            + '<td class="time">' + escapeHtml(scoreMode ? row.solving_time : row.penalty_time) + '</td>'
            + problemCells
            + '</tr>';
        }}).join("");
        rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
        bindMemberPopovers();
        applyFilter();
        rows.forEach(function (row) {{
          if (row.classList.contains("changed-row")) {{
            window.setTimeout(function () {{
              row.classList.remove("changed-row");
            }}, 3400);
          }}
        }});
      }}

      function renderPayload(payload) {{
        var newSignatures = buildRowSignatures(payload);
        var changedTeamIds = new Set();
        if (previousRowSignatures) {{
          Object.keys(newSignatures).forEach(function (teamId) {{
            if (previousRowSignatures[teamId] !== newSignatures[teamId]) {{
              changedTeamIds.add(String(teamId));
            }}
          }});
        }}
        previousRowSignatures = newSignatures;
        currentPayload = payload;
        refreshSeconds = Math.max(
          1,
          Number((currentPayload.config || {{}}).refresh_interval_seconds || {DEFAULT_RUNNING_INTERVAL_SECONDS})
        );
        var competition = payload.competition || {{}};
        titleNode.textContent = competition.name || "Pintia 榜单";
        document.title = titleNode.textContent + " - 榜单";
        renderContestSelect();
        updateTimeDisplays();
        teamCountNode.textContent = "队伍数：" + ((payload.rows || []).length);
        renderTable(payload, changedTeamIds);
      }}

      function applyFilter() {{
        var keywords = parseKeywords(filterInput.value);
        var pinnedGroups = keywords.map(function () {{ return []; }});
        var unpinned = [];
        rows.forEach(function (row) {{
          var target = normalize((row.dataset.school || "") + " " + (row.dataset.team || ""));
          var matchIndex = -1;
          for (var index = 0; index < keywords.length; index += 1) {{
            if (target.indexOf(keywords[index]) !== -1) {{
              matchIndex = index;
              break;
            }}
          }}
          row.classList.toggle("pinned-row", matchIndex !== -1);
          if (matchIndex !== -1) {{
            pinnedGroups[matchIndex].push(row);
          }} else {{
            unpinned.push(row);
          }}
        }});
        var pinned = [].concat.apply([], pinnedGroups);
        pinned.concat(unpinned).forEach(function (row) {{
          tbody.appendChild(row);
        }});
        updateStickyRows(pinned);
        filterStatus.textContent = "置顶 " + pinned.length + " / " + rows.length
          + " 支队伍" + (keywords.length ? "，关键词 " + keywords.length + " 个" : "");
        try {{
          localStorage.setItem(filterKey, filterInput.value);
        }} catch (error) {{}}
      }}

      function updateStickyRows(pinnedRows) {{
        var headerHeight = tableHeader.getBoundingClientRect().height || 34;
        pinnedRows.forEach(function (row, index) {{
          var rowHeight = row.getBoundingClientRect().height || 34;
          row.style.setProperty("--sticky-row-top", (headerHeight + index * rowHeight) + "px");
        }});
        rows.forEach(function (row) {{
          if (!row.classList.contains("pinned-row")) {{
            row.style.removeProperty("--sticky-row-top");
          }}
        }});
      }}

      function bindMemberPopovers() {{
        Array.prototype.slice.call(document.querySelectorAll(".team-name-text")).forEach(function (node) {{
          node.addEventListener("mouseenter", function () {{
            var members = node.dataset.members || "无队员信息";
            memberPopover.innerHTML = '<div class="member-popover-title">'
              + escapeHtml(node.textContent || "队伍")
              + '</div><div class="member-popover-members">'
              + escapeHtml(members).replace(/ \\/ /g, "<br>")
              + '</div>';
            memberPopover.hidden = false;
            positionMemberPopover(node);
          }});
          node.addEventListener("mousemove", function () {{
            positionMemberPopover(node);
          }});
          node.addEventListener("mouseleave", function () {{
            memberPopover.hidden = true;
          }});
        }});
      }}

      function positionMemberPopover(anchor) {{
        var rect = anchor.getBoundingClientRect();
        var left = Math.min(rect.left, window.innerWidth - 300);
        var top = rect.bottom + 8;
        if (top + memberPopover.offsetHeight > window.innerHeight) {{
          top = Math.max(8, rect.top - memberPopover.offsetHeight - 8);
        }}
        memberPopover.style.left = Math.max(8, left) + "px";
        memberPopover.style.top = top + "px";
      }}

      function updateRefreshStatus() {{
        if (refreshInFlight) {{
          refreshStatus.textContent = "正在更新…";
          return;
        }}
        refreshStatus.textContent = autoRefresh.checked
          ? secondsLeft + " 秒后自动刷新"
          : "自动刷新已暂停";
      }}

      try {{
        filterInput.value = localStorage.getItem(filterKey) || "";
        autoRefresh.checked = localStorage.getItem(autoKey) !== "0";
      }} catch (error) {{}}

      filterInput.addEventListener("input", applyFilter);
      clearButton.addEventListener("click", function () {{
        filterInput.value = "";
        applyFilter();
        filterInput.focus();
      }});
      refreshNow.addEventListener("click", function () {{
        try {{
          localStorage.setItem(filterKey, filterInput.value);
        }} catch (error) {{}}
        refreshData();
      }});
      autoRefresh.addEventListener("change", function () {{
        secondsLeft = refreshSeconds;
        try {{
          localStorage.setItem(autoKey, autoRefresh.checked ? "1" : "0");
        }} catch (error) {{}}
        updateRefreshStatus();
      }});
      contestSelect.addEventListener("change", function () {{
        var selectedId = contestSelect.value;
        var selected = getContestOptions().find(function (item) {{
          return item.id === selectedId;
        }});
        if (!selected) {{
          return;
        }}
        try {{
          localStorage.setItem(contestKey, selectedId);
        }} catch (error) {{}}
        previousRowSignatures = null;
        refreshData(selected.json);
      }});

      function refreshData(jsonFile) {{
        if (refreshInFlight) {{
          updateRefreshStatus();
          return;
        }}
        try {{
          localStorage.setItem(filterKey, filterInput.value);
        }} catch (error) {{}}
        if (!window.fetch || location.protocol === "file:") {{
          location.reload();
          return;
        }}
        refreshInFlight = true;
        refreshAbortController = window.AbortController ? new AbortController() : null;
        refreshTimeoutId = window.setTimeout(function () {{
          if (refreshAbortController) {{
            refreshAbortController.abort();
          }}
        }}, Math.max(15000, refreshSeconds * 1000));
        updateRefreshStatus();
        fetch((jsonFile || currentContestJson()) + "?ts=" + Date.now(), {{
          cache: "no-store",
          signal: refreshAbortController ? refreshAbortController.signal : undefined
        }})
          .then(function (response) {{
            if (!response.ok) {{
              throw new Error("HTTP " + response.status);
            }}
            return response.json();
          }})
          .then(function (payload) {{
            renderPayload(payload);
            secondsLeft = refreshSeconds;
            updateRefreshStatus();
          }})
          .catch(function () {{
            secondsLeft = Math.min(5, refreshSeconds);
          }})
          .finally(function () {{
            refreshInFlight = false;
            refreshAbortController = null;
            if (refreshTimeoutId) {{
              window.clearTimeout(refreshTimeoutId);
              refreshTimeoutId = null;
            }}
            updateRefreshStatus();
          }});
      }}

      applyFilter();
      renderPayload(currentPayload);
      try {{
        var savedContestId = localStorage.getItem(contestKey);
        var savedContest = getContestOptions().find(function (item) {{
          return item.id === savedContestId;
        }});
        if (savedContest && savedContest.id !== getCurrentContestId()) {{
          refreshData(savedContest.json);
        }}
      }} catch (error) {{}}
      updateRefreshStatus();
      window.setInterval(function () {{
        updateTimeDisplays();
        if (!autoRefresh.checked) {{
          updateRefreshStatus();
          return;
        }}
        if (refreshInFlight) {{
          updateRefreshStatus();
          return;
        }}
        secondsLeft -= 1;
        if (secondsLeft <= 0) {{
          refreshData();
          return;
        }}
        updateRefreshStatus();
      }}, 1000);
    }})();
  </script>
</body>
</html>
"""


def atomic_write_text(path: Path, content: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding=encoding, newline="")
    temp_path.replace(path)


def write_outputs(
    payload: dict[str, Any],
    paths: OutputPaths,
    include_html: bool = True,
) -> None:
    problem_info = payload["problem_info"]
    rows = payload["rows"]

    json_content = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write_text(paths.latest_json, json_content, encoding="utf-8")
    if paths.snapshot_json:
        atomic_write_text(paths.snapshot_json, json_content, encoding="utf-8")

    if include_html:
        html_content = render_html(payload)
        atomic_write_text(paths.latest_html, html_content, encoding="utf-8")
        if paths.snapshot_html:
            atomic_write_text(paths.snapshot_html, html_content, encoding="utf-8")

    headers = csv_headers(rows, problem_info)
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row_to_csv(row, problem_info))
    csv_content = buffer.getvalue()

    atomic_write_text(paths.latest_csv, csv_content, encoding="utf-8-sig")
    if paths.snapshot_csv:
        atomic_write_text(paths.snapshot_csv, csv_content, encoding="utf-8-sig")


def output_paths(output_dir: Path, timestamp: str, keep_history: bool) -> OutputPaths:
    latest_csv = output_dir / "latest.csv"
    latest_json = output_dir / "latest.json"
    latest_html = output_dir / "latest.html"
    if not keep_history:
        return OutputPaths(latest_csv, latest_json, latest_html, None, None, None)

    history_dir = output_dir / "history"
    return OutputPaths(
        latest_csv=latest_csv,
        latest_json=latest_json,
        latest_html=latest_html,
        snapshot_csv=history_dir / f"{timestamp}.csv",
        snapshot_json=history_dir / f"{timestamp}.json",
        snapshot_html=history_dir / f"{timestamp}.html",
    )


def output_paths_for_contest(
    output_dir: Path,
    timestamp: str,
    keep_history: bool,
    contest: dict[str, Any],
) -> OutputPaths:
    latest_csv = output_dir / contest_csv_name(contest)
    latest_json = output_dir / contest_json_name(contest)
    latest_html = output_dir / "latest.html"
    if not keep_history:
        return OutputPaths(latest_csv, latest_json, latest_html, None, None, None)

    history_dir = output_dir / "history"
    return OutputPaths(
        latest_csv=latest_csv,
        latest_json=latest_json,
        latest_html=latest_html,
        snapshot_csv=history_dir / contest_history_name(contest, timestamp, "csv"),
        snapshot_json=history_dir / contest_history_name(contest, timestamp, "json"),
        snapshot_html=None,
    )


def fetch_nowcoder_pages(
    competition_id: str,
    cookie: str | None,
) -> list[dict[str, Any]]:
    referer = f"https://ac.nowcoder.com/acm/contest/{competition_id}"
    print(
        f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
        f"获取牛客排名：contest={competition_id} page=1",
        flush=True,
    )
    first_page = fetch_json(
        build_nowcoder_rankings_url(competition_id, 1),
        competition_id,
        cookie,
        referer=referer,
    )
    if first_page.get("code") not in (0, None):
        raise RuntimeError(f"Nowcoder 接口错误：{first_page.get('msg') or first_page}")

    basic_info = ((first_page.get("data") or {}).get("basicInfo") or {})
    page_count = max(1, as_count(basic_info.get("pageCount")) or 1)
    pages = [first_page]
    for page in range(2, page_count + 1):
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"获取牛客排名：contest={competition_id} page={page}/{page_count}",
            flush=True,
        )
        payload = fetch_json(
            build_nowcoder_rankings_url(competition_id, page),
            competition_id,
            cookie,
            referer=referer,
        )
        if payload.get("code") not in (0, None):
            raise RuntimeError(f"Nowcoder 第 {page} 页接口错误：{payload.get('msg') or payload}")
        pages.append(payload)
    return pages


def fetch_contest_payload(
    contest: dict[str, Any],
    args: argparse.Namespace,
    cookie: str | None,
    fetched_at: str,
) -> dict[str, Any]:
    source = contest["source"]
    competition_id = str(contest["competition_id"])
    display_name = contest.get("display_name") or contest.get("name") or competition_id
    print(
        f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
        f"获取排名：source={source} contest={competition_id} name={display_name}",
        flush=True,
    )
    if source == "nowcoder":
        pages = fetch_nowcoder_pages(competition_id, cookie)
        payload = normalize_nowcoder_rankings(pages, fetched_at, competition_id)
    elif source == "xcpcio":
        import xcpcio

        data_url = contest.get("data_url") or contest.get("ranking_url")
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"获取 XCPCIO 数据：base={data_url or competition_id}",
            flush=True,
        )
        payload = xcpcio.fetch_contest_payload(
            competition_id,
            fetched_at,
            data_url=data_url,
            now=datetime.fromisoformat(fetched_at),
        )
    else:
        url = build_pintia_rankings_url(
            competition_id,
            str(contest.get("team_excluded") or args.team_excluded),
        )
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"获取 Pintia 排名：url={url}",
            flush=True,
        )
        data = fetch_json(
            url,
            competition_id,
            cookie,
            referer=f"https://pintia.cn/rankings/{competition_id}",
        )
        payload = normalize_pintia_rankings(data, fetched_at)

    if contest.get("name"):
        payload.setdefault("competition", {})["name"] = contest["name"]
    payload["source"] = source
    payload["competition_id"] = competition_id
    print(
        f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
        f"排名解析完成：source={source} contest={competition_id} rows={len(payload.get('rows') or [])}",
        flush=True,
    )
    return payload


def should_discover_nowcoder(args: argparse.Namespace) -> bool:
    return bool(args.discover_nowcoder) and not is_explicit_single_contest(args)


def should_discover_xcpcio(args: argparse.Namespace) -> bool:
    return bool(args.discover_xcpcio) and not is_explicit_single_contest(args)


def discover_nowcoder_contests(
    args: argparse.Namespace,
    last_discovery_at: float | None,
    force: bool = False,
) -> float | None:
    if not should_discover_nowcoder(args):
        return last_discovery_at

    now = time.monotonic()
    interval = max(args.discover_interval, 30)
    if not force and last_discovery_at is not None and now - last_discovery_at < interval:
        return last_discovery_at

    try:
        import nowcoder_running_contests

        urls = args.discover_urls or nowcoder_running_contests.DEFAULT_URLS
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"获取牛客比赛列表：{', '.join(urls)}",
            flush=True,
        )
        contests = nowcoder_running_contests.collect_running_contests(urls)
        nowcoder_running_contests.write_json(Path(args.discover_output), contests, urls)
        stats = nowcoder_running_contests.merge_into_config(
            Path(args.config),
            contests,
            urls,
            keep_ended_hours=args.discover_keep_ended_hours,
        )
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"牛客比赛发现：支持赛制正在进行 {stats['count']} 场，"
            f"新增 {stats['added']}，跳过已有 {stats['skipped_existing']}，"
            f"替换自动项 {stats['replaced_managed']}，"
            f"保留结束未满 {stats['ended_contest_keep_hours']} 小时 "
            f"{stats['kept_recently_ended']}，"
            f"移除超时结束项 {stats['removed_expired']} -> {args.config}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"牛客比赛发现失败：{exc}",
            file=sys.stderr,
            flush=True,
        )
    return now


def discover_xcpcio_contests(
    args: argparse.Namespace,
    last_discovery_at: float | None,
    force: bool = False,
) -> float | None:
    if not should_discover_xcpcio(args):
        return last_discovery_at

    now = time.monotonic()
    interval = max(args.discover_interval, 30)
    if not force and last_discovery_at is not None and now - last_discovery_at < interval:
        return last_discovery_at

    try:
        import xcpcio

        current_time = datetime.now().astimezone()
        print(
            f"[{current_time.isoformat(timespec='seconds')}] "
            f"获取 XCPCIO 比赛列表：{xcpcio.contest_list_url(current_time)}",
            flush=True,
        )
        contests = xcpcio.collect_running_contests(current_time)
        xcpcio.write_running_contests(Path(args.discover_xcpcio_output), contests)
        stats = xcpcio.merge_into_config(
            Path(args.config),
            contests,
            keep_ended_hours=args.discover_keep_ended_hours,
        )
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"XCPCIO 比赛发现：正在进行 {stats['count']} 场，"
            f"新增 {stats['added']}，跳过已有 {stats['skipped_existing']}，"
            f"替换自动项 {stats['replaced_managed']}，"
            f"保留结束未满 {stats['ended_contest_keep_hours']} 小时 "
            f"{stats['kept_recently_ended']}，"
            f"移除超时结束项 {stats['removed_expired']} -> {args.config}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
            f"XCPCIO 比赛发现失败：{exc}",
            file=sys.stderr,
            flush=True,
        )
    return now


def discover_contests(
    args: argparse.Namespace,
    last_discovery_at: dict[str, float | None],
    force: bool = False,
) -> dict[str, float | None]:
    last_discovery_at["nowcoder"] = discover_nowcoder_contests(
        args,
        last_discovery_at.get("nowcoder"),
        force=force,
    )
    last_discovery_at["xcpcio"] = discover_xcpcio_contests(
        args,
        last_discovery_at.get("xcpcio"),
        force=force,
    )
    return last_discovery_at


def update_once(
    args: argparse.Namespace,
    cookie: str | None,
    due_contest_ids: set[str] | None = None,
) -> tuple[Path, int, dict[str, int]]:
    now = datetime.now().astimezone()
    fetched_at = now.isoformat(timespec="seconds")
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    contests = load_contest_configs(args)
    payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for contest in contests:
        if due_contest_ids is not None and contest["id"] not in due_contest_ids:
            continue
        payload = fetch_contest_payload(contest, args, cookie, fetched_at)
        contest["display_name"] = (
            (payload.get("competition") or {}).get("name")
            or contest.get("name")
            or f'{contest["source"]} {contest["competition_id"]}'
        )
        competition = payload.get("competition") or {}
        if competition.get("startAt"):
            contest["start_at"] = competition["startAt"]
        if competition.get("endAt"):
            contest["end_at"] = competition["endAt"]
        payloads.append((contest, payload))

    legacy_paths = output_paths(output_dir, timestamp, args.history)
    if not payloads:
        return legacy_paths.latest_html, 0, {}

    total_rows = 0
    intervals: dict[str, int] = {}
    for contest, payload in payloads:
        refresh_interval = refresh_interval_for_payload(payload, args, now)
        intervals[contest["id"]] = refresh_interval
        add_runtime_config(payload, args, refresh_interval, contests, contest)
        paths = output_paths_for_contest(output_dir, timestamp, args.history, contest)
        write_outputs(payload, paths, include_html=False)
        total_rows += len(payload["rows"])

    primary_contest = max(
        contests,
        key=lambda item: (contest_start_sort_value(item), str(item.get("id", ""))),
    ) if contests else None
    primary_id = primary_contest["id"] if primary_contest else ""
    primary_entry = next(
        ((contest, payload) for contest, payload in payloads if contest["id"] == primary_id),
        None,
    )
    if primary_entry is not None:
        _, primary_payload = primary_entry
        write_outputs(primary_payload, legacy_paths, include_html=True)
    return legacy_paths.latest_html, total_rows, intervals


def due_contest_ids(args: argparse.Namespace, next_due_at: dict[str, float]) -> set[str]:
    contests = load_contest_configs(args)
    active_ids = {contest["id"] for contest in contests}
    for contest_id in list(next_due_at):
        if contest_id not in active_ids:
            del next_due_at[contest_id]

    if not next_due_at:
        return active_ids

    now = time.monotonic()
    return {
        contest["id"]
        for contest in contests
        if next_due_at.get(contest["id"], 0) <= now
    }


def next_discovery_wait_seconds(
    args: argparse.Namespace,
    last_discovery_at: dict[str, float | None],
) -> int | None:
    waits: list[int] = []
    enabled = {
        "nowcoder": should_discover_nowcoder(args),
        "xcpcio": should_discover_xcpcio(args),
    }
    if not any(enabled.values()):
        return None
    interval = max(args.discover_interval, 30)
    now = time.monotonic()
    for source, is_enabled in enabled.items():
        if not is_enabled:
            continue
        previous = last_discovery_at.get(source)
        if previous is None:
            return 0
        waits.append(max(1, int(interval - (now - previous))))
    return min(waits) if waits else None


def next_loop_wait_seconds(
    args: argparse.Namespace,
    next_due_at: dict[str, float],
    last_discovery_at: dict[str, float | None],
) -> int:
    now = time.monotonic()
    waits = [max(0, int(next_due - now)) for next_due in next_due_at.values()]
    discovery_wait = next_discovery_wait_seconds(args, last_discovery_at)
    if discovery_wait is not None:
        waits.append(discovery_wait)
    return min(waits) if waits else resolve_running_interval(args)


def run_update_loop(
    args: argparse.Namespace,
    cookie: str | None,
    stop_event: threading.Event | None = None,
    last_discovery_at: dict[str, float | None] | None = None,
) -> None:
    next_due_at: dict[str, float] = {}
    discovery_state = last_discovery_at or {"nowcoder": None, "xcpcio": None}
    while True:
        try:
            discovery_state = discover_contests(args, discovery_state)
            due_ids = due_contest_ids(args, next_due_at)
            if due_ids:
                latest_csv, row_count, intervals = update_once(args, cookie, due_ids)
                now_monotonic = time.monotonic()
                for contest_id, interval in intervals.items():
                    next_due_at[contest_id] = now_monotonic + interval
                print(
                    f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                    f"已更新 {row_count} 支队伍 -> {latest_csv}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                f"更新失败：{exc}",
                file=sys.stderr,
                flush=True,
            )
            if not args.watch and stop_event is None:
                raise

        if stop_event is None and not args.watch:
            return

        interval = next_loop_wait_seconds(args, next_due_at, discovery_state)
        if stop_event is None:
            time.sleep(interval)
        elif stop_event.wait(interval):
            return


def serve_output(args: argparse.Namespace, cookie: str | None) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate the first page before opening the server, so latest.html exists.
    last_discovery_at = discover_contests(
        args,
        {"nowcoder": None, "xcpcio": None},
        force=True,
    )
    latest_csv, row_count, _ = update_once(args, cookie)
    print(
        f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
        f"已更新 {row_count} 支队伍 -> {latest_csv}",
        flush=True,
    )

    stop_event = threading.Event()
    worker = threading.Thread(
        target=run_update_loop,
        args=(args, cookie, stop_event, last_discovery_at),
        daemon=True,
    )
    worker.start()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(output_dir))
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as server:
        server.daemon_threads = True
        url = f"http://{args.host}:{args.port}/latest.html"
        print(f"本地网页：{url}", flush=True)
        print("按 Ctrl+C 停止服务。", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n正在停止服务。", flush=True)
        finally:
            stop_event.set()
            server.server_close()
    return 0


def main() -> int:
    configure_stdio()
    args = parse_args()
    cookie = load_cookie(args)
    if not cookie:
        print(
            "提示：未读取到 Cookie。可把浏览器请求头里的 Cookie 内容放入 cookies.txt，"
            "或设置 PINTIA_COOKIE/NOWCODER_COOKIE。",
            file=sys.stderr,
        )

    if args.serve:
        return serve_output(args, cookie)

    try:
        run_update_loop(args, cookie)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
