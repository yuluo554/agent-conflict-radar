"""M1 工作区与会话发现。

> ⚠️ **M1 未完成状态（2026-10-17；按用户要求只交付 M0 后冻结本棒进度）**：本模块已写出、
> 已在**合成夹具上跑通一次**（1 worktree / 2 会话 / 2 活跃 cell / 0 undetermined / 双跑逐字节一致，
> 见 `plan/HANDOFF-M1.md` §五 进度快照），但**尚未接入 CLI、尚无测试文件、尚无离线冒烟**。
> 因此 `radar scan` **仍在 `stages.STAGE_NOT_READY` 里**（exit 4 显式拦截）——
> 按 K15 纪律，没有测试与冒烟的交付不算交付。**M1 DoD 达成前不得对外宣称 scan 已交付。**

输入：`git worktree list --porcelain` + 双 harness 会话日志（Claude Code / Codex）。
输出：`WorkspaceTable`（worktrees / sessions / active_cells / undetermined / counts）。

三条硬纪律：

1. **不伪造空结果**：源根目录不存在 → `EnvironmentError_`（exit 3）；找不到任何会话源 →
   也是 exit 3。绝不返回空表让调用方以为"没有冲突"。
2. **未识别形态显式可见**：形状不符 → `undetermined` 条目（`unsupported_format` + 缺失键 +
   点名文件）；会话文件没有消息行 → `missing_cwd`；父会话不在本机 → `parent_not_found`。
   这些一律**独立分区列出**，不计入 `sessions`。
3. **确定性**：全程不读时钟（参考时刻由调用方显式传入或取"观测到的最大时间戳"）；
   遍历先排序；`seq` 是**源文件行号**而不是数组下标。

M1 实测勘误见 `versions.py` 的模块文档（首行不一定是消息行、Codex 子会话没有 session_id 等）。
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from . import versions
from .errors import EnvironmentError_
from .gitio import run_readonly
from .paths import normalize_path

#: `undetermined` 的原因码（对外稳定值，不要改字面量）。
CODE_UNSUPPORTED_FORMAT = "unsupported_format"
CODE_MISSING_CWD = "missing_cwd"
CODE_NO_MESSAGE_LINE = "no_message_line"
CODE_PARENT_NOT_FOUND = "parent_not_found"
CODE_LINE_TOO_LONG = "line_too_long"
CODE_UNPARSABLE_LINE = "unparsable_line"
CODE_WORKTREE_LIST_FAILED = "worktree_list_failed"


class Worktree(object):
    __slots__ = ("path", "head", "branch", "is_main")

    def __init__(self, path, head, branch, is_main):
        self.path = path
        self.head = head
        self.branch = branch
        self.is_main = is_main

    def as_dict(self):
        return {"path": self.path, "head": self.head, "branch": self.branch, "is_main": self.is_main}


class Session(object):
    __slots__ = (
        "source",
        "session_key",
        "session_id",
        "cwd",
        "git_branch",
        "start_ts",
        "end_ts",
        "is_subagent",
        "derived_from",
        "file",
        "seq",
        # parent_ref = 源日志里声明的父会话引用（Codex 的 parent_thread_id）。
        # 它是**内部关联输入**，不进对外产物：解析不到父会话时落 parent_not_found。
        "parent_ref",
    )

    def __init__(self, source, session_key, session_id, cwd, git_branch, start_ts, end_ts,
                 is_subagent, derived_from, file, seq, parent_ref=None):
        self.source = source
        self.session_key = session_key
        self.session_id = session_id
        self.cwd = cwd
        self.git_branch = git_branch
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.is_subagent = is_subagent
        self.derived_from = derived_from
        self.file = file
        self.seq = seq
        self.parent_ref = parent_ref

    def as_dict(self):
        return {
            "source": self.source,
            "session_key": self.session_key,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "git_branch": self.git_branch,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "is_subagent": self.is_subagent,
            "derived_from": self.derived_from,
            "file": self.file,
            "seq": self.seq,
        }


class ActiveCell(object):
    __slots__ = ("workspace", "source", "session_key", "session_id", "window_start", "window_end",
                 "is_subagent", "derived_from", "in_worktree")

    def __init__(self, workspace, source, session_key, session_id, window_start, window_end,
                 is_subagent, derived_from, in_worktree):
        self.workspace = workspace
        self.source = source
        self.session_key = session_key
        self.session_id = session_id
        self.window_start = window_start
        self.window_end = window_end
        self.is_subagent = is_subagent
        self.derived_from = derived_from
        self.in_worktree = in_worktree

    def as_dict(self):
        return {
            "workspace": self.workspace,
            "source": self.source,
            "session_key": self.session_key,
            "session_id": self.session_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "is_subagent": self.is_subagent,
            "derived_from": self.derived_from,
            "in_worktree": self.in_worktree,
        }


class Undetermined(object):
    __slots__ = ("file", "source", "code", "detail", "missing_keys")

    def __init__(self, file, source, code, detail, missing_keys=()):
        self.file = file
        self.source = source
        self.code = code
        self.detail = detail
        self.missing_keys = tuple(missing_keys)

    def as_dict(self):
        payload = {"file": self.file, "source": self.source, "code": self.code, "detail": self.detail}
        if self.missing_keys:
            payload["missing_keys"] = list(self.missing_keys)
        return payload


class WorkspaceTable(object):
    def __init__(self, worktrees, sessions, active_cells, undetermined, reference_time, notes=()):
        self.worktrees = tuple(worktrees)
        self.sessions = tuple(sessions)
        self.active_cells = tuple(active_cells)
        self.undetermined = tuple(undetermined)
        self.reference_time = reference_time
        self.notes = tuple(notes)

    def as_dict(self):
        return {
            "reference_time": self.reference_time,
            "worktrees": [item.as_dict() for item in self.worktrees],
            "sessions": [item.as_dict() for item in self.sessions],
            "active_cells": [item.as_dict() for item in self.active_cells],
            "undetermined": [item.as_dict() for item in self.undetermined],
            "notes": list(self.notes),
            "counts": {
                "worktrees": len(self.worktrees),
                "sessions": len(self.sessions),
                "active_cells": len(self.active_cells),
                "undetermined": len(self.undetermined),
                "subagent_sessions": sum(1 for item in self.sessions if item.is_subagent),
                "cells_outside_worktree": sum(1 for item in self.active_cells if not item.in_worktree),
            },
        }


# --------------------------------------------------------------------------------------
# 时间
# --------------------------------------------------------------------------------------


def parse_timestamp(raw: str) -> Optional[datetime]:
    """解析 ISO8601（容忍 `Z` 后缀与小数秒）。解析不了返回 None——**不猜**。"""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_timestamp(moment: datetime) -> str:
    """统一的输出形态（UTC、秒级精度、`Z` 后缀）——窗口边界用。"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# worktree
