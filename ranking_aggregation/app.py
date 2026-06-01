from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .delivery import (
    build_nowcoder_rankings_url,
    build_pintia_rankings_url,
    fetch_json,
    output_paths,
    output_paths_for_contest,
    write_outputs,
)
from .rankings import as_count, normalize_nowcoder_rankings, normalize_pintia_rankings
from .settings import (
    configure_stdio,
    contest_options,
    contest_start_sort_value,
    is_explicit_single_contest,
    load_contest_configs,
    load_cookie,
    parse_datetime_value,
    parse_args,
    resolve_ended_interval,
    resolve_running_interval,
)


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
        from .platforms import xcpcio

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
        from .platforms import nowcoder_running_contests

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
        from .platforms import xcpcio

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
