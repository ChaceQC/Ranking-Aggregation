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