# --------------------------------------------------------------------------------------


def parse_worktree_porcelain(text: str) -> List[Worktree]:
    """解析 `git worktree list --porcelain`。**按行解析**——路径可能含空格甚至是相对路径。"""
    worktrees: List[Worktree] = []
    current: Dict[str, str] = {}

    def flush():
        if not current:
            return
        path = current.get("worktree")
        if path is None:
            return
        head = current.get("HEAD", "")
        branch = current.get("branch", "")
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/"):]
        elif current.get("detached") is not None:
            branch = "(detached)"
        is_main = not worktrees
        worktrees.append(Worktree(path=path, head=head, branch=branch, is_main=is_main))

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if line == "":
            flush()
            current = {}
            continue
        key, _sep, value = line.partition(" ")
        if key == "bare":
            current["bare"] = "1"
            continue
        current[key] = value
    flush()
    return worktrees


def list_worktrees(repo: str, timeout: Optional[float]) -> Tuple[List[Worktree], List[Undetermined]]:
    """只读枚举 worktree。**只读**：`worktree list --porcelain` 不改任何东西（K4）。"""
    result = run_readonly(["worktree", "list", "--porcelain"], cwd=repo, timeout=timeout)
    if result.returncode != 0:
        return [], [
            Undetermined(
                file="",
                source="git",
                code=CODE_WORKTREE_LIST_FAILED,
                detail=(result.stderr.strip() or result.stdout.strip() or "git worktree list 失败")[:400],
            )
        ]
    return parse_worktree_porcelain(result.stdout), []


