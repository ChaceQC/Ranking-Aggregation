from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DATA_HOST = "https://board.xcpcio.com/data/"
BOARD_HOST = "https://board.xcpcio.com/"
CONTEST_LIST_URL = f"{DATA_HOST}index/contest_list.json"
DEFAULT_OUTPUT = "xcpcio_running_contests.json"
MANAGED_BY = "xcpcio_running_contests"
ENDED_CONTEST_KEEP_HOURS = 48
ACCEPTED_STATUSES = {"ACCEPTED", "CORRECT", "OK", "YES"}
PENDING_STATUSES = {"PENDING", "JUDGING", "COMPILING", "SUBMITTED"}
IGNORED_STATUSES = {"IGNORED", "SKIPPED"}
UNOFFICIAL_GROUPS = {"unofficial", "star", "stars"}


@dataclass
class ProblemCell:
    public_failed_count: int = 0
    public_pending_count: int = 0
    public_submit_count: int = 0
    sealed_submit_count: int = 0
    accepted_timestamp_ms: int | None = None
    accepted_order: tuple[int, str] | None = None

    @property
    def accepted(self) -> bool:
        return self.accepted_timestamp_ms is not None


@dataclass
class TeamState:
    team: dict[str, Any]
    cells: dict[str, ProblemCell] = field(default_factory=dict)
    solved_count: int = 0
    penalty_time: int = 0
    rank: int | str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取 XCPCIO 比赛列表或榜单数据，输出 main.py 可直接使用的 JSON。",
    )
    parser.add_argument(
        "--competition-id",
        default="provincial-contest/2026/sichuan",
        help="XCPCIO data 路径，例如 provincial-contest/2026/sichuan。",
    )
    parser.add_argument(
        "--data-url",
        default=None,
        help="XCPCIO data 基础 URL 或任一数据文件 URL，例如 .../sichuan/config.json。",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"输出 JSON 路径，默认 {DEFAULT_OUTPUT}。",
    )
    parser.add_argument(
        "--running",
        action="store_true",
        help="只抓取并输出 XCPCIO 正在进行的比赛列表。",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="同步写入的主配置文件路径，默认 config.json。",
    )
    parser.add_argument(
        "--update-config",
        dest="update_config",
        action="store_true",
        default=True,
        help="抓取 --running 时把发现到的比赛同步写入 config.json，默认开启。",
    )
    parser.add_argument(
        "--no-update-config",
        dest="update_config",
        action="store_false",
        help="只写输出 JSON，不修改 config.json。",
    )
    parser.add_argument(
        "--keep-ended-hours",
        type=int,
        default=ENDED_CONTEST_KEEP_HOURS,
        help=f"自动发现的已结束比赛保留小时数，默认 {ENDED_CONTEST_KEEP_HOURS}。",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="用于过滤/封榜计算的当前时间，ISO 格式；默认使用本机当前时间。",
    )
    return parser.parse_args()


def json_error_excerpt(text: str, position: int, radius: int = 220) -> str:
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    return repr(text[start:end])


def fetch_json(
    url: str,
    referer: str = "https://board.xcpcio.com/",
    retries: int = 3,
) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
            "Referer": referer,
        },
    )
    last_error: Exception | None = None
    attempts = max(int(retries), 1)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                encoding = response.headers.get("content-encoding", "").lower()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 or attempt == attempts:
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"请求 XCPCIO JSON 失败：url={url} error={exc}") from exc
            last_error = exc
        else:
            try:
                if encoding == "gzip" or raw.startswith(b"\x1f\x8b"):
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8")
                return json.loads(text)
            except (gzip.BadGzipFile, EOFError, OSError) as exc:
                if attempt == attempts:
                    raise RuntimeError(f"XCPCIO JSON 解压失败：url={url} error={exc}") from exc
                last_error = exc
            except UnicodeDecodeError as exc:
                if attempt == attempts:
                    raise RuntimeError(f"XCPCIO JSON 不是 UTF-8：url={url} error={exc}") from exc
                last_error = exc
            except json.JSONDecodeError as exc:
                if attempt == attempts:
                    excerpt = json_error_excerpt(text, exc.pos)
                    raise RuntimeError(
                        "XCPCIO JSON 解析失败："
                        f"url={url} line={exc.lineno} column={exc.colno} "
                        f"position={exc.pos} excerpt={excerpt}"
                    ) from exc
                last_error = exc

        if attempt < attempts:
            time.sleep(0.5 * attempt)

    raise RuntimeError(f"请求 XCPCIO JSON 失败：url={url} error={last_error}")


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="",
    )
    temp_path.replace(path)


