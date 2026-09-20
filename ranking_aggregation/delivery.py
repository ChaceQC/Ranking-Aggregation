from __future__ import annotations

import csv
import gzip
import html
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from .rankings import sorted_problems
from .settings import (
    DEFAULT_RUNNING_INTERVAL_SECONDS,
    contest_csv_name,
    contest_history_name,
    contest_json_name,
)

FAVICON_FILENAME = "favicon.ico"
FAVICON_SOURCE_PATH = Path(__file__).resolve().parents[1] / "assets" / FAVICON_FILENAME


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
    retries: int = 3,
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
                raise RuntimeError(f"请求榜单 JSON 失败：url={url} error={exc}") from exc
            last_error = exc
        else:
            try:
                if encoding == "gzip" or raw.startswith(b"\x1f\x8b"):
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8")
                return json.loads(text)
            except (gzip.BadGzipFile, EOFError, OSError) as exc:
                if attempt == attempts:
                    raise RuntimeError(f"榜单 JSON 解压失败：url={url} error={exc}") from exc
                last_error = exc
            except UnicodeDecodeError as exc:
                if attempt == attempts:
                    raise RuntimeError(f"榜单 JSON 不是 UTF-8：url={url} error={exc}") from exc
                last_error = exc
            except json.JSONDecodeError as exc:
                if attempt == attempts:
                    start = max(0, exc.pos - 220)
                    end = min(len(text), exc.pos + 220)
                    raise RuntimeError(
                        "榜单 JSON 解析失败："
                        f"url={url} line={exc.lineno} column={exc.colno} "
                        f"position={exc.pos} excerpt={text[start:end]!r}"
                    ) from exc
                last_error = exc
        if attempt < attempts:
            time.sleep(0.5 * attempt)

    raise RuntimeError(f"请求榜单 JSON 失败：url={url} error={last_error}")



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
    title = "榜单"
    initial_payload: dict[str, Any] = {}

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="favicon.ico" type="image/x-icon">
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
      --table-bottom-safe: 18px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      height: 100vh;
      height: 100dvh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    }}
    header {{
      flex: 0 0 auto;
      position: relative;
      z-index: 5;
      padding: 14px 20px 12px;
      border-bottom: 1px solid var(--line);
      background: #fff;
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
    .team-type-select,
    .contest-select {{
      height: 32px;
      padding: 4px 28px 4px 8px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }}
    .team-type-select {{
      min-width: 118px;
    }}
    .contest-select {{
      margin-left: auto;
      max-width: min(440px, 100%);
    }}
    .team-type-select:focus,
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
    .problem-summary {{
      display: none;
    }}
    .mobile-header-toggle {{
      display: none;
      align-items: center;
      justify-content: center;
      width: 56px;
      height: 22px;
      margin: 10px auto -4px;
      padding: 0;
      border: 0;
      border-radius: 11px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      touch-action: manipulation;
    }}
    .mobile-header-toggle:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }}
    .mobile-header-toggle-line {{
      position: relative;
      width: 28px;
      height: 10px;
    }}
    .mobile-header-toggle-line::before,
    .mobile-header-toggle-line::after {{
      content: "";
      position: absolute;
      top: 4px;
      width: 15px;
      height: 2px;
      border-radius: 999px;
      background: currentColor;
      transition: transform 160ms ease, background-color 160ms ease;
    }}
    .mobile-header-toggle-line::before {{
      left: 0;
      transform: rotate(-24deg);
      transform-origin: right center;
    }}
    .mobile-header-toggle-line::after {{
      right: 0;
      transform: rotate(24deg);
      transform-origin: left center;
    }}
    .mobile-header-toggle:active {{
      color: var(--accent);
    }}
    main {{
      flex: 1 1 auto;
      min-height: 0;
      padding: 16px 20px 24px;
      overflow: hidden;
    }}
    .table-wrap {{
      height: 100%;
      overflow: auto;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
      border: 1px solid var(--line);
      background: var(--panel);
    }}
    table {{
      width: max-content;
      min-width: 100%;
      table-layout: fixed;
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
    tbody tr > td {{ background: #fff; }}
    tbody tr:nth-child(even) > td {{ background: #fafcff; }}
    tbody tr:hover > td {{ background: #eaf4ff; }}
    tbody tr.virtual-spacer,
    tbody tr.virtual-spacer:hover {{
      background: transparent;
    }}
    tbody tr.virtual-spacer > td {{
      height: var(--spacer-height, 0px);
      padding: 0;
      border: 0;
      line-height: 0;
      background: transparent;
    }}
    tbody tr.virtual-spacer > td:first-child {{
      position: static;
    }}
    tbody tr.pinned-copy > td {{
      position: sticky;
      top: var(--sticky-row-top, 34px);
      z-index: 6;
      background: #fff7ed;
      box-shadow: inset 0 -1px 0 var(--line);
    }}
    tbody tr.pinned-copy > td:first-child {{ z-index: 9; }}
    tbody tr.pinned-copy:hover > td {{ background: #ffedd5; }}
    tbody tr.pinned-original > td {{
      background: #fffaf0;
    }}
    tbody tr.pinned-original:hover > td {{
      background: #ffedd5;
    }}
    th:first-child, td:first-child {{
      position: sticky;
      left: 0;
      z-index: 2;
    }}
    th:first-child {{ z-index: 12; background: #eef3f9; }}
    .school-name, .team-name {{
      text-align: left;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .rank {{
      color: var(--rank);
      font-weight: 700;
    }}
    .rank.medal-gold {{
      color: #6f4b00;
      background: #fff0a6;
    }}
    .rank.medal-silver {{
      color: #344054;
      background: #e4e9ef;
    }}
    .rank.medal-bronze {{
      color: #543b1c;
      background: #d9b978;
    }}
    tbody tr:hover > td.rank.medal-gold,
    tbody tr.pinned-copy > td.rank.medal-gold,
    tbody tr.pinned-original > td.rank.medal-gold {{
      background: #f4d66a;
    }}
    tbody tr:hover > td.rank.medal-silver,
    tbody tr.pinned-copy > td.rank.medal-silver,
    tbody tr.pinned-original > td.rank.medal-silver {{
      background: #cbd3dc;
    }}
    tbody tr:hover > td.rank.medal-bronze,
    tbody tr.pinned-copy > td.rank.medal-bronze,
    tbody tr.pinned-original > td.rank.medal-bronze {{
      background: #c79b55;
    }}
    tbody tr.pinned-copy:hover > td.rank.medal-gold,
    tbody tr.pinned-original:hover > td.rank.medal-gold {{
      background: #e7bb32;
    }}
    tbody tr.pinned-copy:hover > td.rank.medal-silver,
    tbody tr.pinned-original:hover > td.rank.medal-silver {{
      background: #aeb9c6;
    }}
    tbody tr.pinned-copy:hover > td.rank.medal-bronze,
    tbody tr.pinned-original:hover > td.rank.medal-bronze {{
      background: #ad7c37;
    }}
    .team-name {{
      font-weight: 700;
    }}
    .team-name-text, .school-name-text {{
      display: inline-block;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      vertical-align: bottom;
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
      background: var(--cell-bg);
      color: #063f24;
    }}
    .problem-cell.score-positive {{
      background: var(--cell-bg);
      color: #063f24;
    }}
    .problem-cell.rejected {{
      background: var(--cell-bg);
      color: #5f1111;
    }}
    .problem-cell.sealed {{
      background: var(--cell-bg);
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
    .mobile-detail-row,
    .mobile-detail-row[hidden] {{
      display: none;
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
    @media (max-width: 640px) {{
      header {{
        padding: 10px 10px 8px;
      }}
      h1 {{
        margin-bottom: 6px;
        font-size: 16px;
        line-height: 1.28;
      }}
      .meta {{
        gap: 4px 10px;
        font-size: 11px;
      }}
      .toolbar {{
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: 6px;
        margin-top: 8px;
        font-size: 12px;
      }}
      .search-box {{
        grid-column: 1 / -1;
        width: 100%;
      }}
      .team-type-select {{
        min-width: 0;
        width: 100%;
      }}
      .contest-select {{
        grid-column: 1 / -1;
        width: 100%;
        max-width: none;
        margin-left: 0;
      }}
      .auto-refresh,
      .toolbar-status {{
        grid-column: 1 / -1;
      }}
      .problem-summary:not([hidden]) {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
        gap: 4px;
        margin-top: 8px;
        padding-top: 7px;
        border-top: 1px solid var(--line);
      }}
      .problem-summary-items {{
        display: contents;
      }}
      .problem-summary.is-collapsed {{
        margin-top: 0;
        padding-top: 0;
        border-top: 0;
      }}
      .problem-summary.is-collapsed .problem-summary-items {{
        display: none;
      }}
      .problem-summary-toggle {{
        grid-column: -2 / -1;
        justify-self: end;
        align-self: end;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 26px;
        padding: 0;
        border: 0;
        border-radius: 4px;
        background: transparent;
        color: var(--muted);
        cursor: pointer;
        touch-action: manipulation;
      }}
      .problem-summary-toggle:hover,
      .problem-summary-toggle:active {{
        background: #eaf4ff;
        color: var(--accent);
      }}
      .problem-summary-toggle:focus-visible {{
        outline: 2px solid var(--accent);
        outline-offset: 2px;
      }}
      .problem-summary-toggle .mobile-header-toggle-line {{
        width: 14px;
        height: 8px;
      }}
      .problem-summary-toggle .mobile-header-toggle-line::before,
      .problem-summary-toggle .mobile-header-toggle-line::after {{
        top: 3px;
        width: 8px;
        height: 1.5px;
      }}
      .problem-summary.is-collapsed .mobile-header-toggle-line::before {{
        transform: rotate(24deg);
      }}
      .problem-summary.is-collapsed .mobile-header-toggle-line::after {{
        transform: rotate(-24deg);
      }}
      .problem-summary-pill {{
        min-width: 0;
        height: 26px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 3px;
        padding: 3px 4px;
        border: 1px solid var(--line);
        border-radius: 4px;
        background: #fafcff;
        color: var(--muted);
        font-size: 11px;
        line-height: 1;
        font-variant-numeric: tabular-nums;
      }}
      .problem-summary-label {{
        display: inline-flex;
        align-items: center;
        gap: 3px;
        color: var(--text);
        font-weight: 800;
      }}
      .problem-summary-label i {{
        width: 6px;
        height: 6px;
        flex: 0 0 auto;
        border: 1px solid rgba(0, 0, 0, 0.18);
        border-radius: 50%;
      }}
      .problem-summary-pill b {{
        color: #067647;
        font-weight: 800;
      }}
      .problem-summary-pill > span:last-child {{
        color: var(--muted);
      }}
      .ranking-row {{
        cursor: pointer;
      }}
      tbody tr.pinned-copy > td {{
        position: sticky;
        top: var(--sticky-row-top, 34px);
        z-index: 6;
        background: #fff7ed;
        box-shadow: inset 0 -1px 0 var(--line);
      }}
      tbody tr.pinned-copy > td.rank-col {{
        z-index: 9;
      }}
      .number-col,
      .school-col,
      .problem-col,
      .penalty-col,
      body.score-mode .solved-col {{
        display: none;
      }}
      col.number-col,
      col.school-col,
      col.problem-col,
      col.penalty-col,
      body.score-mode col.solved-col {{
        display: none;
        width: 0 !important;
      }}
      table {{
        width: 100%;
        min-width: 0;
        table-layout: fixed;
      }}
      col.rank-col {{ width: 14% !important; }}
      col.team-col {{ width: 48% !important; }}
      col.solved-col {{ width: 18% !important; }}
      col.duration-col {{ width: 20% !important; }}
      body.score-mode col.team-col {{ width: 44% !important; }}
      body.score-mode col.score-col {{ width: 20% !important; }}
      body.score-mode col.duration-col {{ width: 22% !important; }}
      .mobile-detail-row:not([hidden]) {{
        display: table-row;
      }}
      .mobile-detail-row > td {{
        padding: 0;
        border-right: 0;
        background: #f8fafc;
        text-align: left;
      }}
      #pinnedBody .mobile-detail-row > td {{
        position: sticky;
        top: var(--sticky-row-top);
        z-index: 6;
        background: #fff7ed;
      }}
      .mobile-detail-inner {{
        overflow: visible;
        padding: 8px 10px 10px;
        border-left: 3px solid rgba(15, 106, 191, 0.22);
      }}
      .mobile-detail-row.is-opening .mobile-detail-inner {{
        animation: mobile-detail-expand 180ms ease both;
      }}
      .mobile-detail-row.is-collapsing .mobile-detail-inner {{
        animation: mobile-detail-collapse 160ms ease both;
      }}
      .mobile-school-line {{
        display: flex;
        align-items: baseline;
        gap: 7px;
        min-width: 0;
      }}
      .mobile-school-name {{
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--text);
        font-weight: 700;
      }}
      .mobile-school-rank {{
        flex: 0 0 auto;
        color: var(--muted);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }}
      .mobile-members-line {{
        margin-top: 4px;
        color: var(--muted);
        font-size: 11px;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }}
      .mobile-problem-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
        gap: 4px;
        margin-top: 7px;
      }}
      .mobile-problem {{
        position: relative;
        min-width: 0;
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        grid-template-rows: auto auto;
        align-items: center;
        gap: 1px 4px;
        padding: 4px 5px;
        border: 1px solid var(--line);
        border-radius: 4px;
        background: #fff;
        color: var(--muted);
        font-variant-numeric: tabular-nums;
      }}
      .mobile-problem.accepted,
      .mobile-problem.score-positive,
      .mobile-problem.rejected,
      .mobile-problem.sealed {{
        background: var(--cell-bg);
      }}
      .mobile-problem.accepted,
      .mobile-problem.score-positive {{
        color: #063f24;
      }}
      .mobile-problem.rejected {{
        color: #5f1111;
      }}
      .mobile-problem.sealed {{
        color: #102a60;
      }}
      .mobile-problem-label {{
        grid-row: 1 / span 2;
        font-weight: 800;
      }}
      .mobile-problem-value {{
        min-width: 0;
        overflow: visible;
        text-align: right;
        white-space: nowrap;
        font-size: 12px;
        font-weight: 700;
      }}
      .team-col.team-name,
      .team-col .team-name-text {{
        overflow: visible;
        text-overflow: clip;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
        vertical-align: top;
      }}
      .team-col.team-name {{
        position: relative;
        padding-right: 22px;
      }}
      tbody tr.pinned-copy > td.team-col.team-name {{
        position: sticky;
        top: var(--sticky-row-top, 34px);
      }}
      .team-col.team-name::after {{
        content: "";
        position: absolute;
        top: 50%;
        right: 8px;
        width: 6px;
        height: 6px;
        border-right: 1.5px solid var(--muted);
        border-bottom: 1.5px solid var(--muted);
        transform: translateY(-70%) rotate(45deg);
        transition: transform 160ms ease, border-color 160ms ease;
      }}
      .ranking-row[aria-expanded="true"] .team-col.team-name::after {{
        border-color: var(--accent);
        transform: translateY(-25%) rotate(225deg);
      }}
      .mobile-school-name {{
        overflow: visible;
        text-overflow: clip;
        white-space: normal;
        overflow-wrap: anywhere;
      }}
      .mobile-problem.first-accept::before {{
        content: "";
        position: absolute;
        left: -1px;
        top: -1px;
        width: 0;
        height: 0;
        border-top: 9px solid #f59e0b;
        border-right: 9px solid transparent;
      }}
      .mobile-problem.first-accept::after {{
        content: "★";
        position: absolute;
        left: 0;
        top: -1px;
        color: #fff;
        font-size: 6px;
        line-height: 8px;
      }}
      @keyframes mobile-detail-expand {{
        from {{
          opacity: 0;
          transform: translateY(-5px);
        }}
        to {{
          opacity: 1;
          transform: translateY(0);
        }}
      }}
      @keyframes mobile-detail-collapse {{
        from {{
          opacity: 1;
          transform: translateY(0);
        }}
        to {{
          opacity: 0;
          transform: translateY(-5px);
        }}
      }}
      .mobile-header-toggle {{
        display: flex;
      }}
      body.mobile-header-collapsed header {{
        padding-top: 2px;
        padding-bottom: 2px;
      }}
      body.mobile-header-collapsed header h1,
      body.mobile-header-collapsed header .meta,
      body.mobile-header-collapsed header .toolbar {{
        display: none;
      }}
      body.mobile-header-collapsed .mobile-header-toggle {{
        margin-top: 0;
        margin-bottom: 0;
      }}
      body.mobile-header-collapsed header .mobile-header-toggle-line::before {{
        transform: rotate(24deg);
      }}
      body.mobile-header-collapsed header .mobile-header-toggle-line::after {{
        transform: rotate(-24deg);
      }}
      main {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 8px;
      }}
      .table-wrap {{
        flex: 1 1 auto;
        min-height: 0;
        height: auto;
        overflow-anchor: none;
        padding-bottom: env(safe-area-inset-bottom, 0px);
      }}
      table {{
        font-size: 12px;
      }}
      th, td {{
        padding: 7px 8px;
      }}
      :root {{
        --table-bottom-safe: 64px;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{html_escape(title)}</h1>
    <div class="meta">
      <span id="updateTime">更新时间：加载中</span>
      <span id="contestClock">比赛用时：--:--:--</span>
      <span id="teamCount">队伍数：--</span>
      <span id="refreshStatus">正在加载…</span>
    </div>
    <div class="toolbar">
      <input id="rankFilter" class="search-box" type="search" placeholder="输入多个学校或队名置顶，用空格/逗号分隔" autocomplete="off">
      <button id="clearFilter" type="button">清空</button>
      <select id="teamTypeFilter" class="team-type-select" aria-label="筛选队伍类型" hidden>
        <option value="all">全部队伍</option>
        <option value="official">正式队</option>
        <option value="unofficial">非正式队</option>
      </select>
      <button id="refreshNow" type="button">刷新</button>
      <select id="contestSelect" class="contest-select" aria-label="选择榜单"></select>
      <label class="auto-refresh">
        <input id="autoRefresh" type="checkbox" checked>
        自动刷新
      </label>
      <span id="filterStatus" class="toolbar-status">置顶 0 / 0 支队伍</span>
    </div>
    <button id="mobileHeaderToggle" class="mobile-header-toggle" type="button" aria-label="收起顶部展示栏" aria-expanded="true">
      <span class="mobile-header-toggle-line" aria-hidden="true"></span>
    </button>
  </header>
  <main>
    <div id="problemSummary" class="problem-summary" hidden aria-label="各题总答题情况">
      <div id="problemSummaryItems" class="problem-summary-items"></div>
      <button id="problemSummaryToggle" class="problem-summary-toggle" type="button" aria-label="收起题目统计" title="收起题目统计" aria-expanded="true" aria-controls="problemSummaryItems">
        <span class="mobile-header-toggle-line" aria-hidden="true"></span>
      </button>
    </div>
    <div class="table-wrap">
      <table>
        <colgroup id="tableColumns"></colgroup>
        <thead>
          <tr id="tableHeader"></tr>
        </thead>
        <tbody id="pinnedBody"></tbody>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </main>
  <div id="memberPopover" class="member-popover" hidden></div>
  <script id="initialPayload" type="application/json">{script_json(initial_payload)}</script>
  <script>
    (function () {{
      var filterInput = document.getElementById("rankFilter");
      var clearButton = document.getElementById("clearFilter");
      var teamTypeFilter = document.getElementById("teamTypeFilter");
      var refreshNow = document.getElementById("refreshNow");
      var contestSelect = document.getElementById("contestSelect");
      var autoRefresh = document.getElementById("autoRefresh");
      var mobileHeaderToggle = document.getElementById("mobileHeaderToggle");
      var filterStatus = document.getElementById("filterStatus");
      var problemSummary = document.getElementById("problemSummary");
      var problemSummaryItems = document.getElementById("problemSummaryItems");
      var problemSummaryToggle = document.getElementById("problemSummaryToggle");
      var refreshStatus = document.getElementById("refreshStatus");
      var updateTimeNode = document.getElementById("updateTime");
      var contestClockNode = document.getElementById("contestClock");
      var teamCountNode = document.getElementById("teamCount");
      var titleNode = document.querySelector("h1");
      var tableColumns = document.getElementById("tableColumns");
      var tableHeader = document.getElementById("tableHeader");
      var tableWrap = document.querySelector(".table-wrap");
      var pinnedBody = document.getElementById("pinnedBody");
      var tbody = document.getElementById("tableBody");
      var memberPopover = document.getElementById("memberPopover");
      var sourceRows = [];
      var allRows = [];
      var problemEntries = [];
      var tableColumnCount = 7;
      var tableColumnClasses = [];
      var rowHeight = 35;
      var currentScoreMode = false;
      var renderStart = -1;
      var renderEnd = -1;
      var pendingRenderFrame = null;
      var pendingFilterFrame = null;
      var pendingFilterTimer = null;
      var headerLayoutTimer = null;
      var pinnedRowKeys = new Set();
      var pinnedItems = [];
      var expandedMobileRowKey = "";
      var collapsingMobileRowKey = "";
      var openingMobileRowKey = "";
      var mobileDetailRowHeight = 0;
      var mobileDetailGroup = "main";
      var mobileDetailNode = null;
      var mobileCollapseTimer = null;
      var mobileRowHeights = new Map();
      var mobileOffsets = [0];
      var mobileLayoutWidth = 0;
      var mobilePinnedHeight = 0;
      var mobileContentVersion = 0;
      var mobileTopSpacer = null;
      var mobileBottomSpacer = null;
      var changedTeamIds = new Set();
      var currentPayload = JSON.parse(document.getElementById("initialPayload").textContent);
      var refreshSeconds = Math.max(
        1,
        Number((currentPayload.config || {{}}).refresh_interval_seconds || {DEFAULT_RUNNING_INTERVAL_SECONDS})
      );
      var previousRowSignatures = null;
      var filterKey = "pintia-ranking-filter:" + location.pathname;
      var teamTypeKey = "pintia-ranking-team-type:" + location.pathname;
      var autoKey = "pintia-ranking-auto-refresh:" + location.pathname;
      var contestKey = "pintia-ranking-contest:" + location.pathname;
      var headerCollapsedKey = "pintia-ranking-header-collapsed:" + location.pathname;
      var summaryCollapsedKey = "pintia-ranking-summary-collapsed:" + location.pathname;
      var secondsLeft = refreshSeconds;
      var refreshInFlight = false;
      var refreshAbortController = null;
      var refreshTimeoutId = null;
      var contestIndex = {{
        contests: (currentPayload.config && currentPayload.config.contests) || [],
        default_contest_id: (currentPayload.config && currentPayload.config.current_contest_id) || ""
      }};
      var contestIndexRequest = null;

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
        var relativeTime = formatRelativeTime(currentPayload.fetched_at);
        updateTimeNode.textContent = "更新时间：" + formatDateTime(currentPayload.fetched_at)
          + (relativeTime ? "（" + relativeTime + "）" : "");

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
        if (contestIndex.contests && contestIndex.contests.length) {{
          return contestIndex.contests;
        }}
        return (currentPayload.config && currentPayload.config.contests) || [];
      }}

      function getCurrentContestId() {{
        var options = getContestOptions();
        var payloadContestId = (currentPayload.config && currentPayload.config.current_contest_id) || "";
        if (options.some(function (item) {{ return item.id === payloadContestId; }})) {{
          return payloadContestId;
        }}
        return contestIndex.default_contest_id || payloadContestId || "";
      }}

      function currentContestJson() {{
        var contestId = getCurrentContestId();
        var selected = getContestOptions().find(function (item) {{
          return item.id === contestId;
        }});
        return (selected && selected.json) || "latest.json";
      }}

      function isMobileLayout() {{
        return Boolean(window.matchMedia && window.matchMedia("(max-width: 640px)").matches);
      }}

      function renderProblemSummary() {{
        if (!problemSummary) {{
          return;
        }}
        problemSummaryItems.innerHTML = problemEntries.map(function (entry) {{
          var info = entry[1] || {{}};
          var label = info.label || entry[0];
          var acceptCount = Number(info.acceptCount || 0);
          var submitCount = Number(info.submitCount || 0);
          return '<span class="problem-summary-pill">'
            + '<span class="problem-summary-label"><i style="background:'
            + escapeHtml(info.balloonRgb || "#999") + '"></i>' + escapeHtml(label) + '</span>'
            + '<b>' + escapeHtml(acceptCount) + '</b>'
            + '<span>/</span><span>' + escapeHtml(submitCount) + '</span>'
            + '</span>';
        }}).join("");
        problemSummary.hidden = problemEntries.length === 0;
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

      function mergeContestIndex(indexPayload) {{
        if (!indexPayload || !Array.isArray(indexPayload.contests)) {{
          return;
        }}
        contestIndex = {{
          contests: indexPayload.contests,
          default_contest_id: indexPayload.default_contest_id || contestIndex.default_contest_id || ""
        }};
        renderContestSelect();
      }}

      function refreshContestIndex() {{
        if (!window.fetch || location.protocol === "file:") {{
          return Promise.resolve();
        }}
        if (contestIndexRequest) {{
          return contestIndexRequest;
        }}
        contestIndexRequest = fetch("contests.json?ts=" + Date.now(), {{ cache: "no-store" }})
          .then(function (response) {{
            if (!response.ok) {{
              throw new Error("HTTP " + response.status);
            }}
            return response.json();
          }})
          .then(mergeContestIndex)
          .catch(function () {{}})
          .finally(function () {{
            contestIndexRequest = null;
          }});
        return contestIndexRequest;
      }}

      function rowKey(row) {{
        return String(row.team_fid || row.team_no || row.display_no || "");
      }}

      function prepareRows(payload) {{
        var preparedRows = (payload.rows || []).map(function (row, index) {{
          var key = rowKey(row);
          return {{
            key: key,
            row: row,
            index: index,
            searchText: normalize((row.school_name || "") + " " + (row.team_name || ""))
          }};
        }});
        assignMedals(preparedRows);
        return preparedRows;
      }}

      function currentContestOption() {{
        var contestId = getCurrentContestId();
        return getContestOptions().find(function (item) {{
          return item.id === contestId;
        }});
      }}

      function isTeamTypeFilterSupported(payload) {{
        var source = normalize((payload && payload.source) || "");
        if (!source) {{
          var selected = currentContestOption();
          source = normalize((selected && selected.source) || "");
        }}
        return source === "pintia" || source === "xcpcio" || source === "board";
      }}

      function updateTeamTypeFilterVisibility(payload) {{
        var supported = isTeamTypeFilterSupported(payload);
        teamTypeFilter.hidden = !supported;
        teamTypeFilter.disabled = !supported;
      }}

      function isUnofficialRow(row) {{
        var excluded = row && row.excluded;
        if (typeof excluded === "string") {{
          var value = normalize(excluded);
          return value === "true" || value === "1" || value === "yes";
        }}
        return Boolean(excluded);
      }}

      function isEffectiveMedalRow(row) {{
        var solvedCount = Number(row && row.solved_count);
        return Number.isFinite(solvedCount) && solvedCount > 0;
      }}

      function medalForPosition(position, total) {{
        if (!Number.isFinite(position) || position <= 0 || total <= 0) {{
          return "";
        }}
        var goldCount = Math.ceil(total * 0.1);
        var silverCount = Math.ceil(total * 0.2);
        var bronzeCount = Math.ceil(total * 0.3);
        if (position <= goldCount) {{
          return "gold";
        }}
        if (position <= goldCount + silverCount) {{
          return "silver";
        }}
        if (position <= goldCount + silverCount + bronzeCount) {{
          return "bronze";
        }}
        return "";
      }}

      function assignMedals(rows) {{
        var officialRows = rows.filter(function (item) {{
          return !isUnofficialRow(item.row);
        }});
        var distinguishesTeamTypes = officialRows.length !== rows.length;
        var medalCandidateRows = distinguishesTeamTypes ? officialRows : rows;
        var eligibleRows = medalCandidateRows.filter(function (item) {{
          return isEffectiveMedalRow(item.row);
        }});
        var total = eligibleRows.length;
        eligibleRows.forEach(function (item, index) {{
          var rank = Number(item.row.rank);
          var position = Number.isFinite(rank) && rank > 0 ? rank : index + 1;
          item.medal = medalForPosition(position, total);
        }});
      }}

      function rowMatchesTeamType(row) {{
        if (!isTeamTypeFilterSupported(currentPayload)) {{
          return true;
        }}
        if (teamTypeFilter.value === "official") {{
          return !isUnofficialRow(row);
        }}
        if (teamTypeFilter.value === "unofficial") {{
          return isUnofficialRow(row);
        }}
        return true;
      }}

      function updateTeamCount() {{
        if (allRows.length === sourceRows.length) {{
          teamCountNode.textContent = "队伍数：" + sourceRows.length;
          return;
        }}
        teamCountNode.textContent = "队伍数：" + allRows.length + " / " + sourceRows.length;
      }}

      function applyTeamTypeFilter(resetScroll) {{
        mobileContentVersion += 1;
        allRows = sourceRows.filter(function (item) {{
          return rowMatchesTeamType(item.row);
        }}).map(function (item, index) {{
          return {{
            key: item.key,
            row: item.row,
            index: index,
            sourceIndex: item.index,
            searchText: item.searchText,
            displayNo: index + 1,
            medal: item.medal
          }};
        }});
        if (resetScroll) {{
          tableWrap.scrollTop = 0;
        }}
        renderStart = -1;
        renderEnd = -1;
        updateTeamCount();
        applyColumnWidths();
        applyFilter();
      }}

      function renderTableHeader(scoreMode) {{
        var baseHeaders = (scoreMode
          ? [
              {{ label: "序号", className: "number-col" }},
              {{ label: "排名", className: "rank-col" }},
              {{ label: "学校", className: "school-col" }},
              {{ label: "队名", className: "team-col" }},
              {{ label: "总分", className: "score-col" }},
              {{ label: "满分题", className: "solved-col" }},
              {{ label: "用时", className: "duration-col" }}
            ]
          : [
              {{ label: "序号", className: "number-col" }},
              {{ label: "排名", className: "rank-col" }},
              {{ label: "学校", className: "school-col" }},
              {{ label: "队名", className: "team-col" }},
              {{ label: "过题数", className: "solved-col" }},
              {{ label: "总用时", className: "duration-col" }},
              {{ label: "罚时", className: "penalty-col" }}
            ]
        ).map(function (header) {{
          return {{ html: escapeHtml(header.label), className: header.className }};
        }});
        var problemHeaders = problemEntries.map(function (entry) {{
          var info = entry[1] || {{}};
          var label = info.label || entry[0];
          var fullScore = info.fullScore == null || info.fullScore === "" ? "" : " / " + escapeHtml(info.fullScore);
          return {{ className: "problem-col", html: '<span class="problem-header">'
            + '<span class="problem-header-label"><i style="background:' + escapeHtml(info.balloonRgb || "#999") + '"></i>'
            + escapeHtml(label) + '</span>'
            + '<span class="problem-header-count">' + escapeHtml(info.acceptCount || 0)
            + (scoreMode ? fullScore : ' / ' + escapeHtml(info.submitCount || 0)) + '</span>'
            + '</span>' }};
        }});
        var headers = baseHeaders.concat(problemHeaders);
        tableColumnCount = headers.length;
        tableColumnClasses = headers.map(function (header) {{ return header.className; }});
        tableHeader.innerHTML = headers.map(function (header) {{
          return '<th class="' + header.className + '">' + header.html + "</th>";
        }}).join("");
      }}

      function textWidth(value, minWidth, maxWidth) {{
        var text = String(value == null ? "" : value);
        var wideCount = 0;
        for (var index = 0; index < text.length; index += 1) {{
          wideCount += text.charCodeAt(index) > 255 ? 1 : 0;
        }}
        var asciiCount = text.length - wideCount;
        var width = Math.ceil(asciiCount * 7 + wideCount * 13 + 24);
        width = Math.max(minWidth, width);
        return maxWidth == null ? width : Math.min(maxWidth, width);
      }}

      function maxTextWidth(values, minWidth, maxWidth) {{
        return values.reduce(function (width, value) {{
          return Math.max(width, textWidth(value, minWidth, maxWidth));
        }}, minWidth);
      }}

      function rowProblemText(row, entry) {{
        var label = entry[1] && entry[1].label || entry[0];
        var cell = (row.problem_cells || {{}})[label] || {{}};
        return cell.text || row[label] || "";
      }}

      function computeColumnWidths() {{
        var rows = allRows.map(function (item) {{ return item.row; }});
        var widths = [
          maxTextWidth(["序号"].concat(allRows.map(function (item) {{ return item.displayNo; }})), 54, 90),
          maxTextWidth(["排名"].concat(rows.map(function (row) {{ return row.display_rank || row.rank; }})), 58, 110),
          maxTextWidth(["学校"].concat(rows.map(function (row) {{ return row.school_name; }})), 96, null),
          maxTextWidth(["队名"].concat(rows.map(function (row) {{ return row.team_name; }})), 128, null),
          maxTextWidth(
            [currentScoreMode ? "总分" : "过题数"].concat(rows.map(function (row) {{
              return currentScoreMode ? (row.total_score || "") : row.solved_count;
            }})),
            70,
            140
          ),
          maxTextWidth(
            [currentScoreMode ? "满分题" : "总用时"].concat(rows.map(function (row) {{
              return currentScoreMode ? row.solved_count : row.solving_time;
            }})),
            76,
            150
          ),
          maxTextWidth(
            ["用时"].concat(rows.map(function (row) {{
              return currentScoreMode ? row.solving_time : row.penalty_time;
            }})),
            70,
            150
          )
        ];
        problemEntries.forEach(function (entry) {{
          var info = entry[1] || {{}};
          var label = info.label || entry[0];
          var headerText = label + " " + (info.acceptCount || 0) + " / "
            + (currentScoreMode ? (info.fullScore || "") : (info.submitCount || 0));
          widths.push(maxTextWidth(
            [headerText].concat(rows.map(function (row) {{ return rowProblemText(row, entry); }})),
            58,
            150
          ));
        }});
        return widths;
      }}

      function applyColumnWidths() {{
        tableColumns.innerHTML = computeColumnWidths().map(function (width, index) {{
          return '<col class="' + (tableColumnClasses[index] || "")
            + '" style="width:' + width + 'px">';
        }}).join("");
      }}

      function opaqueMixedColor(red, green, blue, amount) {{
        amount = Math.max(0, Math.min(1, Number(amount || 0)));
        var base = 255;
        return "rgb("
          + Math.round(base + (red - base) * amount) + ", "
          + Math.round(base + (green - base) * amount) + ", "
          + Math.round(base + (blue - base) * amount) + ")";
      }}

      function submitIntensity(submits) {{
        return Math.max(0.18, 0.72 - Math.min(Number(submits || 0), 10) * 0.05);
      }}

      function problemPresentation(row, entry, scoreMode) {{
        var label = entry[1] && entry[1].label || entry[0];
        var cell = (row.problem_cells || {{}})[label] || {{}};
        var submits = Number(cell.submit_count || 0);
        var classes = [];
        var scoreCell = Boolean(cell.score_mode || scoreMode);
        var cellStyle = "--submits:" + submits;
        if (cell.sealed) {{
          classes.push("sealed");
          cellStyle += ";--cell-bg:" + opaqueMixedColor(37, 99, 235, submitIntensity(submits));
        }} else if (scoreCell && cell.submitted) {{
          var score = Number(cell.score || 0);
          var ratio = Number(cell.score_ratio || 0);
          if (score > 0) {{
            var scoreAlpha = 0.24 + Math.max(0, Math.min(1, ratio)) * 0.5;
            classes.push(cell.accepted ? "accepted" : "score-positive");
            cellStyle += ";--cell-bg:" + opaqueMixedColor(22, 163, 74, scoreAlpha);
          }} else {{
            classes.push("rejected");
            cellStyle += ";--cell-bg:" + opaqueMixedColor(220, 38, 38, submitIntensity(submits));
          }}
        }} else if (cell.accepted) {{
          classes.push("accepted");
          cellStyle += ";--cell-bg:" + opaqueMixedColor(22, 163, 74, submitIntensity(submits));
        }} else if (submits > 0) {{
          classes.push("rejected");
          cellStyle += ";--cell-bg:" + opaqueMixedColor(220, 38, 38, submitIntensity(submits));
        }} else {{
          classes.push("empty");
        }}
        if (cell.first_accept) {{
          classes.push("first-accept");
        }}
        return {{
          label: label,
          text: cell.text || row[label] || "",
          submits: submits,
          classes: classes,
          style: cellStyle
        }};
      }}

      function renderProblemCells(row, scoreMode) {{
        if (isMobileLayout()) {{
          return problemEntries.map(function () {{
            return '<td class="problem-col"></td>';
          }}).join("");
        }}
        return problemEntries.map(function (entry) {{
          var presentation = problemPresentation(row, entry, scoreMode);
          return '<td class="' + ["problem-cell", "problem-col"].concat(presentation.classes).join(" ")
            + '" style="' + presentation.style + '">'
            + escapeHtml(presentation.text)
            + '</td>';
        }}).join("");
      }}

      function renderMobileProblemCells(row, scoreMode) {{
        return problemEntries.map(function (entry) {{
          var presentation = problemPresentation(row, entry, scoreMode);
          return '<div class="' + ["mobile-problem"].concat(presentation.classes).join(" ")
          + '" style="' + presentation.style + '">'
          + '<span class="mobile-problem-label">' + escapeHtml(presentation.label) + '</span>'
          + '<span class="mobile-problem-value">' + escapeHtml(presentation.text || "--") + '</span>'
            + '</div>';
        }}).join("");
      }}

      function renderRankCell(item) {{
        var medal = item.medal || "";
        var classes = ["rank", "rank-col"];
        var labels = {{
          gold: "金牌",
          silver: "银牌",
          bronze: "铜牌"
        }};
        var rank = Number(item.row.display_rank || item.row.rank);
        var podium = {{ 1: "gold", 2: "silver", 3: "bronze" }}[rank];
        if (medal) {{
          classes.push("medal-" + medal);
        }}
        if (podium) {{
          classes.push("podium-" + podium);
        }}
        var title = medal ? ' title="' + labels[medal] + '"' : "";
        return '<td class="' + classes.join(" ") + '"' + title + '>'
          + escapeHtml(item.row.display_rank || item.row.rank)
          + '</td>';
      }}

      function renderRow(item, extraClass) {{
        var row = item.row;
        var schoolRank = String(row.school_rank == null ? "" : row.school_rank).trim();
        var schoolName = escapeHtml(row.school_name);
        var schoolNameMarkup = schoolRank
          ? '<span class="school-name-text" data-school-rank="'
            + escapeHtml(schoolRank) + '">' + schoolName + '</span>'
          : schoolName;
        var classes = ["ranking-row"];
        if (extraClass) {{
          classes.push(extraClass);
        }}
        if (pinnedRowKeys.has(item.key) && extraClass !== "pinned-copy") {{
          classes.push("pinned-original");
        }}
        if (changedTeamIds.has(item.key)) {{
          classes.push("changed-row");
        }}
        var classAttribute = classes.length ? ' class="' + classes.join(" ") + '"' : "";
        var expanded = isMobileLayout() && expandedMobileRowKey === item.key
          && mobileDetailGroup === (extraClass === "pinned-copy" ? "pinned" : "main");
        var rowInteraction = isMobileLayout()
          ? ' tabindex="0" aria-expanded="' + (expanded ? "true" : "false") + '"'
          : "";
        var primaryClass = currentScoreMode ? "score-col solved" : "solved-col solved";
        var secondaryClass = currentScoreMode ? "solved-col time" : "duration-col time";
        var tertiaryClass = currentScoreMode ? "duration-col time" : "penalty-col time";
        return '<tr' + classAttribute + ' data-team-fid="' + escapeHtml(item.key)
          + '" data-school="' + escapeHtml(row.school_name) + '" data-team="' + escapeHtml(row.team_name) + '"'
          + rowInteraction + '>'
          + '<td class="number-col number">' + escapeHtml(item.displayNo == null ? row.display_no : item.displayNo) + '</td>'
          + renderRankCell(item)
          + '<td class="school-col school-name">' + schoolNameMarkup + '</td>'
          + '<td class="team-col team-name"><span class="team-name-text" data-members="'
          + escapeHtml(row.members) + '">' + escapeHtml(row.team_name) + '</span></td>'
          + '<td class="' + primaryClass + '">' + escapeHtml(currentScoreMode ? (row.total_score || "") : row.solved_count) + '</td>'
          + '<td class="' + secondaryClass + '">' + escapeHtml(currentScoreMode ? row.solved_count : row.solving_time) + '</td>'
          + '<td class="' + tertiaryClass + '">' + escapeHtml(currentScoreMode ? row.solving_time : row.penalty_time) + '</td>'
          + renderProblemCells(row, currentScoreMode)
          + '</tr>';
      }}

      function renderMobileDetailRow(item) {{
        var row = item.row;
        var schoolRank = String(row.school_rank == null ? "" : row.school_rank).trim();
        var members = String(row.members == null ? "" : row.members).trim();
        var schoolRankMarkup = schoolRank
          ? '<span class="mobile-school-rank">校排 ' + escapeHtml(schoolRank) + '</span>'
          : "";
        var membersMarkup = members
          ? '<div class="mobile-members-line">' + escapeHtml(members) + '</div>'
          : "";
        var collapsing = collapsingMobileRowKey === item.key;
        var opening = !collapsing && openingMobileRowKey === item.key;
        var stateClass = collapsing
          ? " is-collapsing"
          : (opening ? " is-opening" : "");
        return '<tr class="mobile-detail-row' + stateClass + '" data-detail-for="'
          + escapeHtml(item.key) + '">'
          + '<td colspan="' + tableColumnCount + '">'
          + '<div class="mobile-detail-inner">'
          + '<div class="mobile-school-line"><span class="mobile-school-name">'
          + escapeHtml(row.school_name) + '</span>' + schoolRankMarkup + '</div>'
          + membersMarkup
          + '<div class="mobile-problem-grid">'
          + renderMobileProblemCells(row, currentScoreMode)
          + '</div>'
          + '</div></td></tr>';
      }}

      function spacerRow(height) {{
        return '<tr class="virtual-spacer"><td colspan="' + tableColumnCount
          + '" style="--spacer-height:' + Math.max(0, Math.round(height)) + 'px"></td></tr>';
      }}

      function tableBottomSafeHeight() {{
        var value = window.getComputedStyle(document.documentElement)
          .getPropertyValue("--table-bottom-safe");
        var parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : 0;
      }}

      function estimateRowHeight() {{
        var probe = tbody.querySelector("tr:not(.virtual-spacer)") || pinnedBody.querySelector("tr");
        if (!probe) {{
          return;
        }}
        var measured = probe.getBoundingClientRect().height;
        if (measured > 0) {{
          rowHeight = Math.max(28, measured);
        }}
      }}

      function mobileNodeFromHtml(html) {{
        var template = document.createElement("template");
        template.innerHTML = html;
        return template.content.firstElementChild;
      }}

      function mobileExistingRows(parent) {{
        var rows = new Map();
        parent.querySelectorAll("tr.ranking-row").forEach(function (row) {{
          rows.set(row.dataset.teamFid, row);
        }});
        return rows;
      }}

      function mobileRowNode(item, group, existing) {{
        var node = existing.get(item.key);
        if (!node || node.mobileContentVersion !== mobileContentVersion) {{
          node = mobileNodeFromHtml(renderRow(item, group === "pinned" ? "pinned-copy" : ""));
          node.mobileContentVersion = mobileContentVersion;
        }}
        node.classList.toggle("pinned-original", group === "main" && pinnedRowKeys.has(item.key));
        node.classList.toggle("changed-row", changedTeamIds.has(item.key));
        var expanded = String(expandedMobileRowKey === item.key && mobileDetailGroup === group);
        if (node.getAttribute("aria-expanded") !== expanded) {{
          node.setAttribute("aria-expanded", expanded);
        }}
        return node;
      }}

      function mobileDetailFor(item) {{
        if (!mobileDetailNode || mobileDetailNode.mobileContentVersion !== mobileContentVersion) {{
          mobileDetailNode = mobileNodeFromHtml(renderMobileDetailRow(item));
          mobileDetailNode.mobileContentVersion = mobileContentVersion;
        }}
        return mobileDetailNode;
      }}

      function reconcileMobileRows(parent, nodes) {{
        var wanted = new Set(nodes);
        Array.from(parent.children).forEach(function (node) {{
          if (!wanted.has(node)) {{
            if (node === mobileDetailNode) {{
              node.classList.remove("is-opening");
            }}
            node.remove();
          }}
        }});
        var cursor = parent.firstElementChild;
        nodes.forEach(function (node) {{
          if (node === cursor) {{
            cursor = cursor.nextElementSibling;
          }} else {{
            parent.insertBefore(node, cursor);
          }}
        }});
      }}

      function clearMobileDetail() {{
        window.clearTimeout(mobileCollapseTimer);
        mobileCollapseTimer = null;
        if (mobileDetailNode) {{
          mobileDetailNode.remove();
        }}
        mobileDetailNode = null;
        mobileDetailRowHeight = 0;
        expandedMobileRowKey = "";
        collapsingMobileRowKey = "";
        openingMobileRowKey = "";
      }}

      function validateMobileDetail() {{
        var key = expandedMobileRowKey || collapsingMobileRowKey;
        if (key && (!allRows.some(function (item) {{ return item.key === key; }})
          || (mobileDetailGroup === "pinned" && !pinnedRowKeys.has(key)))) {{
          clearMobileDetail();
        }}
      }}

      function captureMobileAnchor(preferred) {{
        if (!isMobileLayout()) {{
          return null;
        }}
        var boundary = tableWrap.getBoundingClientRect().top + tableWrap.clientTop
          + tableHeader.getBoundingClientRect().height + mobilePinnedHeight;
        var node = preferred || Array.from(tbody.children).find(function (row) {{
          return !row.classList.contains("virtual-spacer") && row.getBoundingClientRect().bottom > boundary;
        }});
        if (!node || node.parentElement !== tbody) {{
          return null;
        }}
        return {{
          key: node.dataset.teamFid || node.dataset.detailFor,
          detail: node.classList.contains("mobile-detail-row"),
          top: node.getBoundingClientRect().top
        }};
      }}

      function restoreMobileAnchor(anchor) {{
        if (!anchor) {{
          return;
        }}
        var node = Array.from(tbody.children).find(function (row) {{
          return (anchor.detail ? row.dataset.detailFor : row.dataset.teamFid) === anchor.key;
        }});
        if (node) {{
          var delta = node.getBoundingClientRect().top - anchor.top;
          if (Math.abs(delta) > 0.5) {{
            tableWrap.scrollTop += delta;
          }}
        }}
      }}

      function updateMobileOffsets() {{
        var detailKey = expandedMobileRowKey || collapsingMobileRowKey;
        mobileOffsets = [0];
        allRows.forEach(function (item, index) {{
          var height = mobileRowHeights.get(item.key) || 32;
          if (mobileDetailGroup === "main" && item.key === detailKey) {{
            height += mobileDetailRowHeight;
          }}
          mobileOffsets.push(mobileOffsets[index] + height);
        }});
      }}

      function updateMobileSpacers() {{
        if (!mobileTopSpacer || !mobileTopSpacer.isConnected || renderStart < 0) {{
          return;
        }}
        mobileTopSpacer.firstElementChild.style.setProperty("--spacer-height", mobileOffsets[renderStart] + "px");
        mobileBottomSpacer.firstElementChild.style.setProperty("--spacer-height",
          (mobileOffsets[allRows.length] - mobileOffsets[renderEnd] + tableBottomSafeHeight()) + "px");
      }}

      function updateMobileExpandedRows() {{
        [pinnedBody, tbody].forEach(function (parent) {{
          var group = parent === pinnedBody ? "pinned" : "main";
          parent.querySelectorAll("tr.ranking-row").forEach(function (node) {{
            var expanded = String(node.dataset.teamFid === expandedMobileRowKey && group === mobileDetailGroup);
            if (node.getAttribute("aria-expanded") !== expanded) {{
              node.setAttribute("aria-expanded", expanded);
            }}
          }});
        }});
      }}

      function mobileRowAtOffset(offset) {{
        var low = 0;
        var high = allRows.length;
        while (low < high) {{
          var middle = Math.floor((low + high) / 2);
          if (mobileOffsets[middle + 1] <= offset) {{
            low = middle + 1;
          }} else {{
            high = middle;
          }}
        }}
        return low;
      }}

      function updateMobilePinnedOffsets() {{
        var headerHeight = tableHeader.getBoundingClientRect().height;
        var top = headerHeight;
        var rows = Array.from(pinnedBody.children).map(function (node) {{
          return {{ node: node, height: node.getBoundingClientRect().height }};
        }});
        rows.forEach(function (item) {{
          var node = item.node;
          node.style.setProperty("--sticky-row-top", top + "px");
          top += item.height;
          if (node === mobileDetailNode) {{
            mobileDetailRowHeight = item.height;
          }}
        }});
        mobilePinnedHeight = top - headerHeight;
      }}

      function renderMobilePinnedRows() {{
        var existing = mobileExistingRows(pinnedBody);
        var nodes = [];
        var detailKey = expandedMobileRowKey || collapsingMobileRowKey;
        pinnedItems.forEach(function (item) {{
          nodes.push(mobileRowNode(item, "pinned", existing));
          if (mobileDetailGroup === "pinned" && item.key === detailKey) {{
            nodes.push(mobileDetailFor(item));
          }}
        }});
        reconcileMobileRows(pinnedBody, nodes);
        updateMobilePinnedOffsets();
      }}

      function renderMobileVisibleRows() {{
        var anchor = captureMobileAnchor();
        var width = tableWrap.clientWidth;
        if (width !== mobileLayoutWidth) {{
          mobileLayoutWidth = width;
          mobileRowHeights.clear();
          updateMobilePinnedOffsets();
          if (mobileDetailNode && mobileDetailNode.isConnected) {{
            mobileDetailRowHeight = mobileDetailNode.getBoundingClientRect().height;
          }}
        }}
        updateMobileOffsets();
        var viewportHeight = Math.max(0, tableWrap.clientHeight
          - tableHeader.getBoundingClientRect().height - mobilePinnedHeight);
        var start = Math.max(0, mobileRowAtOffset(tableWrap.scrollTop) - 12);
        var end = Math.min(allRows.length, mobileRowAtOffset(tableWrap.scrollTop + viewportHeight) + 13);
        var existing = mobileExistingRows(tbody);
        if (!mobileTopSpacer) {{
          mobileTopSpacer = mobileNodeFromHtml(spacerRow(0));
          mobileBottomSpacer = mobileNodeFromHtml(spacerRow(0));
        }}
        mobileTopSpacer.firstElementChild.colSpan = tableColumnCount;
        mobileBottomSpacer.firstElementChild.colSpan = tableColumnCount;
        var nodes = [mobileTopSpacer];
        var detailKey = expandedMobileRowKey || collapsingMobileRowKey;
        for (var index = start; index < end; index += 1) {{
          var item = allRows[index];
          nodes.push(mobileRowNode(item, "main", existing));
          if (mobileDetailGroup === "main" && item.key === detailKey) {{
            nodes.push(mobileDetailFor(item));
          }}
        }}
        nodes.push(mobileBottomSpacer);
        reconcileMobileRows(tbody, nodes);
        // Cache individual heights so wrapped names and details retain their space offscreen.
        nodes.forEach(function (node) {{
          if (node.classList.contains("ranking-row")) {{
            mobileRowHeights.set(node.dataset.teamFid, node.getBoundingClientRect().height);
          }} else if (node === mobileDetailNode) {{
            mobileDetailRowHeight = node.getBoundingClientRect().height;
          }}
        }});
        updateMobileOffsets();
        renderStart = start;
        renderEnd = end;
        updateMobileSpacers();
        restoreMobileAnchor(anchor);
      }}

      function renderPinnedRows() {{
        if (isMobileLayout()) {{
          renderMobilePinnedRows();
          return;
        }}
        var headerHeight = tableHeader.getBoundingClientRect().height || rowHeight;
        pinnedBody.innerHTML = pinnedItems.map(function (item, index) {{
          return renderRow(item, "pinned-copy").replace(
            "<tr",
            '<tr style="--sticky-row-top:' + (headerHeight + index * rowHeight) + 'px"'
          );
        }}).join("");
      }}

      function renderVisibleRows(force) {{
        if (isMobileLayout()) {{
          renderMobileVisibleRows();
          return;
        }}
        if (!allRows.length) {{
          tbody.innerHTML = "";
          renderStart = 0;
          renderEnd = 0;
          return;
        }}
        var viewportHeight = tableWrap.clientHeight || window.innerHeight;
        var scrollTop = tableWrap.scrollTop || 0;
        var bufferRows = 18;
        var start = Math.max(0, Math.floor(scrollTop / rowHeight) - bufferRows);
        var visibleCount = Math.ceil(viewportHeight / rowHeight) + bufferRows * 2;
        var end = Math.min(allRows.length, start + visibleCount);
        if (!force && start === renderStart && end === renderEnd) {{
          return;
        }}
        renderStart = start;
        renderEnd = end;
        var html = spacerRow(start * rowHeight);
        for (var index = start; index < end; index += 1) {{
          html += renderRow(allRows[index], "");
        }}
        html += spacerRow((allRows.length - end) * rowHeight + tableBottomSafeHeight());
        tbody.innerHTML = html;
        estimateRowHeight();
      }}

      function scheduleVisibleRows(force) {{
        if (pendingRenderFrame) {{
          window.cancelAnimationFrame(pendingRenderFrame);
        }}
        pendingRenderFrame = window.requestAnimationFrame(function () {{
          pendingRenderFrame = null;
          renderVisibleRows(Boolean(force));
        }});
      }}

      function renderTable(payload, changed) {{
        problemEntries = sortedProblems(payload.problem_info || {{}});
        currentScoreMode = Boolean(payload.score_mode || (payload.competition || {{}}).scoreMode);
        document.body.classList.toggle("score-mode", currentScoreMode);
        changedTeamIds = changed || new Set();
        sourceRows = prepareRows(payload);
        allRows = sourceRows.slice();
        rowHeight = 35;
        renderStart = -1;
        renderEnd = -1;
        pinnedItems = [];
        pinnedRowKeys = new Set();
        updateTeamTypeFilterVisibility(payload);
        renderProblemSummary();
        renderTableHeader(currentScoreMode);
        applyTeamTypeFilter(false);
        window.setTimeout(function () {{
          changedTeamIds = new Set();
          renderPinnedRows();
          renderVisibleRows(true);
        }}, 3400);
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
        if (payload.competition_id !== currentPayload.competition_id || payload.source !== currentPayload.source) {{
          clearMobileDetail();
          mobileRowHeights.clear();
        }}
        currentPayload = payload;
        refreshSeconds = Math.max(
          1,
          Number((currentPayload.config || {{}}).refresh_interval_seconds || {DEFAULT_RUNNING_INTERVAL_SECONDS})
        );
        var competition = payload.competition || {{}};
        titleNode.textContent = competition.name || "榜单";
        document.title = titleNode.textContent + " - 榜单";
        renderContestSelect();
        updateTimeDisplays();
        teamCountNode.textContent = "队伍数：" + ((payload.rows || []).length);
        renderTable(payload, changedTeamIds);
      }}

      function applyFilter() {{
        var keywords = parseKeywords(filterInput.value);
        if (!keywords.length) {{
          pinnedItems = [];
          pinnedRowKeys = new Set();
          validateMobileDetail();
          renderPinnedRows();
          renderVisibleRows(true);
          filterStatus.textContent = "置顶 0 / " + allRows.length + " 支队伍";
          try {{
            localStorage.setItem(filterKey, filterInput.value);
          }} catch (error) {{}}
          return;
        }}
        var pinnedGroups = keywords.map(function () {{ return []; }});
        allRows.forEach(function (item) {{
          var matchIndex = -1;
          for (var index = 0; index < keywords.length; index += 1) {{
            if (item.searchText.indexOf(keywords[index]) !== -1) {{
              matchIndex = index;
              break;
            }}
          }}
          if (matchIndex !== -1) {{
            pinnedGroups[matchIndex].push(item);
          }}
        }});
        pinnedItems = [].concat.apply([], pinnedGroups);
        pinnedRowKeys = new Set(pinnedItems.map(function (item) {{
          return item.key;
        }}));
        validateMobileDetail();
        renderPinnedRows();
        renderVisibleRows(true);
        filterStatus.textContent = "置顶 " + pinnedItems.length + " / " + allRows.length
          + " 支队伍" + (keywords.length ? "，关键词 " + keywords.length + " 个" : "");
        try {{
          localStorage.setItem(filterKey, filterInput.value);
        }} catch (error) {{}}
      }}

      function scheduleFilter() {{
        if (pendingFilterTimer) {{
          window.clearTimeout(pendingFilterTimer);
        }}
        pendingFilterTimer = window.setTimeout(function () {{
          pendingFilterTimer = null;
          if (pendingFilterFrame) {{
            window.cancelAnimationFrame(pendingFilterFrame);
          }}
          pendingFilterFrame = window.requestAnimationFrame(function () {{
            pendingFilterFrame = null;
            applyFilter();
          }});
        }}, 80);
      }}

      function showMemberPopover(node) {{
        var members = node.dataset.members || "无队员信息";
        memberPopover.innerHTML = '<div class="member-popover-title">'
          + escapeHtml(node.textContent || "队伍")
          + '</div><div class="member-popover-members">'
          + escapeHtml(members).replace(/ \\/ /g, "<br>")
          + '</div>';
        memberPopover.hidden = false;
        positionMemberPopover(node);
      }}

      function showSchoolPopover(node) {{
        var schoolRank = node.dataset.schoolRank || "";
        if (!schoolRank) {{
          memberPopover.hidden = true;
          return;
        }}
        memberPopover.innerHTML = '<div class="member-popover-title">'
          + escapeHtml(node.textContent || "学校")
          + '</div><div class="member-popover-members">校排：'
          + escapeHtml(schoolRank)
          + '</div>';
        memberPopover.hidden = false;
        positionMemberPopover(node);
      }}

      function hoverPopoverNode(target) {{
        if (isMobileLayout()) {{
          return null;
        }}
        var node = target && target.closest
          ? target.closest(".team-name-text, .school-name-text")
          : null;
        return node && tableWrap.contains(node) ? node : null;
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

      function refreshTableLayoutSoon() {{
        if (headerLayoutTimer) {{
          window.clearTimeout(headerLayoutTimer);
        }}
        headerLayoutTimer = window.setTimeout(function () {{
          headerLayoutTimer = null;
          memberPopover.hidden = true;
          renderStart = -1;
          renderEnd = -1;
          renderPinnedRows();
          renderVisibleRows(true);
        }}, 180);
      }}

      function setMobileHeaderCollapsed(collapsed, skipLayoutRefresh) {{
        collapsed = Boolean(collapsed);
        document.body.classList.toggle("mobile-header-collapsed", collapsed);
        mobileHeaderToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        mobileHeaderToggle.setAttribute(
          "aria-label",
          collapsed ? "展开顶部展示栏" : "收起顶部展示栏"
        );
        if (!skipLayoutRefresh) {{
          refreshTableLayoutSoon();
        }}
      }}

      function setProblemSummaryCollapsed(collapsed, skipLayoutRefresh) {{
        problemSummary.classList.toggle("is-collapsed", Boolean(collapsed));
        problemSummaryToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        var label = collapsed ? "展开题目统计" : "收起题目统计";
        problemSummaryToggle.setAttribute("aria-label", label);
        problemSummaryToggle.title = label;
        if (!skipLayoutRefresh) {{
          refreshTableLayoutSoon();
        }}
      }}

      try {{
        filterInput.value = localStorage.getItem(filterKey) || "";
        teamTypeFilter.value = localStorage.getItem(teamTypeKey) || "all";
        if (!teamTypeFilter.value) {{
          teamTypeFilter.value = "all";
        }}
        autoRefresh.checked = localStorage.getItem(autoKey) !== "0";
        setMobileHeaderCollapsed(localStorage.getItem(headerCollapsedKey) === "1", true);
        setProblemSummaryCollapsed(localStorage.getItem(summaryCollapsedKey) === "1", true);
      }} catch (error) {{}}

      mobileHeaderToggle.addEventListener("click", function () {{
        var collapsed = !document.body.classList.contains("mobile-header-collapsed");
        setMobileHeaderCollapsed(collapsed, false);
        try {{
          localStorage.setItem(headerCollapsedKey, collapsed ? "1" : "0");
        }} catch (error) {{}}
      }});
      problemSummaryToggle.addEventListener("click", function () {{
        var collapsed = !problemSummary.classList.contains("is-collapsed");
        setProblemSummaryCollapsed(collapsed, false);
        try {{
          localStorage.setItem(summaryCollapsedKey, collapsed ? "1" : "0");
        }} catch (error) {{}}
      }});
      window.addEventListener("resize", refreshTableLayoutSoon);
      function finishMobileCollapse() {{
        if (!collapsingMobileRowKey) {{
          return;
        }}
        var anchor = mobileDetailGroup === "main" ? captureMobileAnchor() : null;
        clearMobileDetail();
        updateMobileExpandedRows();
        updateMobilePinnedOffsets();
        updateMobileOffsets();
        updateMobileSpacers();
        restoreMobileAnchor(anchor);
      }}

      function toggleMobileRow(row) {{
        if (!isMobileLayout()) {{
          return;
        }}
        var key = row.getAttribute("data-team-fid");
        if (!key) {{
          return;
        }}
        var group = row.parentElement === pinnedBody ? "pinned" : "main";
        var anchor = group === "main" ? captureMobileAnchor(row) : null;
        if (expandedMobileRowKey === key && mobileDetailGroup === group) {{
          expandedMobileRowKey = "";
          collapsingMobileRowKey = key;
          row.setAttribute("aria-expanded", "false");
          if (mobileDetailNode) {{
            mobileDetailNode.classList.remove("is-opening");
            mobileDetailNode.classList.add("is-collapsing");
          }}
          mobileCollapseTimer = window.setTimeout(finishMobileCollapse, 180);
          return;
        }}
        if (collapsingMobileRowKey === key && mobileDetailGroup === group) {{
          window.clearTimeout(mobileCollapseTimer);
          mobileCollapseTimer = null;
          collapsingMobileRowKey = "";
          expandedMobileRowKey = key;
          mobileDetailNode.classList.remove("is-collapsing");
          mobileDetailNode.classList.add("is-opening");
        }} else {{
          clearMobileDetail();
          mobileDetailGroup = group;
          expandedMobileRowKey = key;
          openingMobileRowKey = key;
        }}
        memberPopover.hidden = true;
        var item = allRows.find(function (candidate) {{ return candidate.key === key; }});
        if (!item) {{
          clearMobileDetail();
          return;
        }}
        var detail = mobileDetailFor(item);
        row.after(detail);
        updateMobileExpandedRows();
        mobileDetailRowHeight = detail.getBoundingClientRect().height;
        updateMobilePinnedOffsets();
        updateMobileOffsets();
        updateMobileSpacers();
        restoreMobileAnchor(anchor);
        openingMobileRowKey = "";
      }}
      tableWrap.addEventListener("click", function (event) {{
        var target = event.target;
        var row = target && target.closest ? target.closest("tr.ranking-row") : null;
        if (row && tableWrap.contains(row)) {{
          toggleMobileRow(row);
        }}
      }});
      tableWrap.addEventListener("keydown", function (event) {{
        if (event.key !== "Enter" && event.key !== " ") {{
          return;
        }}
        var target = event.target;
        var row = target && target.closest ? target.closest("tr.ranking-row") : null;
        if (row && tableWrap.contains(row)) {{
          event.preventDefault();
          toggleMobileRow(row);
        }}
      }});
      tableWrap.addEventListener("animationend", function (event) {{
        var detailRow = event.target && event.target.closest
          ? event.target.closest("tr.mobile-detail-row")
          : null;
        if (!detailRow) {{
          return;
        }}
        if (event.animationName === "mobile-detail-expand") {{
          detailRow.classList.remove("is-opening");
        }}
        if (event.animationName === "mobile-detail-collapse" && detailRow === mobileDetailNode) {{
          finishMobileCollapse();
        }}
      }});
      tableWrap.addEventListener("scroll", function () {{
        scheduleVisibleRows(false);
      }});
      tableWrap.addEventListener("mouseover", function (event) {{
        var node = hoverPopoverNode(event.target);
        if (node) {{
          if (node.classList.contains("school-name-text")) {{
            showSchoolPopover(node);
          }} else {{
            showMemberPopover(node);
          }}
        }}
      }});
      tableWrap.addEventListener("mousemove", function (event) {{
        var node = hoverPopoverNode(event.target);
        if (node && !memberPopover.hidden) {{
          positionMemberPopover(node);
        }}
      }});
      tableWrap.addEventListener("mouseout", function (event) {{
        var node = hoverPopoverNode(event.target);
        if (node) {{
          memberPopover.hidden = true;
        }}
      }});
      filterInput.addEventListener("input", scheduleFilter);
      teamTypeFilter.addEventListener("change", function () {{
        try {{
          localStorage.setItem(teamTypeKey, teamTypeFilter.value || "all");
        }} catch (error) {{}}
        applyTeamTypeFilter(true);
      }});
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
        refreshData(selected.json, true);
      }});

      function refreshData(jsonFile, skipContestIndex) {{
        if (refreshInFlight) {{
          updateRefreshStatus();
          return Promise.resolve();
        }}
        try {{
          localStorage.setItem(filterKey, filterInput.value);
        }} catch (error) {{}}
        if (!window.fetch || location.protocol === "file:") {{
          refreshStatus.textContent = "请通过 HTTP 服务访问榜单";
          return Promise.resolve();
        }}
        refreshInFlight = true;
        refreshAbortController = window.AbortController ? new AbortController() : null;
        refreshTimeoutId = window.setTimeout(function () {{
          if (refreshAbortController) {{
            refreshAbortController.abort();
          }}
        }}, Math.max(15000, refreshSeconds * 1000));
        updateRefreshStatus();
        var indexPromise = skipContestIndex ? Promise.resolve() : refreshContestIndex();
        return indexPromise
          .then(function () {{
            return fetch((jsonFile || currentContestJson()) + "?ts=" + Date.now(), {{
              cache: "no-store",
              signal: refreshAbortController ? refreshAbortController.signal : undefined
            }});
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
            refreshStatus.textContent = "更新失败，稍后重试";
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

      function loadInitialData() {{
        if (!window.fetch || location.protocol === "file:") {{
          refreshStatus.textContent = "请通过 HTTP 服务访问榜单";
          return;
        }}
        refreshStatus.textContent = "正在加载…";
        refreshContestIndex().then(function () {{
          var jsonFile = "";
          try {{
            var savedContestId = localStorage.getItem(contestKey);
            var savedContest = getContestOptions().find(function (item) {{
              return item.id === savedContestId;
            }});
            if (savedContest) {{
              contestSelect.value = savedContest.id;
              jsonFile = savedContest.json;
            }}
          }} catch (error) {{}}
          previousRowSignatures = null;
          return refreshData(jsonFile || currentContestJson(), true);
        }});
      }}

      loadInitialData();
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




@dataclass(frozen=True)
class OutputPaths:
    latest_csv: Path
    latest_json: Path
    latest_html: Path
    snapshot_csv: Path | None
    snapshot_json: Path | None
    snapshot_html: Path | None


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


def atomic_write_text(path: Path, content: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding=encoding, newline="")
    temp_path.replace(path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_bytes(content)
    temp_path.replace(path)


def ensure_favicon(output_dir: Path) -> None:
    if not FAVICON_SOURCE_PATH.is_file():
        raise FileNotFoundError(f"favicon source not found: {FAVICON_SOURCE_PATH}")
    atomic_write_bytes(output_dir / FAVICON_FILENAME, FAVICON_SOURCE_PATH.read_bytes())


def gzip_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.gz")


def write_outputs(
    payload: dict[str, Any],
    paths: OutputPaths,
    include_html: bool = True,
) -> None:
    ensure_favicon(paths.latest_html.parent)
    problem_info = payload["problem_info"]
    rows = payload["rows"]

    json_content = json_payload_content(payload)
    atomic_write_text(paths.latest_json, json_content, encoding="utf-8")
    atomic_write_bytes(gzip_path(paths.latest_json), gzip_content(json_content))
    if paths.snapshot_json:
        atomic_write_text(paths.snapshot_json, json_content, encoding="utf-8")
        atomic_write_bytes(gzip_path(paths.snapshot_json), gzip_content(json_content))

    if include_html:
        html_content = render_html(payload)
        atomic_write_text(paths.latest_html, html_content, encoding="utf-8")
        if paths.snapshot_html:
            atomic_write_text(paths.snapshot_html, html_content, encoding="utf-8")

    headers = csv_headers(rows, problem_info)

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row_to_csv(row, problem_info))
    csv_content = buffer.getvalue()

    atomic_write_text(paths.latest_csv, csv_content, encoding="utf-8-sig")
    if paths.snapshot_csv:
        atomic_write_text(paths.snapshot_csv, csv_content, encoding="utf-8-sig")


def write_html_output(payload: dict[str, Any], path: Path) -> None:
    ensure_favicon(path.parent)
    atomic_write_text(path, render_html(payload), encoding="utf-8")


def json_payload_content(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def gzip_content(content: str) -> bytes:
    return gzip.compress(content.encode("utf-8"), compresslevel=9)


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    json_content = json_payload_content(payload)
    atomic_write_text(path, json_content, encoding="utf-8")
    atomic_write_bytes(gzip_path(path), gzip_content(json_content))


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