# --------------------------------------------------------------------------------------
# 会话文件
# --------------------------------------------------------------------------------------


def iter_session_files(root: Path) -> List[Path]:
    """收集 `*.jsonl`（**排序**后返回，保证遍历顺序确定）。"""
    return sorted(path for path in Path(root).rglob("*.jsonl") if path.is_file())


def iter_jsonl(path: Path, max_line_bytes: int, relative: str) -> Iterator[Tuple[int, dict]]:
    """逐行解析 JSONL。超长行 → `EnvironmentError_`（**不静默截断**：截断会让 JSON 变残缺）。"""
    with open(str(path), "r", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if len(raw.encode("utf-8", errors="replace")) > max_line_bytes:
                raise EnvironmentError_(
                    "会话文件 %s 第 %d 行超过行长上限（%d 字节）：请调大 config 的 scan.max_line_bytes，"
                    "或排除该文件。本工具不做静默截断（截断会产出半条记录）。"
                    % (relative, line_no, max_line_bytes)
                )
            text = raw.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield line_no, record


class _ScanResult(object):
    __slots__ = ("session", "undetermined", "parent_ref")

    def __init__(self, session=None, undetermined=(), parent_ref=None):
        self.session = session
        self.undetermined = tuple(undetermined)
        self.parent_ref = parent_ref


def _scan_claude(path: Path, relative: str, spec, max_line_bytes: int, source: str) -> _ScanResult:
    """Claude 侧：消息行可能不在首行（实测首行多为 last-prompt / queue-operation）。"""
    message_line = None
    message_line_no = 0
    timestamps: List[datetime] = []
    sidechain_flag = None
    for line_no, record in iter_jsonl(path, max_line_bytes, relative):
        moment = parse_timestamp(record.get(spec.timestamp_key))
        if moment is not None:
            timestamps.append(moment)
        flag = record.get(spec.subagent_flag_key)
        if isinstance(flag, bool):
            sidechain_flag = flag if sidechain_flag is None else (sidechain_flag or flag)
        if message_line is None and spec.discriminator_key in record:
            missing = versions.missing_keys(record, spec)
            if missing:
                return _ScanResult(
                    undetermined=[
                        Undetermined(
                            file=relative,
                            source=source,
                            code=CODE_UNSUPPORTED_FORMAT,
                            detail="消息行缺少必需键（版本指纹 %s）" % spec.version,
                            missing_keys=missing,
                        )
                    ]
                )
            message_line = record
            message_line_no = line_no
    if message_line is None:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_NO_MESSAGE_LINE,
                    detail="文件内没有任何带 %r 的行（实测存在只有元信息行的会话文件）" % spec.discriminator_key,
                )
            ]
        )
    cwd = message_line.get(spec.cwd_key)
    if not isinstance(cwd, str) or not cwd:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_MISSING_CWD,
                    detail="消息行没有可用的 %r：无法与该会话匹配到任何工作区" % spec.cwd_key,
                )
            ]
        )
    session_id = None
    for key in spec.session_id_keys:
        value = message_line.get(key)
        if isinstance(value, str) and value:
            session_id = value
            break
    if session_id is None:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_UNSUPPORTED_FORMAT,
                    detail="消息行缺少会话标识键 %s" % (list(spec.session_id_keys),),
                    missing_keys=spec.session_id_keys,
                )
            ]
        )
    branch = message_line.get(spec.branch_key) if spec.branch_key else None
    start_ts, end_ts = _time_bounds(timestamps)
    session = Session(
        source=source,
        session_key="%s:%s" % (source, relative),
        session_id=session_id,
        cwd=cwd,
        git_branch=branch if isinstance(branch, str) else None,
        start_ts=start_ts,
        end_ts=end_ts,
        is_subagent=bool(sidechain_flag),
        derived_from=None,  # 回填：同 sessionId 下 isSidechain=False 的那只文件
        file=relative,
        seq=message_line_no,
    )
    return _ScanResult(session=session)


