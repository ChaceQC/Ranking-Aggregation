from __future__ import annotations

from datetime import datetime
from typing import Any

from .settings import NOWCODER_SCORE_RANK_TYPES

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


