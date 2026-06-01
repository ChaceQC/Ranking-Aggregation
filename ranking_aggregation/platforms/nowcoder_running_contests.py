from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_URLS = [
    "https://ac.nowcoder.com/acm/contest/vip-index?topCategoryFilter=13",
    "https://ac.nowcoder.com/acm/contest/vip-index?topCategoryFilter=14",
]
DEFAULT_OUTPUT = "nowcoder_running_contests.json"
DEFAULT_CONFIG = "config.json"
MANAGED_BY = "nowcoder_running_contests"
ENDED_CONTEST_KEEP_HOURS = 48
SUPPORTED_RANK_TYPES = {"ICPC", "IOI", "OI", "NOIP", "WEEKLY"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取牛客当前正在进行的比赛，去重后写入 JSON。",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="牛客比赛列表 URL，可重复传入；默认抓取 topCategoryFilter=13 和 14。",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"输出 JSON 路径，默认 {DEFAULT_OUTPUT}。",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"同步写入的主配置文件路径，默认 {DEFAULT_CONFIG}。",
    )
    parser.add_argument(
        "--update-config",
        dest="update_config",
        action="store_true",
        default=True,
        help="把发现到的支持赛制正在进行比赛同步写入 config.json，默认开启。",
    )
    parser.add_argument(
        "--no-update-config",
        dest="update_config",
        action="store_false",
        help="只写 nowcoder_running_contests.json，不修改 config.json。",
    )
    parser.add_argument(
        "--keep-ended-hours",
        type=int,
        default=ENDED_CONTEST_KEEP_HOURS,
        help=f"自动发现的已结束比赛保留小时数，默认 {ENDED_CONTEST_KEEP_HOURS}。",
    )
    return parser.parse_args()


def json_error_excerpt(text: str, position: int, radius: int = 220) -> str:
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    return repr(text[start:end])


def fetch_text(url: str, retries: int = 3) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "identity",
            "Referer": "https://ac.nowcoder.com/",
        },
    )
    last_error: Exception | None = None
    attempts = max(int(retries), 1)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 or attempt == attempts:
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"请求牛客页面失败：url={url} error={exc}") from exc
            last_error = exc
        if attempt < attempts:
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"请求牛客页面失败：url={url} error={last_error}")


def fetch_json(url: str, referer: str, retries: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "identity",
            "Referer": referer,
        },
    )
    last_error: Exception | None = None
    attempts = max(int(retries), 1)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
            return json.loads(text)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 or attempt == attempts:
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"请求牛客 JSON 失败：url={url} error={exc}") from exc
            last_error = exc
        except json.JSONDecodeError as exc:
            if attempt == attempts:
                raise RuntimeError(
                    "牛客 JSON 解析失败："
                    f"url={url} line={exc.lineno} column={exc.colno} "
                    f"position={exc.pos} excerpt={json_error_excerpt(text, exc.pos)}"
                ) from exc
            last_error = exc
        if attempt < attempts:
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"请求牛客 JSON 失败：url={url} error={last_error}")


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_datetime(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp / 1000).astimezone().isoformat(timespec="seconds")


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_item_blocks(page_html: str) -> list[str]:
    blocks: list[str] = []
    div_pattern = re.compile(r"<div\s+[^>]*>", re.I)
    matches = []
    for match in div_pattern.finditer(page_html):
        class_names = attr_value(match.group(0), "class").split()
        if "platform-item" in class_names:
            matches.append(match)

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_html)
        blocks.append(page_html[start:end])
    return blocks


def attr_value(block: str, name: str) -> str:
    match = re.search(rf'\b{name}="([^"]*)"', block, re.I)
    return html.unescape(match.group(1)) if match else ""


def extract_href_and_title(block: str) -> tuple[str, str]:
    match = re.search(
        r'<a\s+[^>]*href="(/acm/contest/\d+)"[^>]*>(.*?)</a>',
        block,
        re.I | re.S,
    )
    if not match:
        return "", ""
    return html.unescape(match.group(1)), strip_tags(match.group(2))


def extract_status(block: str) -> str:
    match = re.search(
        r'<span\s+[^>]*class="[^"]*\bmatch-status\b[^"]*"[^>]*>(.*?)</span>',
        block,
        re.I | re.S,
    )
    return strip_tags(match.group(1)) if match else ""


def extract_info(block: str, class_name: str) -> str:
    match = re.search(
        rf'<li\s+[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>(.*?)</li>',
        block,
        re.I | re.S,
    )
    return strip_tags(match.group(1)) if match else ""