def parse_now(value: str | None = None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()


def timestamp_ms(value: Any) -> int:
    if value is None:
        return 0
    number = int(value)
    if abs(number) < 10_000_000_000:
        return number * 1000
    return number


def iso_from_timestamp(value: Any) -> str:
    number = timestamp_ms(value)
    if number <= 0:
        return ""
    return datetime.fromtimestamp(number / 1000).astimezone().isoformat(timespec="seconds")


def normalize_data_base_url(competition_id: str, data_url: str | None = None) -> str:
    if data_url:
        url = data_url.strip()
        if not url.endswith("/"):
            url = url.rsplit("/", 1)[0] + "/"
        return url
    path = competition_id.strip("/")
    return urllib.parse.urljoin(DATA_HOST, f"{path}/")


def contest_list_url(now: datetime | None = None) -> str:
    current_time = now or datetime.now().astimezone()
    bucket = int(current_time.timestamp() * 1000) // (5 * 60 * 1000)
    return f"{CONTEST_LIST_URL}?t={bucket}"


def contest_name(config: dict[str, Any]) -> str:
    return str(config.get("contest_name") or config.get("name") or "")


def contest_is_running(item: dict[str, Any], now: datetime | None = None) -> bool:
    current_time = now or datetime.now().astimezone()
    current_ms = int(current_time.timestamp() * 1000)
    return timestamp_ms(item.get("start_time")) <= current_ms < timestamp_ms(item.get("end_time"))


def flatten_contest_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    contests: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if "config" in node and isinstance(node.get("config"), dict):
            config = node["config"]
            board_link = str(node.get("board_link") or "")
            contests.append(
                {
                    "name": contest_name(config),
                    "start_time": config.get("start_time"),
                    "end_time": config.get("end_time"),
                    "start_at": iso_from_timestamp(config.get("start_time")),
                    "end_at": iso_from_timestamp(config.get("end_time")),
                    "board_link": board_link,
                    "competition_id": board_link.strip("/"),
                    "source": "xcpcio",
                    "raw": node,
                },
            )
            return
        for child in node.values():
            visit(child)

    visit(data)
    return contests


def collect_running_contests(now: datetime | None = None) -> list[dict[str, Any]]:
    current_time = now or datetime.now().astimezone()
    data = fetch_json(contest_list_url(current_time))
    contests = [
        contest
        for contest in flatten_contest_list(data)
        if contest_is_running(contest, current_time)
    ]
    return sorted(
        contests,
        key=lambda item: (
            timestamp_ms(item.get("start_time")),
            timestamp_ms(item.get("end_time")),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )


def slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    chars: list[str] = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    slug = "".join(chars).strip("-")
    return slug or "contest"


def competition_id_from_url(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if "board.xcpcio.com" not in parsed.netloc.lower():
        return ""

    path = parsed.path.strip("/")
    if path.startswith("data/"):
        path = path[5:]
    if path.endswith(".json"):
        path = path.rsplit("/", 1)[0]
    return path.strip("/")


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"contests": []}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"contests": raw}
    if isinstance(raw, dict):
        contests = raw.get("contests", [])
        if not isinstance(contests, list):
            raise ValueError(f"{path} 中 contests 必须是数组。")
        raw["contests"] = contests
        return raw
    raise ValueError(f"{path} 必须是 JSON 对象或数组。")


def config_identity(entry: dict[str, Any]) -> tuple[str, str] | None:
    source = str(entry.get("source") or "").strip().lower()
    if source == "auto":
        source = ""
    competition_id = str(entry.get("competition_id") or "").strip("/")

    if not competition_id:
        for key in ("data_url", "dataUrl", "ranking_url", "url", "contest_url"):
            competition_id = competition_id_from_url(entry.get(key))
            if competition_id:
                source = source or "xcpcio"
                break

    if not source or not competition_id:
        return None
    return source, competition_id


def contest_to_config_entry(
    contest: dict[str, Any],
    previous_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    competition_id = str(contest["competition_id"]).strip("/")
    return {
        "key": (previous_entry or {}).get("key") or f"xcpcio-{slugify(competition_id)}",
        "name": contest.get("name") or f"XCPCIO {competition_id}",
        "source": "xcpcio",
        "competition_id": competition_id,
        "managed_by": MANAGED_BY,
        "contest_url": urllib.parse.urljoin(BOARD_HOST, competition_id),
        "data_url": urllib.parse.urljoin(DATA_HOST, f"{competition_id}/"),
        "start_at": contest.get("start_at", ""),
        "end_at": contest.get("end_at", ""),
    }


def parse_config_datetime(value: Any) -> datetime | None:
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


def should_remove_ended_entry(entry: dict[str, Any], now: datetime, keep_hours: int) -> bool:
    end_at = parse_config_datetime(entry.get("end_at") or entry.get("endAt"))
    if end_at is None:
        return False
    return now >= end_at + timedelta(hours=max(0, keep_hours))


def merge_into_config(
    config_path: Path,
    contests: list[dict[str, Any]],
    keep_ended_hours: int = ENDED_CONTEST_KEEP_HOURS,
) -> dict[str, int]:
    config = load_config(config_path)
    kept_contests: list[dict[str, Any]] = []
    existing_identities: set[tuple[str, str]] = set()
    previous_managed_entries: dict[tuple[str, str], dict[str, Any]] = {}
    incoming_identities = {
        ("xcpcio", str(contest["competition_id"]).strip("/"))
        for contest in contests
        if contest.get("competition_id")
    }
    now = datetime.now().astimezone()
    replaced_managed = 0
    kept_recently_ended = 0
    removed_expired = 0

    for entry in config["contests"]:
        if not isinstance(entry, dict):
            kept_contests.append(entry)
            continue

        identity = config_identity(entry)
        is_managed_xcpcio = (
            entry.get("managed_by") == MANAGED_BY
            and identity is not None
            and identity[0] == "xcpcio"
        )
        if is_managed_xcpcio:
            previous_managed_entries[identity] = entry
            if identity in incoming_identities:
                replaced_managed += 1
                continue
            if should_remove_ended_entry(entry, now, keep_ended_hours):
                removed_expired += 1
                continue
            kept_recently_ended += 1
            kept_contests.append(entry)
            existing_identities.add(identity)
            continue

        kept_contests.append(entry)
        if identity is not None:
            existing_identities.add(identity)

    added = 0
    skipped = 0
    for contest in contests:
        identity = ("xcpcio", str(contest["competition_id"]).strip("/"))
        entry = contest_to_config_entry(contest, previous_managed_entries.get(identity))
        if identity in existing_identities:
            skipped += 1
            continue
        kept_contests.append(entry)
        existing_identities.add(identity)
        if identity not in previous_managed_entries:
            added += 1

    fetched_at = now.isoformat(timespec="seconds")
    config["contests"] = kept_contests
    config["xcpcio_discovery"] = {
        "managed_by": MANAGED_BY,
        "fetched_at": fetched_at,
        "source_url": CONTEST_LIST_URL,
        "count": len(contests),
        "added": added,
        "skipped_existing": skipped,
        "replaced_managed": replaced_managed,
        "kept_recently_ended": kept_recently_ended,
        "removed_expired": removed_expired,
        "ended_contest_keep_hours": keep_ended_hours,
    }
    atomic_write_json(config_path, config)
    return {
        "count": len(contests),
        "added": added,
        "skipped_existing": skipped,
        "replaced_managed": replaced_managed,
        "kept_recently_ended": kept_recently_ended,
        "removed_expired": removed_expired,
        "ended_contest_keep_hours": keep_ended_hours,
    }


def load_contest_data(
    competition_id: str,
    data_url: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    base_url = normalize_data_base_url(competition_id, data_url)
    config = fetch_json(urllib.parse.urljoin(base_url, "config.json"))
    teams = fetch_json(urllib.parse.urljoin(base_url, "team.json"))
    runs = fetch_json(urllib.parse.urljoin(base_url, "run.json"))
    organizations_ref = config.get("organizations") if isinstance(config, dict) else None
    organizations_url = "organizations.json"
    if isinstance(organizations_ref, dict) and organizations_ref.get("url"):
        organizations_url = str(organizations_ref["url"])
    organizations = fetch_json(urllib.parse.urljoin(base_url, organizations_url))
    return config, teams, runs, organizations


def i18n_text(value: Any, locale: str = "zh-CN") -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        texts = value.get("texts")
        if isinstance(texts, dict):
            fallback_lang = value.get("fallback_lang") or value.get("fallbackLang")
            return str(
                texts.get(locale)
                or texts.get(fallback_lang)
                or value.get("fallback")
                or next(iter(texts.values()), ""),
            )
        if value.get("fallback") is not None:
            return str(value["fallback"])
    return str(value)


def member_names(team: dict[str, Any]) -> str:
    names: list[str] = []
    for member in team.get("members") or []:
        if isinstance(member, dict):
            name = i18n_text(member.get("name"))
        else:
            name = i18n_text(member)
        if name:
            names.append(name)
    return " / ".join(names)


def problem_labels(config: dict[str, Any]) -> list[str]:
    values = config.get("problem_id") or config.get("problems") or []
    labels: list[str] = []
    for index, value in enumerate(values):
        if isinstance(value, dict):
            labels.append(str(value.get("label") or value.get("id") or chr(ord("A") + index)))
        else:
            labels.append(str(value))
    return labels


def problem_key_from_run(raw_problem_id: Any, labels: list[str]) -> str | None:
    if isinstance(raw_problem_id, int):
        if 0 <= raw_problem_id < len(labels):
            return labels[raw_problem_id]
        raw_index = raw_problem_id - 1
        if 0 <= raw_index < len(labels):
            return labels[raw_index]
    text = str(raw_problem_id)
    if text in labels:
        return text
    if text.isdigit():
        number = int(text)
        if 0 <= number < len(labels):
            return labels[number]
        if 1 <= number <= len(labels):
            return labels[number - 1]
    return None


def run_timestamp_ms(run: dict[str, Any], unit: str) -> int:
    timestamp = int(run.get("timestamp") or 0)
    if unit.lower().startswith("milli"):
        return timestamp
    return timestamp * 1000


def contest_cutoffs(config: dict[str, Any], now: datetime | None = None) -> tuple[int | None, int | None]:
    current_time = now or datetime.now().astimezone()
    current_ms = int(current_time.timestamp() * 1000)
    start_ms = timestamp_ms(config.get("start_time"))
    end_ms = timestamp_ms(config.get("end_time"))
    frozen_duration = int(config.get("frozen_time") or 0) * 1000
    freeze_start_ms = end_ms - frozen_duration
    if config.get("freeze_time") is not None:
        freeze_start_ms = timestamp_ms(config.get("freeze_time"))

    if start_ms <= 0 or end_ms <= 0 or current_ms >= end_ms:
        return None, None

    current_elapsed_ms = max(0, current_ms - start_ms)
    freeze_elapsed_ms = max(0, freeze_start_ms - start_ms)
    if current_ms >= freeze_start_ms:
        return freeze_elapsed_ms, current_elapsed_ms
    return current_elapsed_ms, current_elapsed_ms


def sorted_runs(runs: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, str]:
        fallback_order, run = item
        return int(run.get("timestamp") or 0), str(run.get("id") or fallback_order)

    return sorted(enumerate(runs), key=sort_key)


def is_unofficial(team: dict[str, Any]) -> bool:
    groups = {str(group).strip().lower() for group in team.get("group") or []}
    return bool(groups & UNOFFICIAL_GROUPS)


def format_problem_cell(cell: ProblemCell) -> str:
    hidden_count = cell.public_pending_count + cell.sealed_submit_count
    if cell.accepted_timestamp_ms is not None:
        text = str(cell.accepted_timestamp_ms // 60000)
        if cell.public_failed_count:
            text += f" (+{cell.public_failed_count})"
        if hidden_count:
            text += f" ? {hidden_count}"
        return text
    if cell.public_failed_count:
        text = f"+{cell.public_failed_count}"
        if hidden_count:
            text += f" ? {hidden_count}"
        return text
    if hidden_count:
        return f"? {hidden_count}"
    return ""


def cell_submit_count(cell: ProblemCell) -> int:
    return cell.public_submit_count + cell.sealed_submit_count


def cell_public_submit_count(cell: ProblemCell) -> int:
    return cell.public_submit_count


def penalty_minutes(cell: ProblemCell, penalty_seconds: int) -> int:
    if cell.accepted_timestamp_ms is None:
        return 0
    return cell.accepted_timestamp_ms // 60000 + cell.public_failed_count * (
        penalty_seconds // 60
    )


def build_team_states(
    config: dict[str, Any],
    teams: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    labels: list[str],
    now: datetime | None = None,
) -> dict[str, TeamState]:
    options = config.get("options") or {}
    timestamp_unit = str(options.get("submission_timestamp_unit") or "second")
    public_cutoff_ms, current_cutoff_ms = contest_cutoffs(config, now)
    team_states = {
        str(team.get("id")): TeamState(
            team=team,
            cells={label: ProblemCell() for label in labels},
        )
        for team in teams
    }

    for run_order, run in sorted_runs(runs):
        team_id = str(run.get("team_id") or "")
        team_state = team_states.get(team_id)
        if team_state is None:
            continue

        problem_key = problem_key_from_run(run.get("problem_id"), labels)
        if problem_key is None:
            continue

        timestamp = run_timestamp_ms(run, timestamp_unit)
        if timestamp < 0:
            continue
        if current_cutoff_ms is not None and timestamp > current_cutoff_ms:
            continue

        cell = team_state.cells[problem_key]
        if cell.accepted:
            continue

        status = str(run.get("status") or "").strip().upper()
        if status in IGNORED_STATUSES:
            continue

        if public_cutoff_ms is not None and timestamp > public_cutoff_ms:
            cell.sealed_submit_count += 1
            continue

        cell.public_submit_count += 1
        if status in ACCEPTED_STATUSES:
            cell.accepted_timestamp_ms = timestamp
            cell.accepted_order = (timestamp, str(run.get("id") or run_order))
        elif status in PENDING_STATUSES:
            cell.public_pending_count += 1
        else:
            cell.public_failed_count += 1

    penalty_seconds = int(config.get("penalty") or 1200)
    for team_state in team_states.values():
        team_state.solved_count = sum(
            1 for cell in team_state.cells.values() if cell.accepted
        )
        team_state.penalty_time = sum(
            penalty_minutes(cell, penalty_seconds)
            for cell in team_state.cells.values()
        )
    return team_states


def rank_team_states(team_states: list[TeamState]) -> list[TeamState]:
    sorted_states = sorted(
        team_states,
        key=lambda item: (
            -item.solved_count,
            item.penalty_time,
            str(item.team.get("name") or ""),
            str(item.team.get("id") or ""),
        ),
    )

    official_index = 0
    previous_score: tuple[int, int] | None = None
    previous_rank = 0
    for team_state in sorted_states:
        if is_unofficial(team_state.team):
            team_state.rank = "*"
            continue
        official_index += 1
        score = (team_state.solved_count, team_state.penalty_time)
        if score == previous_score:
            team_state.rank = previous_rank
        else:
            previous_rank = official_index
            team_state.rank = official_index
            previous_score = score
    return sorted_states


def build_problem_info(
    labels: list[str],
    team_states: list[TeamState],
    config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    balloon_colors = config.get("balloon_color") or []
    problem_info: dict[str, dict[str, Any]] = {}
    for label_index, label in enumerate(labels):
        accepted_states = [
            state
            for state in team_states
            if state.cells[label].accepted_order is not None
        ]
        first_accept_team_id = ""
        if accepted_states:
            first_accept = min(
                accepted_states,
                key=lambda state: state.cells[label].accepted_order or (10**18, ""),
            )
            first_accept_team_id = str(first_accept.team.get("id") or "")

        color = "#999"
        if label_index < len(balloon_colors) and isinstance(balloon_colors[label_index], dict):
            color = str(
                balloon_colors[label_index].get("background_color")
                or balloon_colors[label_index].get("color")
                or color,
            )

        problem_info[label] = {
            "label": label,
            "acceptCount": len(accepted_states),
            "submitCount": sum(cell_submit_count(state.cells[label]) for state in team_states),
            "fullScore": None,
            "balloonRgb": color,
            "firstAcceptTeamFid": first_accept_team_id,
        }
    return problem_info


def build_rows(
    team_states: list[TeamState],
    labels: list[str],
    organizations: list[dict[str, Any]],
    fetched_at: str,
) -> list[dict[str, Any]]:
    organization_names = {
        str(organization.get("id")): i18n_text(organization.get("name"))
        for organization in organizations
        if isinstance(organization, dict)
    }
    rows: list[dict[str, Any]] = []
    for display_no, team_state in enumerate(team_states, start=1):
        team = team_state.team
        team_id = str(team.get("id") or "")
        row = {
            "fetched_at": fetched_at,
            "display_no": display_no,
            "rank": team_state.rank,
            "display_rank": "*" if is_unofficial(team) else team_state.rank,
            "school_rank": "",
            "team_no": team.get("location") or team_id,
            "team_fid": team_id,
            "school_name": organization_names.get(str(team.get("organization_id") or ""), ""),
            "team_name": i18n_text(team.get("name")),
            "members": member_names(team),
            "solved_count": team_state.solved_count,
            "solving_time": team_state.penalty_time,
            "penalty_time": team_state.penalty_time,
            "ranking_update_at": "",
            "excluded": is_unofficial(team),
            "groups": team.get("group") or [],
        }
        for label in labels:
            cell = team_state.cells[label]
            text = format_problem_cell(cell)
            row[label] = text
            row[f"{label}_submits"] = cell_submit_count(cell)
            row.setdefault("problem_cells", {})[label] = {
                "text": text,
                "accepted": cell.accepted,
                "submitted": cell_submit_count(cell) > 0,
                "submit_count": cell_submit_count(cell),
                "public_submit_count": cell_public_submit_count(cell),
                "sealed_submit_count": cell.sealed_submit_count,
                "sealed": cell.sealed_submit_count > 0,
                "first_accept": False,
                "score_mode": False,
                "score": None,
                "full_score": None,
                "score_ratio": 0.0,
            }
        rows.append(row)
    return rows


def mark_first_accepts(rows: list[dict[str, Any]], problem_info: dict[str, dict[str, Any]]) -> None:
    for label, info in problem_info.items():
        first_team_id = str(info.get("firstAcceptTeamFid") or "")
        if not first_team_id:
            continue
        for row in rows:
            if str(row.get("team_fid") or "") == first_team_id:
                problem_cells = row.setdefault("problem_cells", {})
                if label in problem_cells:
                    problem_cells[label]["first_accept"] = True
                break


def normalize_contest_payload(
    config: dict[str, Any],
    teams: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    organizations: list[dict[str, Any]],
    fetched_at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    labels = problem_labels(config)
    team_states_map = build_team_states(config, teams, runs, labels, now)
    ranked_states = rank_team_states(list(team_states_map.values()))
    problem_info = build_problem_info(labels, ranked_states, config)
    rows = build_rows(ranked_states, labels, organizations, fetched_at)
    mark_first_accepts(rows, problem_info)

    competition = {
        "name": contest_name(config),
        "startAt": iso_from_timestamp(config.get("start_time")),
        "endAt": iso_from_timestamp(config.get("end_time")),
        "rankType": "ICPC",
        "rawRankType": "ICPC",
        "scoreMode": False,
        "xcpcio_config": config,
    }
    return {
        "fetched_at": fetched_at,
        "competition": competition,
        "problem_info": problem_info,
        "rank_type": "ICPC",
        "score_mode": False,
        "rows": rows,
    }


def fetch_contest_payload(
    competition_id: str,
    fetched_at: str,
    data_url: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    config, teams, runs, organizations = load_contest_data(competition_id, data_url)
    return normalize_contest_payload(
        config,
        teams,
        runs,
        organizations,
        fetched_at,
        now=now,
    )


def write_running_contests(path: Path, contests: list[dict[str, Any]]) -> None:
    payload = {
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_url": CONTEST_LIST_URL,
        "count": len(contests),
        "contests": contests,
    }
    atomic_write_json(path, payload)


def main() -> int:
    args = parse_args()
    now = parse_now(args.now)
    if args.running:
        contests = collect_running_contests(now)
        write_running_contests(Path(args.output), contests)
        print(f"已写入 {len(contests)} 场 XCPCIO 正在进行比赛 -> {args.output}")
        if args.update_config:
            stats = merge_into_config(
                Path(args.config),
                contests,
                keep_ended_hours=args.keep_ended_hours,
            )
            print(
                f"已同步 {stats['count']} 场 XCPCIO 正在进行比赛 -> {args.config} "
                f"(新增 {stats['added']}，跳过已有 {stats['skipped_existing']}，"
                f"替换自动项 {stats['replaced_managed']}，"
                f"保留结束未满 {stats['ended_contest_keep_hours']} 小时 "
                f"{stats['kept_recently_ended']}，"
                f"移除超时结束项 {stats['removed_expired']})",
            )
        return 0

    fetched_at = now.isoformat(timespec="seconds")
    payload = fetch_contest_payload(
        args.competition_id,
        fetched_at=fetched_at,
        data_url=args.data_url,
        now=now,
    )
    atomic_write_json(Path(args.output), payload)
    print(f"已写入 {len(payload['rows'])} 支队伍 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