def _scan_codex(path: Path, relative: str, spec, max_line_bytes: int, source: str) -> _ScanResult:
    """Codex 侧：首行恒为 session_meta（实测 220/220），会话元信息从首行取。"""
    meta = None
    meta_line_no = 0
    timestamps: List[datetime] = []
    for line_no, record in iter_jsonl(path, max_line_bytes, relative):
        moment = parse_timestamp(record.get(spec.timestamp_key))
        if moment is not None:
            timestamps.append(moment)
        if meta is None and record.get("type") == spec.meta_type:
            payload = record.get("payload")
            if isinstance(payload, dict):
                meta = payload
                meta_line_no = line_no
    if meta is None:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_UNSUPPORTED_FORMAT,
                    detail="找不到 %r 元信息行（版本指纹 %s）" % (spec.meta_type, spec.version),
                    missing_keys=(spec.meta_type,),
                )
            ]
        )
    missing = versions.missing_meta_keys(meta, spec)
    if missing:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_UNSUPPORTED_FORMAT,
                    detail="session_meta.payload 缺少必需键（版本指纹 %s）" % spec.version,
                    missing_keys=missing,
                )
            ]
        )
    cwd = meta.get(spec.cwd_key)
    if not isinstance(cwd, str) or not cwd:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_MISSING_CWD,
                    detail="session_meta.payload 没有可用的 %r" % spec.cwd_key,
                )
            ]
        )
    session_id = None
    for key in spec.session_id_keys:
        value = meta.get(key)
        if isinstance(value, str) and value:
            session_id = value
            break
    if session_id is None:
        return _ScanResult(
            undetermined=[
                Undetermined(
                    file=relative,
                    source=source,
                    code=CODE_UNSUPPORTED_FORMAT,
                    detail="session_meta.payload 缺少会话标识键 %s" % (list(spec.session_id_keys),),
                    missing_keys=spec.session_id_keys,
                )
            ]
        )
    parent_raw = None
    for key in spec.parent_keys:
        value = meta.get(key)
        if isinstance(value, str) and value:
            parent_raw = value
            break
    start_ts, end_ts = _time_bounds(timestamps)
    session = Session(
        source=source,
        session_key="%s:%s" % (source, relative),
        session_id=session_id,
        cwd=cwd,
        git_branch=None,
        start_ts=start_ts,
        end_ts=end_ts,
        is_subagent=parent_raw is not None,
        derived_from=None,
        file=relative,
        seq=meta_line_no,
    )
    return _ScanResult(session=session, parent_ref=parent_raw)


def _time_bounds(timestamps: Sequence[datetime]) -> Tuple[Optional[str], Optional[str]]:
    if not timestamps:
        return None, None
    return format_timestamp(min(timestamps)), format_timestamp(max(timestamps))


# --------------------------------------------------------------------------------------
# 组装
# --------------------------------------------------------------------------------------


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def resolve_root(raw: Optional[str], env_name: str, default_relative: str) -> Optional[Path]:
    """解析会话根：显式参数 > 环境变量 > 常见位置（`~/<default_relative>`）。

    任何一条都找不到时返回 `None`——**由调用方显式报错**，不在这里伪造空目录。
    """
    if raw:
        return normalize_path(raw)
    from_env = os.environ.get(env_name)
    if from_env:
        return normalize_path(from_env)
    candidate = Path(os.path.expanduser("~")) / default_relative
    if candidate.is_dir():
        return candidate
    return None