def parse_data_json(block: str) -> dict[str, Any]:
    value = attr_value(block, "data-json")
    if not value:
        return {}
    value = html.unescape(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def parse_category(url: str, data: dict[str, Any]) -> int:
    if data.get("topCategoryId") is not None:
        return parse_int(data.get("topCategoryId"))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return parse_int((query.get("topCategoryFilter") or ["0"])[0])


def parse_contest(block: str, source_url: str) -> dict[str, Any] | None:
    status = extract_status(block)
    if status != "比赛中":
        return None

    data = parse_data_json(block)
    href, title = extract_href_and_title(block)
    contest_id = attr_value(block, "data-id")
    if not contest_id and href:
        contest_id = href.rstrip("/").split("/")[-1]
    if not contest_id and data.get("contestId"):
        contest_id = str(data["contestId"])
    if not contest_id:
        return None

    contest_url = f"https://ac.nowcoder.com{href or f'/acm/contest/{contest_id}'}"
    title = data.get("contestName") or title
    ranking_url = (
        "https://ac.nowcoder.com/acm-heavy/acm/contest/real-time-rank-data"
        f"?token=&id={contest_id}&page=1&limit=0"
    )
    return {
        "id": contest_id,
        "competition_id": contest_id,
        "source": "nowcoder",
        "name": title,
        "title": title,
        "status": status,
        "url": contest_url,
        "category": parse_category(source_url, data),
        "organizer": extract_info(block, "user-icon").replace("主办方：", "")
        or data.get("creatorName")
        or "",
        "participants": parse_int(data.get("signUpCount")) or parse_int(
            re.sub(r"\D+", "", extract_info(block, "joins-icon")),
        ),
        "start_at": parse_datetime(data.get("contestStartTime")),
        "end_at": parse_datetime(data.get("contestEndTime")),
        "duration_seconds": parse_int(data.get("contestDuration")) // 1000,
        "rank_type": "",
        "ranking_url": ranking_url,
        "raw": {
            "signup_time": extract_info(block, "time-icon"),
            "contest_time": extract_info(block, "match-time-icon"),
        },
    }


def fetch_rank_type(contest: dict[str, Any]) -> str:
    payload = fetch_json(contest["ranking_url"], contest["url"])
    if payload.get("code") not in (0, None):
        raise RuntimeError(f"牛客榜单接口错误：{payload.get('msg') or payload}")
    basic_info = (payload.get("data") or {}).get("basicInfo") or {}
    return str(basic_info.get("rankType") or "")


def display_rank_type(rank_type: Any) -> str:
    rank_type_text = str(rank_type or "").strip().upper()
    return "IOI" if rank_type_text == "WEEKLY" else rank_type_text


def collect_running_contests(urls: list[str]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for url in urls:
        page_html = fetch_text(url)
        for block in extract_item_blocks(page_html):
            contest = parse_contest(block, url)
            if contest:
                rank_type = fetch_rank_type(contest)
                if rank_type not in SUPPORTED_RANK_TYPES:
                    continue
                contest["raw_rank_type"] = rank_type
                contest["rank_type"] = display_rank_type(rank_type)
                by_id[contest["id"]] = contest
    return sorted(
        by_id.values(),
        key=lambda item: (item.get("start_at") or "", item.get("id") or ""),
    )


def write_json(path: Path, contests: list[dict[str, Any]], urls: list[str]) -> None:
    payload = {
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_urls": urls,
        "count": len(contests),
        "contests": contests,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="",
    )
    temp_path.replace(path)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="",
    )
    temp_path.replace(path)


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
    competition_id = str(entry.get("competition_id") or "").strip()
    if not competition_id:
        url = str(entry.get("ranking_url") or entry.get("url") or entry.get("contest_url") or "")
        parsed = urllib.parse.urlparse(url)
        if "nowcoder.com" in parsed.netloc.lower():
            source = source or "nowcoder"
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("id"):
                competition_id = str(query["id"][0]).strip()
            else:
                parts = parsed.path.rstrip("/").split("/")
                for index, part in enumerate(parts):
                    if part == "contest" and index + 1 < len(parts):
                        competition_id = parts[index + 1]
                        break
    if not source or not competition_id:
        return None
    return source, competition_id


def contest_to_config_entry(
    contest: dict[str, Any],
    previous_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contest_id = str(contest["competition_id"])
    return {
        "key": (previous_entry or {}).get("key") or f"nowcoder-{contest_id}",
        "name": contest.get("name") or contest.get("title") or f"牛客比赛 {contest_id}",
        "source": "nowcoder",
        "competition_id": contest_id,
        "managed_by": MANAGED_BY,
        "rank_type": contest.get("rank_type") or "",
        "raw_rank_type": contest.get("raw_rank_type") or contest.get("rank_type") or "",
        "contest_url": contest.get("url", ""),
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
    urls: list[str],
    keep_ended_hours: int = ENDED_CONTEST_KEEP_HOURS,
) -> dict[str, int]:
    config = load_config(config_path)
    kept_contests: list[dict[str, Any]] = []
    existing_identities: set[tuple[str, str]] = set()
    previous_managed_entries: dict[tuple[str, str], dict[str, Any]] = {}
    incoming_identities = {
        ("nowcoder", str(contest["competition_id"]))
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
        is_managed_nowcoder = (
            entry.get("managed_by") == MANAGED_BY
            and identity is not None
            and identity[0] == "nowcoder"
        )
        if is_managed_nowcoder:
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
        identity = ("nowcoder", str(contest["competition_id"]))
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
    config["nowcoder_discovery"] = {
        "managed_by": MANAGED_BY,
        "fetched_at": fetched_at,
        "source_urls": urls,
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


def main() -> int:
    args = parse_args()
    urls = args.urls or DEFAULT_URLS
    contests = collect_running_contests(urls)
    write_json(Path(args.output), contests, urls)
    print(f"已写入 {len(contests)} 场比赛 -> {args.output}")
    if args.update_config:
        stats = merge_into_config(
            Path(args.config),
            contests,
            urls,
            keep_ended_hours=args.keep_ended_hours,
        )
        print(
            f"已同步 {stats['count']} 场支持赛制正在进行比赛 -> {args.config} "
            f"(新增 {stats['added']}，跳过已有 {stats['skipped_existing']}，"
            f"替换自动项 {stats['replaced_managed']}，"
            f"保留结束未满 {stats['ended_contest_keep_hours']} 小时 "
            f"{stats['kept_recently_ended']}，"
            f"移除超时结束项 {stats['removed_expired']})",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
