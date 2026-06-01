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
    tbody tr:nth-child(even) {{ background: #fafcff; }}
    tbody tr:hover {{ background: #eaf4ff; }}
    tbody tr.virtual-spacer,
    tbody tr.virtual-spacer:hover {{
      background: transparent;
    }}
    tbody tr.virtual-spacer > td {{
      height: var(--spacer-height, 0px);
      padding: 0;
      border: 0;
      line-height: 0;
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
      var tableColumns = document.getElementById("tableColumns");
      var tableHeader = document.getElementById("tableHeader");
      var tableWrap = document.querySelector(".table-wrap");
      var pinnedBody = document.getElementById("pinnedBody");
      var tbody = document.getElementById("tableBody");
      var memberPopover = document.getElementById("memberPopover");
      var allRows = [];
      var problemEntries = [];
      var tableColumnCount = 7;
      var rowHeight = 35;
      var currentScoreMode = false;
      var renderStart = -1;
      var renderEnd = -1;
      var pendingRenderFrame = null;
      var pendingFilterFrame = null;
      var pendingFilterTimer = null;
      var pinnedRowKeys = new Set();
      var pinnedItems = [];
      var changedTeamIds = new Set();
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
        return contestIndex.contests || (currentPayload.config && currentPayload.config.contests) || [];
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
        return (payload.rows || []).map(function (row, index) {{
          var key = rowKey(row);
          return {{
            key: key,
            row: row,
            index: index,
            searchText: normalize((row.school_name || "") + " " + (row.team_name || ""))
          }};
        }});
      }}

      function renderTableHeader(scoreMode) {{
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
        tableColumnCount = baseHeaders.length + problemHeaders.length;
        tableHeader.innerHTML = baseHeaders.concat(problemHeaders).map(function (header) {{
          return "<th>" + header.html + "</th>";
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
        return Math.max(minWidth, Math.min(maxWidth, width));
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
          maxTextWidth(["序号"].concat(rows.map(function (row) {{ return row.display_no; }})), 54, 90),
          maxTextWidth(["排名"].concat(rows.map(function (row) {{ return row.display_rank || row.rank; }})), 58, 110),
          maxTextWidth(["学校"].concat(rows.map(function (row) {{ return row.school_name; }})), 96, 260),
          maxTextWidth(["队名"].concat(rows.map(function (row) {{ return row.team_name; }})), 128, 340),
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
        tableColumns.innerHTML = computeColumnWidths().map(function (width) {{
          return '<col style="width:' + width + 'px">';
        }}).join("");
      }}

      function renderProblemCells(row, scoreMode) {{
        return problemEntries.map(function (entry) {{
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
      }}

      function renderRow(item, extraClass) {{
        var row = item.row;
        var classes = [];
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
        return '<tr' + classAttribute + ' data-team-fid="' + escapeHtml(item.key)
          + '" data-school="' + escapeHtml(row.school_name) + '" data-team="' + escapeHtml(row.team_name) + '">'
          + '<td class="number">' + escapeHtml(row.display_no) + '</td>'
          + '<td class="rank">' + escapeHtml(row.display_rank || row.rank) + '</td>'
          + '<td class="school-name">' + escapeHtml(row.school_name) + '</td>'
          + '<td class="team-name"><span class="team-name-text" data-members="'
          + escapeHtml(row.members) + '">' + escapeHtml(row.team_name) + '</span></td>'
          + '<td class="solved">' + escapeHtml(currentScoreMode ? (row.total_score || "") : row.solved_count) + '</td>'
          + '<td class="time">' + escapeHtml(currentScoreMode ? row.solved_count : row.solving_time) + '</td>'
          + '<td class="time">' + escapeHtml(currentScoreMode ? row.solving_time : row.penalty_time) + '</td>'
          + renderProblemCells(row, currentScoreMode)
          + '</tr>';
      }}

      function spacerRow(height) {{
        return '<tr class="virtual-spacer"><td colspan="' + tableColumnCount
          + '" style="--spacer-height:' + Math.max(0, Math.round(height)) + 'px"></td></tr>';
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

      function renderPinnedRows() {{
        var headerHeight = tableHeader.getBoundingClientRect().height || rowHeight;
        pinnedBody.innerHTML = pinnedItems.map(function (item, index) {{
          return renderRow(item, "pinned-copy").replace(
            "<tr",
            '<tr style="--sticky-row-top:' + (headerHeight + index * rowHeight) + 'px"'
          );
        }}).join("");
      }}

      function renderVisibleRows(force) {{
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
        html += spacerRow((allRows.length - end) * rowHeight);
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
        changedTeamIds = changed || new Set();
        allRows = prepareRows(payload);
        rowHeight = 35;
        renderStart = -1;
        renderEnd = -1;
        pinnedItems = [];
        pinnedRowKeys = new Set();
        renderTableHeader(currentScoreMode);
        applyColumnWidths();
        applyFilter();
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
        if (!keywords.length) {{
          pinnedItems = [];
          pinnedRowKeys = new Set();
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

      tableWrap.addEventListener("scroll", function () {{
        scheduleVisibleRows(false);
      }});
      tableWrap.addEventListener("mouseover", function (event) {{
        var node = event.target && event.target.closest
          ? event.target.closest(".team-name-text")
          : null;
        if (node && tableWrap.contains(node)) {{
          showMemberPopover(node);
        }}
      }});
      tableWrap.addEventListener("mousemove", function (event) {{
        var node = event.target && event.target.closest
          ? event.target.closest(".team-name-text")
          : null;
        if (node && tableWrap.contains(node)) {{
          positionMemberPopover(node);
        }}
      }});
      tableWrap.addEventListener("mouseout", function (event) {{
        var node = event.target && event.target.closest
          ? event.target.closest(".team-name-text")
          : null;
        if (node && tableWrap.contains(node)) {{
          memberPopover.hidden = true;
        }}
      }});
      filterInput.addEventListener("input", scheduleFilter);
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
        refreshContestIndex()
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

      renderPayload(currentPayload);
      refreshContestIndex().then(function () {{
        try {{
          var savedContestId = localStorage.getItem(contestKey);
          var savedContest = getContestOptions().find(function (item) {{
            return item.id === savedContestId;
          }});
          if (savedContest && savedContest.id !== getCurrentContestId()) {{
            refreshData(savedContest.json);
          }}
        }} catch (error) {{}}
      }});
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


def gzip_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.gz")


def write_outputs(
    payload: dict[str, Any],
    paths: OutputPaths,
    include_html: bool = True,
) -> None:
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