def scan_sessions(
    roots: Sequence[Tuple[str, Path]],
    cfg,
    max_line_bytes: int,
) -> Tuple[List[Session], List[Undetermined]]:
    """扫描各源的会话根，返回 (sessions, undetermined)。`roots` 里不存在的路径直接报错。"""
    sessions: List[Session] = []
    undetermined: List[Undetermined] = []
    for source, root in roots:
        root = Path(root)
        if not root.is_dir():
            raise EnvironmentError_(
                "会话根目录不存在或不是目录：%s（源 %s）。请用 --claude-root / --codex-root 显式指定，"
                "或设置 RADAR_CLAUDE_ROOT / RADAR_CODEX_ROOT。本工具不会伪造空结果。"
                % (root, source)
            )
        spec = versions.spec_for_source(source)
        for path in iter_session_files(root):
            relative = path.relative_to(root).as_posix()
            try:
                if source == versions.SOURCE_CLAUDE:
                    result = _scan_claude(path, relative, spec, max_line_bytes, source)
                else:
                    result = _scan_codex(path, relative, spec, max_line_bytes, source)
            except EnvironmentError_ as exc:
                undetermined.append(
                    Undetermined(file=relative, source=source, code=CODE_LINE_TOO_LONG, detail=str(exc)[:400])
                )
                continue
            if result.session is not None:
                if result.parent_ref:
                    result.session.parent_ref = result.parent_ref
                sessions.append(result.session)
            undetermined.extend(result.undetermined)
    return sessions, undetermined


def link_derivations(sessions: List[Session], undetermined: List[Undetermined]) -> None:
    """回填 `derived_from`（**原地**修改 sessions）。

    Claude：`isSidechain=True` 的文件归属于**同 sessionId 下 isSidechain=False** 的那只文件。
    Codex：`parent_thread_id` 指向**另一个文件的 session_id**。
    父会话不在本机（例如已被清理）→ 落 `parent_not_found`，**不猜**。
    """
    by_source_id: Dict[Tuple[str, str], str] = {}
    for session in sessions:
        if not session.is_subagent:
            by_source_id.setdefault((session.source, session.session_id), session.session_key)
    for session in sessions:
        if session.source == versions.SOURCE_CLAUDE:
            if session.is_subagent:
                parent = by_source_id.get((session.source, session.session_id))
                if parent is None or parent == session.session_key:
                    undetermined.append(
                        Undetermined(
                            file=session.file,
                            source=session.source,
                            code=CODE_PARENT_NOT_FOUND,
                            detail="isSidechain=True 但本机没有同 sessionId 的主会话文件",
                        )
                    )
                else:
                    session.derived_from = parent
            continue
        parent_raw = session.parent_ref
        if not parent_raw:
            continue
        parent = by_source_id.get((session.source, parent_raw))
        if parent is None:
            undetermined.append(
                Undetermined(
                    file=session.file,
                    source=session.source,
                    code=CODE_PARENT_NOT_FOUND,
                    detail="parent_thread_id 指向的父会话不在本次扫描范围内",
                )
            )
        else:
            session.derived_from = parent


def build_workspace_table(
    repo: str,
    claude_root: Optional[str],
    codex_root: Optional[str],
    cfg,
    now: Optional[str] = None,
) -> WorkspaceTable:
    """M1 主入口：worktree 表 + 会话归集 + 活跃 cell。

    `now`：参考时刻（ISO8601）。缺省取**观测到的最大时间戳**（输入的函数，保持双跑一致）；
    真实使用时由 CLI 传系统时钟，并把它写进产物（`reference_time`），使"为何这个会话算活跃"
    可解释、可复现。
    """
    timeout = cfg.get("git", "timeout_seconds")
    active_minutes = cfg.get("window", "active_minutes")
    scan_days = cfg.get("window", "scan_days")
    max_line_bytes = cfg.get("scan", "max_line_bytes")

    notes: List[str] = []
    worktrees, worktree_undetermined = list_worktrees(repo, timeout)
    undetermined: List[Undetermined] = list(worktree_undetermined)
    if not worktrees:
        notes.append("git 未报告任何 worktree：会话仍会被扫描，但无法与工作区匹配")

    roots: List[Tuple[str, Path]] = []
    for source, raw, env_name, default_relative in (
        (versions.SOURCE_CLAUDE, claude_root, "RADAR_CLAUDE_ROOT", os.path.join(".claude", "projects")),
        (versions.SOURCE_CODEX, codex_root, "RADAR_CODEX_ROOT", os.path.join(".codex", "sessions")),
    ):
        resolved = resolve_root(raw, env_name, default_relative)
        if resolved is None:
            notes.append("未找到 %s 会话源（既未显式指定，常见位置也没有）" % source)
            continue
        roots.append((source, resolved))
    if not roots:
        raise EnvironmentError_(
            "找不到任何会话源：请用 --claude-root / --codex-root 显式指定，"
            "或设置 RADAR_CLAUDE_ROOT / RADAR_CODEX_ROOT。本工具不会伪造空结果。"
        )

    sessions, session_undetermined = scan_sessions(roots, cfg, max_line_bytes)
    undetermined.extend(session_undetermined)
    link_derivations(sessions, undetermined)

    reference = parse_timestamp(now) if now else None
    if reference is None:
        observed = [parse_timestamp(item.end_ts) for item in sessions if item.end_ts]
        observed = [item for item in observed if item is not None]
        if now is not None and not observed:
            raise EnvironmentError_("--now 解析失败且没有可用的会话时间戳：%s" % now)
        if observed:
            reference = max(observed)
            if now is None:
                notes.append("未传 --now：参考时刻取观测到的最大会话时间戳（输入的函数，保证双跑一致）")
        else:
            reference = datetime.now(timezone.utc)
            notes.append("未传 --now 且无任何会话时间戳：参考时刻取系统时钟")

    sessions.sort(key=lambda item: (item.source, item.session_id, item.file, item.seq))
    worktrees.sort(key=lambda item: (not item.is_main, item.path))

    window_start_cut = reference - timedelta(days=scan_days)
    active_window = timedelta(minutes=active_minutes)
    cells: List[ActiveCell] = []
    for session in sessions:
        end = parse_timestamp(session.end_ts)
        if end is None:
            undetermined.append(
                Undetermined(
                    file=session.file,
                    source=session.source,
                    code=CODE_UNPARSABLE_LINE,
                    detail="会话没有任何可解析的时间戳：无法判定活跃窗口",
                )
            )
            continue
        if end < window_start_cut:
            continue  # 落在扫描窗口之外：不进活跃表（不是"无冲突"，是本次不参与）
        cell_start = end - active_window
        if cell_start < window_start_cut:
            cell_start = window_start_cut
        if end < reference - active_window:
            continue  # 活跃窗已过：不进活跃表
        workspace, in_worktree = match_worktree(session.cwd, worktrees)
        cells.append(
            ActiveCell(
                workspace=workspace,
                source=session.source,
                session_key=session.session_key,
                session_id=session.session_id,
                window_start=format_timestamp(cell_start),
                window_end=format_timestamp(end),
                is_subagent=session.is_subagent,
                derived_from=session.derived_from,
                in_worktree=in_worktree,
            )
        )

    cells.sort(key=lambda item: (item.workspace, item.source, item.session_id, item.session_key))
    undetermined.sort(key=lambda item: (item.source, item.file, item.code))
    return WorkspaceTable(
        worktrees=worktrees,
        sessions=sessions,
        active_cells=cells,
        undetermined=undetermined,
        reference_time=format_timestamp(reference),
        notes=notes,
    )


def match_worktree(cwd: str, worktrees: Iterable[Worktree]) -> Tuple[str, bool]:
    """把会话 `cwd` 匹配到 worktree：先精确、再**最长前缀**（cwd 可能是 worktree 的子目录）。

    匹配不上时返回 `(cwd, False)`——保留原始 cwd 并显式标注 `in_worktree=False`，
    既不做"丢弃"，也不假装它属于某个工作区。
    """
    normalized = _norm(cwd)
    best = None
    for worktree in worktrees:
        root = _norm(worktree.path)
        if normalized == root:
            return worktree.path, True
        prefix = root.rstrip("\\/") + os.sep
        if normalized.startswith(prefix):
            if best is None or len(root) > len(_norm(best.path)):
                best = worktree
    if best is not None:
        return best.path, True
    return cwd, False
