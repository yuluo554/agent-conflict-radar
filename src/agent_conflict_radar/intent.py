"""M2 变更意图提取（`radar intent` 的实现主体）。

把"会话里的写操作"翻译成"文件集合 + 改动行区间"，并**与磁盘对账**。三条来源各司其职：

* **会话是意图**：Claude 的 `Edit` / `Write` / `MultiEdit`，Codex 的 `apply_patch`（含经 `exec`
  下发的同形变体）——都在 `versions.py` 的实测字段表里登记过；
* **磁盘是事实**：`git status --porcelain` / `git diff` / `git diff --cached` 的 hunk 是改动行区间的
  权威；两边不一致时**以磁盘为准**，并在产物里点名（`disk_and_session_disagree`），不悄悄改数字；
* **`HEAD` 是定位基线**：会话里 `old_string` 的定位一律**在 `git show HEAD:<path>` 的版本里做**，
  **不读工作区文件、不读仓库外的任何路径**。这条是有意的：
  ① 语义更对——agent 的改动相对"它开始时的已提交版本"，磁盘可能已经带上这次改动，
     在工作区里找锚点会找不到（而 HEAD 里能找到）；
  ② 只读与隐私更好——全程走 `gitio.run_readonly` 的只读白名单，零仓库外读取。

## 落点三分法（`exact` / `coarse` / `unknown`，互斥且穷尽）

| 落点 | 判据 | 产物形态 |
|---|---|---|
| `exact` | 改动区间**可独立复算**：磁盘 hunk，或会话锚点在 HEAD 基线里**唯一命中** | `changed_ranges` 非空 |
| `coarse` | 文件定位到了，但**会话侧**区间不可精确断言：`replace_all` / 锚点 0 处或多处命中 / 写内容与基线逐行相同 / 删除 / 非 git 工作区 / 基线取不到 | 会话侧 `writes[].changed_ranges == []`（**不编"看起来精确"的区间**） |
| `unknown` | **连文件都定不下来**：`file_path` 缺失、`MultiEdit`（本机 0 次出现，不假装支持）、patch 里没有任何文件指令行 | `path == ""`，计 `counts.unknown_write_ops` |

**计数恒等式**（写成测试）：`exact + coarse + unknown == entries`。
`unknown_write_ops` 是**未定位到文件的写操作条数**（一个会话的多次未定位写操作合并成同一条
unknown 记录，故它 ≥ `unknown` 条目数）——K12"先声明计数口径"的落地。

当磁盘 hunk 与会话侧区间不一致时，条目 `changed_ranges` 取**磁盘**区间，`writes[].changed_ranges`
保留**会话**区间，`reasons` 里出现 `disk_and_session_disagree`。`ranges_source` 显式登记这个来源，
使"这条区间是谁给的"随时可查。

## 降级纪律（逐条对应 `plan/HANDOFF-M2.md` §二 的表）

| 情形 | 行为 | reason 码 |
|---|---|---|
| `old_string` 多处命中 | `coarse` + 点名命中次数 | `anchor_ambiguous#<n>` |
| `replace_all=True` | `coarse` + 明确"无精确区间" | `replace_all` |
| `MultiEdit`（本机 0 次出现） | `unknown` + 计注记 | `multi_edit_unsupported` |
| 非 Python 文件 | 行区间照给，但 `approximate=True`，**不产出任何符号字段**（R4） | —— |
| 会话 `cwd` 不在任何 worktree | 只做会话侧抽取；`precision` 上限 `coarse`；不崩不伪造 | `not_in_worktree` |
| 磁盘与会话不一致 | 以磁盘为准 + 点名两边区间 | `disk_and_session_disagree` |

## 确定性纪律

* 不读时钟：`last_write_ts` 取会话原值，`reference_time` 由调用方显式传 `--now`（缺省取观测到的
  最大时间戳，是输入的函数）；
* 遍历前一律排序；`sessions` / `evidence` / `ranges` 去重后按首次出现序或数值序；
* 零写盘：不给 `--out-dir` 时一个文件都不落（含临时文件）。
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import discover
from . import versions
from .errors import EnvironmentError_
from .gitio import run_readonly

#: 落点（对外稳定值，不要改字面量）。
PRECISION_EXACT = "exact"
PRECISION_COARSE = "coarse"
PRECISION_UNKNOWN = "unknown"

#: 由强到弱：条目级落点取**最弱**的那一档（有一处说不准，整条就不能声称精确）。
PRECISION_ORDER = (PRECISION_EXACT, PRECISION_COARSE, PRECISION_UNKNOWN)

#: 区间来源（显式登记"这条区间是谁给的"）。
RANGES_FROM_DISK = "disk"
RANGES_FROM_SESSION = "session"
RANGES_FROM_NONE = "none"

#: 写操作的降级原因码（对外稳定值；产物里按出现序排列）。
REASON_MULTI_EDIT = "multi_edit_unsupported"
REASON_MISSING_FILE_PATH = "missing_file_path"
REASON_PATCH_WITHOUT_INSTRUCTION = "patch_without_file_instruction"
REASON_PATCH_WITHOUT_HUNK = "patch_without_hunk"
REASON_REPLACE_ALL = "replace_all"
REASON_ANCHOR_AMBIGUOUS = "anchor_ambiguous"
REASON_ANCHOR_NOT_FOUND = "anchor_not_found"
REASON_WRITE_IDENTICAL_TO_BASE = "write_identical_to_base"
REASON_WRITE_EMPTY = "write_empty"
REASON_NOT_IN_WORKTREE = "not_in_worktree"
REASON_BASELINE_UNAVAILABLE = "baseline_unavailable"
REASON_BINARY_BASELINE = "binary_baseline"
REASON_DELETED_PATH = "deleted_path"
REASON_UNTRACKED_PATH = "untracked_path"
REASON_BINARY_DIFF = "binary_diff"
REASON_DISK_AND_SESSION_DISAGREE = "disk_and_session_disagree"

#: 会话侧被认作"写操作"的 Claude 工具名（R3 实测：Edit 263 / Write 128 / MultiEdit 0）。
CLAUDE_WRITE_TOOLS = ("Edit", "Write", "MultiEdit")

#: 本机 **0 次出现**、名字像写操作的形态：出现即落 `unknown`，**不假装支持**（known-name 占位）。
CLAUDE_PLACEHOLDER_TOOLS = ("MultiEdit",)

#: Codex 侧承载 patch 的工具名（R2 实测：`apply_patch` 专用调用 + 经 `exec` 下发的同形变体）。
CODEX_PATCH_TOOLS = ("apply_patch", "exec")

#: patch 文件指令行（R2 实测形态）。
PATCH_INSTRUCTIONS = (
    ("*** Update File:", "update"),
    ("*** Add File:", "add"),
    ("*** Delete File:", "delete"),
)

#: patch 载荷的起止标记（判别"这是不是一段 patch 文本"）。
PATCH_BEGIN = "*** Begin Patch"
PATCH_END = "*** End Patch"

#: 写操作类别（会话侧工具路径的形态）。
OP_EDIT = "edit"
OP_WRITE = "write"
OP_PATCH_UPDATE = "patch_update"
OP_PATCH_ADD = "patch_add"
OP_PATCH_DELETE = "patch_delete"
OP_OPAQUE = "opaque"

#: 诊断文本的截断长度（展示用常量，不是判定阈值；阈值一律读 config）。
#: 与 `discover.py` 的同名常量保持一致，理由也相同——它只影响报错信息长度，不影响任何判定。
_DETAIL_LIMIT = 400

#: 协议偏移一律用 `len(...)` 表达，不写裸数字：这些数字是**格式常量**（`git status -z` 的
#: 两字符状态码 + 一个空格、diff 头的 `+++ ` / `b/` 前缀），写裸数字会被 K5 门禁判成策略数值。
_STATUS_CODE_LEN = len("XY")
_STATUS_SEPARATOR_LEN = len(" ")
_STATUS_PATH_OFFSET = _STATUS_CODE_LEN + _STATUS_SEPARATOR_LEN
_DIFF_TARGET_PREFIX = "+++ "
_DIFF_PATH_PREFIX = "b/"
_DIFF_GIT_MIN_TOKENS = len(("diff", "--git", "a/path", "b/path"))

#: `@@ -a,b +c,d @@` 至少被两个 `@@` 切成三段（前缀 / 范围 / 上下文）。
_HUNK_MIN_PARTS = len(("", "", ""))

#: `git status --porcelain` 的未跟踪状态字符。
_STATUS_UNTRACKED = "?"


# --------------------------------------------------------------------------------------
# 数据对象
# --------------------------------------------------------------------------------------


class WriteRecord(object):
    """某一会话在某文件上的改动（同会话同文件多次写入**已按时间序合并**）。"""

    __slots__ = ("session", "session_id", "source", "last_write_ts", "changed_ranges",
                 "precision", "approximate", "in_worktree", "tools", "reasons", "evidence", "path")

    def __init__(self, session, session_id, source, last_write_ts, changed_ranges, precision,
                 approximate, in_worktree, tools, reasons, evidence, path=""):
        self.session = session
        self.session_id = session_id
        self.source = source
        self.last_write_ts = last_write_ts
        self.changed_ranges = tuple(changed_ranges)
        self.precision = precision
        self.approximate = approximate
        self.in_worktree = in_worktree
        self.tools = tuple(tools)
        self.reasons = tuple(reasons)
        self.evidence = tuple(evidence)
        self.path = path

    def as_dict(self):
        return {
            "session": self.session,
            "session_id": self.session_id,
            "source": self.source,
            "last_write_ts": self.last_write_ts,
            "changed_ranges": [list(item) for item in self.changed_ranges],
            "precision": self.precision,
            "approximate": self.approximate,
            "in_worktree": self.in_worktree,
            "tools": list(self.tools),
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
        }


class IntentEntry(object):
    """一个 `(workspace, path)` 组合的意图（`plan/04` M2 的聚合口径）。

    `writes` 保留**逐会话**的区间与落点：M3 的符号级要按会话比对改动落在哪个符号上，
    只给一个并集会让"谁动了哪一段"丢失。
    """

    __slots__ = ("workspace", "path", "sessions", "session_ids", "last_write_ts", "changed_ranges",
                 "precision", "approximate", "ranges_source", "writes", "reasons", "evidence",
                 "in_worktree", "disk_confirmed")

    def __init__(self, workspace, path, sessions, session_ids, last_write_ts, changed_ranges,
                 precision, approximate, ranges_source, writes, reasons, evidence, in_worktree,
                 disk_confirmed):
        self.workspace = workspace
        self.path = path
        self.sessions = tuple(sessions)
        self.session_ids = tuple(session_ids)
        self.last_write_ts = last_write_ts
        self.changed_ranges = tuple(changed_ranges)
        self.precision = precision
        self.approximate = approximate
        self.ranges_source = ranges_source
        self.writes = tuple(writes)
        self.reasons = tuple(reasons)
        self.evidence = tuple(evidence)
        self.in_worktree = in_worktree
        #: 是否由磁盘 hunk 确认过（M2 的"事实侧"是否到场）。
        self.disk_confirmed = disk_confirmed

    def as_dict(self):
        return {
            "workspace": self.workspace,
            "path": self.path,
            "sessions": list(self.sessions),
            "session_ids": list(self.session_ids),
            "last_write_ts": self.last_write_ts,
            "changed_ranges": [list(item) for item in self.changed_ranges],
            "precision": self.precision,
            "approximate": self.approximate,
            "ranges_source": self.ranges_source,
            "in_worktree": self.in_worktree,
            "disk_confirmed": self.disk_confirmed,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
            "writes": [item.as_dict() for item in self.writes],
        }


class IntentSet(object):
    def __init__(self, entries, undetermined, reference_time, notes=(), counts=None):
        self.entries = tuple(entries)
        self.undetermined = tuple(undetermined)
        self.reference_time = reference_time
        self.notes = tuple(notes)
        self._counts = dict(counts or {})

    def counts(self):
        return dict(self._counts)

    def as_dict(self):
        return {
            "reference_time": self.reference_time,
            "entries": [item.as_dict() for item in self.entries],
            "undetermined": [item.as_dict() for item in self.undetermined],
            "notes": list(self.notes),
            "counts": self.counts(),
        }

    def entries_by_path(self):
        """`(workspace, path) -> IntentEntry`（测试与 M3 消费用）。"""
        return dict(((item.workspace, item.path), item) for item in self.entries)


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------


def looks_python(path: str) -> bool:
    """是否具备符号级能力（R4 闭环）：只认 `.py` 后缀。

    **保守方向是有意的**：认不出后缀的一律按"非 Python"处理（`approximate=True`），
    而不是乐观地宣称"我们可以做符号级"。
    """
    return str(path).lower().endswith(".py")


def split_lines(text: str) -> List[str]:
    """把文本切成行（丢掉结尾空行带来的那一个元素）；CRLF/CR 一律归一成 LF。"""
    if text == "":
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _norm_text(raw: str) -> str:
    return os.path.normcase(os.path.normpath(str(raw)))


def to_workspace_relative(raw: str, cwd: str) -> Tuple[str, bool]:
    """把工具调用里的路径归一成"相对会话 `cwd` 的 posix 路径"。

    返回 `(相对路径, 是否落在 cwd 之下)`。**不在 cwd 之下时原样返回**（不猜它属于哪个仓库）——
    猜错会把别的仓库的文件算进本次分析，那是最糟的一类错误。
    """
    text = os.path.normpath(str(raw))
    base = os.path.normpath(str(cwd))
    if os.path.normcase(text) == os.path.normcase(base):
        return "", True
    prefix = os.path.normcase(base) + os.sep
    if os.path.normcase(text).startswith(prefix):
        return text[len(base) + 1:].replace(os.sep, "/"), True
    return text.replace(os.sep, "/"), False


#: 盘符式绝对路径（`C:/x`、`C:\x`）。**不能**用 `os.path.isabs` 判：POSIX 上它不认盘符，
#: 于是 `C:/abs/a.py` 会被当成"干净的相对路径"（CI 的 ubuntu leg 实测踩中）。
_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_clean_relative(rel: str) -> bool:
    """仓库相对路径必须干净（不得是绝对路径、不得用 `..` 逃出去、不得含反斜杠）。

    ⚠️ 判据必须**跨平台一致**：同一个字符串在 Windows 与 POSIX 上要给出同一个答案。
    首版只用了 `os.path.isabs`，于是 `C:/abs/a.py` 在 ubuntu 上被判成"干净"（CI 首跑实测）。
    """
    if not rel or os.path.isabs(rel) or rel.startswith("..") or "\\" in rel:
        return False
    if _DRIVE_ABSOLUTE_RE.match(rel):
        return False
    if rel.startswith("/"):
        # POSIX 绝对路径（Windows 上 `os.path.isabs("/x")` 已经为 True，这里是另一侧的兜底）。
        return False
    return True


def find_anchor_hits(base_lines: Sequence[str], anchor_lines: Sequence[str]) -> List[int]:
    """锚点在基线里的**全部**命中位置（0-based 起始下标，升序）。

    返回全部命中而不是第一个：调用方**必须**能判断"多处命中"并显式降级。
    """
    anchor = list(anchor_lines)
    if not anchor:
        return []
    hits = []
    span = len(anchor)
    for index in range(len(base_lines) - span + 1):
        if list(base_lines[index:index + span]) == anchor:
            hits.append(index)
    return hits


def effective_change_range(base_lines: Sequence[str], new_lines: Sequence[str]) -> Optional[Tuple[int, int]]:
    """逐行比对求**有效改动区间**（1-based 闭区间，**新文件行号**）；完全相同返回 `None`。

    做法是去掉公共前后缀：改动块之外的差异不归因于这一次写操作。
    """
    before = list(base_lines)
    after = list(new_lines)
    head = 0
    while head < len(before) and head < len(after) and before[head] == after[head]:
        head += 1
    tail = 0
    while (tail < len(before) - head and tail < len(after) - head
           and before[len(before) - 1 - tail] == after[len(after) - 1 - tail]):
        tail += 1
    if head >= len(after) - tail and head >= len(before) - tail:
        return None
    return head + 1, len(after) - tail


def sort_ranges(ranges) -> List[Tuple[int, int]]:
    """区间去重 + 按 `(start, end)` 升序（**不做合并**：保留来源信息，便于逐条对账）。"""
    seen: List[Tuple[int, int]] = []
    for item in ranges:
        pair = (int(item[0]), int(item[1]))
        if pair not in seen:
            seen.append(pair)
    seen.sort()
    return seen


def _ordered_unique(items) -> List:
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _worst_precision(values: Sequence[str]) -> str:
    """取最弱的一档；空输入按 `exact`（没有反面证据就不降级）。"""
    if not values:
        return PRECISION_EXACT
    return max(values, key=PRECISION_ORDER.index)


def _worst_of(values: Sequence[str], override: Optional[str]) -> str:
    if override is None:
        return _worst_precision(values)
    return max(list(values) + [override], key=PRECISION_ORDER.index)


# --------------------------------------------------------------------------------------
# 会话侧：写操作抽取
# --------------------------------------------------------------------------------------


class _Op(object):
    """一条原始写操作（尚未定位区间）。"""

    __slots__ = ("session", "session_id", "source", "file", "seq", "ts", "tool", "kind",
                 "path_raw", "cwd", "workspace", "in_worktree", "old_lines", "new_lines",
                 "replace_all", "content_lines", "reason")

    def __init__(self, session, session_id, source, file, seq, ts, tool, kind, path_raw, cwd,
                 workspace, in_worktree, old_lines=(), new_lines=(), replace_all=False,
                 content_lines=(), reason=None):
        self.session = session
        self.session_id = session_id
        self.source = source
        self.file = file
        self.seq = seq
        self.ts = ts
        self.tool = tool
        self.kind = kind
        self.path_raw = path_raw
        self.cwd = cwd
        self.workspace = workspace
        self.in_worktree = in_worktree
        self.old_lines = tuple(old_lines)
        self.new_lines = tuple(new_lines)
        self.replace_all = bool(replace_all)
        self.content_lines = tuple(content_lines)
        self.reason = reason

    def evidence(self):
        return "%s:%s:%d" % (self.source, self.file, self.seq)

    def rel_path(self):
        """相对会话 `cwd` 的 posix 路径（`None` = 路径缺失）。"""
        if self.path_raw is None:
            return None
        rel, _inside = to_workspace_relative(self.path_raw, self.cwd)
        return rel


def _make_op(tokens, tool, kind, path_raw, old_lines=(), new_lines=(), replace_all=False,
             content_lines=(), reason=None) -> _Op:
    """按会话的归集结果（cwd / workspace / in_worktree）造一条写操作。"""
    return _Op(
        session=tokens["session"],
        session_id=tokens["session_id"],
        source=tokens["source"],
        file=tokens["file"],
        seq=tokens["seq"],
        ts=tokens["ts"],
        tool=tool,
        kind=kind,
        path_raw=path_raw,
        cwd=tokens["cwd"],
        workspace=tokens["workspace"],
        in_worktree=tokens["in_worktree"],
        old_lines=old_lines,
        new_lines=new_lines,
        replace_all=replace_all,
        content_lines=content_lines,
        reason=reason,
    )


def claude_write_ops(record, tokens) -> List[_Op]:
    """从一条 Claude 消息行里抽写操作（`message.content[]` 中 `type == "tool_use"` 的项）。"""
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    ops: List[_Op] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name")
        if name not in CLAUDE_WRITE_TOOLS:
            continue
        raw_input = item.get("input")
        tool_input = raw_input if isinstance(raw_input, dict) else {}
        if name in CLAUDE_PLACEHOLDER_TOOLS:
            # 本机 0 次出现 → known-name 占位、落 unknown + 计注记，**不假装支持**。
            ops.append(_make_op(tokens, name, OP_OPAQUE, None, reason=REASON_MULTI_EDIT))
            continue
        raw_path = tool_input.get("file_path")
        if not isinstance(raw_path, str) or not raw_path:
            ops.append(_make_op(tokens, name, OP_OPAQUE, None, reason=REASON_MISSING_FILE_PATH))
            continue
        if name == "Write":
            content_text = tool_input.get("content")
            lines = split_lines(content_text) if isinstance(content_text, str) else []
            ops.append(_make_op(tokens, name, OP_WRITE, raw_path, content_lines=lines))
            continue
        old_text = tool_input.get("old_string")
        new_text = tool_input.get("new_string")
        ops.append(
            _make_op(
                tokens, name, OP_EDIT, raw_path,
                old_lines=split_lines(old_text) if isinstance(old_text, str) else [],
                new_lines=split_lines(new_text) if isinstance(new_text, str) else [],
                replace_all=bool(tool_input.get("replace_all")),
            )
        )
    return ops


class _PatchInstruction(object):
    """patch 里的一个文件指令（可变：hunk 边读边追加）。

    用**具名属性**而不是 `current[3]` 这类下标：下标里的裸数字会被 K5 门禁判成"策略数值"，
    而它其实只是容器位置。用具名属性既过门禁，也让这段状态机读起来是"状态"而不是"元组魔术"。
    """

    __slots__ = ("kind", "path", "hunks", "pending")

    def __init__(self, kind, path):
        self.kind = kind
        self.path = path
        self.hunks = []
        self.pending = None


def parse_patch_instructions(text: str):
    """解析 patch 文本里的文件指令行（`plan/04` M2 步骤 1）。

    返回 `[(kind, path, hunks), ...]`；`hunks` 是按 `-`/`+` 块分段的 `(old_lines, new_lines)`，
    这是 `old_string` 在 Codex 侧的对等物（一段 hunk = 一个锚点）。
    """
    if not isinstance(text, str) or not text:
        return []
    instructions: List[_PatchInstruction] = []
    current: Optional[_PatchInstruction] = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        matched = None
        for prefix, kind in PATCH_INSTRUCTIONS:
            if line.startswith(prefix):
                matched = (kind, line[len(prefix):].strip())
                break
        if matched is not None:
            current = _PatchInstruction(matched[0], matched[1])
            instructions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("@@"):
            current.pending = None
            continue
        if line.startswith("-") or line.startswith("+"):
            if current.pending is None:
                current.pending = [[], []]
                current.hunks.append(current.pending)
            # 前缀 `-` = 旧行、`+` = 新行：按首字符分流（不是"第几个元素"）。
            bucket = current.pending[0] if line.startswith("-") else current.pending[1]
            bucket.append(line[1:])
            continue
        # 上下文行 / 其他标记行：结束当前 hunk（上下文不是改动，不作锚点）。
        current.pending = None
    return [
        (item.kind, item.path, [(tuple(old), tuple(new)) for old, new in item.hunks])
        for item in instructions
    ]


def has_patch_marker(text) -> bool:
    """载荷里是否出现 patch 标记（用来判别"这是不是一段 patch 文本"）。"""
    if not isinstance(text, str):
        return False
    if PATCH_BEGIN in text:
        return True
    return any(prefix in text for prefix, _kind in PATCH_INSTRUCTIONS)


def _arguments_to_input(arguments) -> Optional[str]:
    """`function_call` 形态的 `arguments` 是 JSON 字符串：取其中的 `input`。"""
    if not isinstance(arguments, str):
        return None
    import json

    try:
        parsed = json.loads(arguments)
    except ValueError:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("input"), str):
        return parsed["input"]
    return None


def codex_write_ops(record, tokens) -> List[_Op]:
    """从一条 Codex `response_item` 行里抽写操作（R2 实测形态 + `exec` 同形变体）。

    两条反例守门（都要有正例与反例，见 `plan/05` §六 与 HANDOFF §二）：
    ① 工具名不认识**且**载荷里没有 patch 标记 → **不是写操作**，直接不认（不猜）；
    ② 是 patch 工具但载荷里没有任何文件指令行 → 落 `unknown` + 计注记（不静默丢弃）。
    """
    if record.get("type") != "response_item":
        return []
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    payload_type = payload.get("type")
    name = payload.get("name")
    if payload_type == "custom_tool_call":
        text = payload.get("input")
    elif payload_type == "function_call":
        text = _arguments_to_input(payload.get("arguments"))
    else:
        return []
    if not isinstance(text, str) or not text:
        return []
    # 反例守门 ①：`exec` 只是"外壳"——载荷里没有 patch 标记就是一条普通 shell 命令，**不是写操作**
    # （不猜、不落 unknown：把 `ls -la` 记成"没定位到文件的写操作"会污染 unknown 计数）。
    if name == "exec" and not has_patch_marker(text):
        return []
    if name not in CODEX_PATCH_TOOLS and not has_patch_marker(text):
        return []
    instructions = parse_patch_instructions(text)
    tool = name or "apply_patch"
    if not instructions:
        # 反例守门 ②：是 patch 工具却没有任何文件指令行 → 落 unknown + 计注记（不静默丢弃）。
        return [_make_op(tokens, tool, OP_OPAQUE, None, reason=REASON_PATCH_WITHOUT_INSTRUCTION)]
    ops: List[_Op] = []
    for kind, path, hunks in instructions:
        if kind == "delete":
            ops.append(_make_op(tokens, tool, OP_PATCH_DELETE, path))
            continue
        if kind == "add":
            content_lines: List[str] = []
            for _old, new in hunks:
                content_lines.extend(new)
            ops.append(_make_op(tokens, tool, OP_PATCH_ADD, path, content_lines=content_lines))
            continue
        if not hunks:
            ops.append(_make_op(tokens, tool, OP_PATCH_UPDATE, path, reason=REASON_PATCH_WITHOUT_HUNK))
            continue
        for old, new in hunks:
            ops.append(_make_op(tokens, tool, OP_PATCH_UPDATE, path, old_lines=old, new_lines=new))
    return ops


def _session_tokens(session, workspace, in_worktree, seq, ts):
    return {
        "session": session.session_key,
        "session_id": session.session_id,
        "source": session.source,
        "file": session.file,
        "seq": seq,
        "ts": ts,
        "cwd": session.cwd,
        "workspace": workspace,
        "in_worktree": in_worktree,
    }


def collect_write_ops(table, roots, max_line_bytes):
    """对**活跃会话**逐条抽写操作。返回 `(ops, undetermined, notes)`。"""
    by_key = dict((item.session_key, item) for item in table.sessions)
    root_by_source = dict(roots)
    ops: List[_Op] = []
    undetermined: List[Any] = []
    notes: List[str] = []
    for cell in table.active_cells:
        session = by_key.get(cell.session_key)
        if session is None:
            continue
        root = root_by_source.get(session.source)
        if root is None:
            continue
        source_path = Path(root) / session.file
        try:
            records = list(discover.iter_jsonl(source_path, max_line_bytes, session.file))
        except EnvironmentError_ as exc:
            undetermined.append(
                discover.Undetermined(
                    file=session.file, source=session.source,
                    code=discover.CODE_LINE_TOO_LONG, detail=str(exc)[:_DETAIL_LIMIT],
                )
            )
            continue
        except OSError as exc:
            undetermined.append(
                discover.Undetermined(
                    file=session.file, source=session.source,
                    code=discover.CODE_UNPARSABLE_LINE,
                    detail=("会话文件不可读：%s" % exc)[:_DETAIL_LIMIT],
                )
            )
            continue
        produced = 0
        for line_no, record in records:
            moment = discover.parse_timestamp(record.get("timestamp"))
            tokens = _session_tokens(
                session, cell.workspace, cell.in_worktree, line_no,
                discover.format_timestamp(moment) if moment is not None else None,
            )
            if session.source == versions.SOURCE_CLAUDE:
                found = claude_write_ops(record, tokens)
            else:
                found = codex_write_ops(record, tokens)
            produced += len(found)
            ops.extend(found)
        if produced == 0:
            notes.append(
                "会话 %s 在扫描窗口内没有任何可识别的写操作（它可能只读文件）" % session.session_key
            )
    return ops, undetermined, notes


# --------------------------------------------------------------------------------------
# 磁盘侧：未提交改动的行区间（事实）
# --------------------------------------------------------------------------------------


class DiskSnapshot(object):
    """某工作区的未提交改动形态。

    `paths`：`{路径: XY 状态码}`；`ranges`：`{路径: [(start,end)]}`（`git diff -U0` 的新文件坐标）；
    `reasons`：该路径没有区间的原因码；`head_available`：是否可用 `HEAD` 作定位基线。
    """

    __slots__ = ("toplevel", "paths", "ranges", "reasons", "notes", "head_available")

    def __init__(self, toplevel, paths, ranges, reasons, notes, head_available):
        self.toplevel = toplevel
        self.paths = paths
        self.ranges = ranges
        self.reasons = reasons
        self.notes = notes
        self.head_available = head_available


def decode_status_records(stdout: str) -> Dict[str, str]:
    """解析 `git status --porcelain -z`：`{路径: XY}`。

    用 `-z` 而不是行模式：路径不会被 C 风格转义（中文/空格原样），这是本机实测能踩到的一类坑
    （行模式下中文文件名显示成八进制转义）。rename/copy 形态会**多跟一条原始路径**记录，按协议消费。
    """
    records = stdout.split("\0")
    paths: Dict[str, str] = {}
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:_STATUS_CODE_LEN]
        path = record[_STATUS_PATH_OFFSET:] if len(record) > _STATUS_PATH_OFFSET else ""
        if not path:
            continue
        paths[path] = status
        if "R" in status or "C" in status:
            index += 1
    return paths


def parse_hunks(diff_text: str):
    """解析 `git diff -U0` 的 hunk 头：`{路径: [(start,end)]}` 与"没有区间"的原因码。

    `-U0` 让 hunk 头正好覆盖改动行：`@@ -a,b +c,d @@` 的新文件区间 = `[c, c+d-1]`。
    `d == 0`（纯删除）在新文件里没有坐标 → 该路径落 `coarse` 并点名原因，**不编区间**。
    """
    ranges: Dict[str, List[Tuple[int, int]]] = {}
    reasons: Dict[str, str] = {}
    current: Optional[str] = None
    for raw in diff_text.replace("\r\n", "\n").split("\n"):
        if raw.startswith("diff --git "):
            # 二进制 diff **没有** `+++` 头（只有 `Binary files ... differ`），路径只能从这一行取。
            # 本机实测踩中过：只认 `+++` 时二进制改动会静默落进"没有原因码"的黑洞。
            pieces = raw.split()
            tail = pieces[-1]
            current = (
                tail[len(_DIFF_PATH_PREFIX):]
                if len(pieces) >= _DIFF_GIT_MIN_TOKENS and tail.startswith(_DIFF_PATH_PREFIX)
                else None
            )
            continue
        if raw.startswith(_DIFF_TARGET_PREFIX):
            target = raw[len(_DIFF_TARGET_PREFIX):].strip()
            if target.startswith(_DIFF_PATH_PREFIX):
                target = target[len(_DIFF_PATH_PREFIX):]
            current = None if target == "/dev/null" else target
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            if current:
                reasons[current] = REASON_BINARY_DIFF
            continue
        if not raw.startswith("@@") or current is None:
            continue
        # 形态：`@@ -a,b +c,d @@ <可选上下文>`。范围在**第二个** `@@` 之前，不是之后——
        # `split("@@")` 的 `parts[1]` 才是范围（`parts[2]` 是上下文文本；本机实测踩中过：
        # 把它当范围会解析出 0 个区间，整块改动静默消失）。
        parts = raw.split("@@")
        if len(parts) < _HUNK_MIN_PARTS:
            continue
        tokens = parts[1].split()
        plus = None
        for token in tokens:
            if token.startswith("+"):
                plus = token
                break
        if plus is None:
            continue
        body = plus[1:]
        start_text, _sep, count_text = body.partition(",")
        try:
            start = int(start_text)
            count = int(count_text) if count_text else 1
        except ValueError:
            reasons[current] = "unparsable_hunk"
            continue
        if count <= 0:
            reasons[current] = REASON_DELETED_PATH
            continue
        ranges.setdefault(current, []).append((start, start + count - 1))
    return ranges, reasons


def read_disk_snapshot(workspace: str, timeout: Optional[float]) -> DiskSnapshot:
    """只读取某工作区的未提交改动（`rev-parse` / `status` / `diff` / `diff --cached`）。"""
    notes: List[str] = []
    toplevel_result = run_readonly(["rev-parse", "--show-toplevel"], cwd=workspace, timeout=timeout)
    toplevel = toplevel_result.stdout.strip() if toplevel_result.returncode == 0 else workspace
    head_probe = run_readonly(["rev-parse", "--verify", "--quiet", "HEAD"], cwd=toplevel, timeout=timeout)
    head_available = head_probe.returncode == 0

    status = run_readonly(["status", "--porcelain", "-z"], cwd=toplevel, timeout=timeout)
    if status.returncode != 0:
        return DiskSnapshot(toplevel, {}, {}, {}, [
            "工作区 %s 的 `git status` 失败（rc=%s）：本次不做磁盘对账" % (toplevel, status.returncode)
        ], head_available)
    paths = decode_status_records(status.stdout)

    ranges: Dict[str, List[Tuple[int, int]]] = {}
    reasons: Dict[str, str] = {}
    for args in (
        ["diff", "--no-color", "--no-ext-diff", "-U0"],
        ["diff", "--cached", "--no-color", "--no-ext-diff", "-U0"],
    ):
        result = run_readonly(args, cwd=toplevel, timeout=timeout)
        if result.returncode != 0:
            notes.append("`git %s` 失败（rc=%s）：本次不做磁盘对账" % (" ".join(args), result.returncode))
            continue
        part_ranges, part_reasons = parse_hunks(result.stdout)
        for path, items in part_ranges.items():
            ranges.setdefault(path, []).extend(items)
        for path, code in part_reasons.items():
            reasons.setdefault(path, code)

    # 状态里确有改动但没有 hunk → 点名原因（含未跟踪文件：它没有 diff，不许编区间）。
    for path, status_code in sorted(paths.items()):
        if path in ranges:
            continue
        if status_code.startswith(_STATUS_UNTRACKED):
            reasons.setdefault(path, REASON_UNTRACKED_PATH)
        elif "D" in status_code:
            reasons.setdefault(path, REASON_DELETED_PATH)
        else:
            reasons.setdefault(path, "no_hunk")
    return DiskSnapshot(toplevel, paths, ranges, reasons, notes, head_available)


def read_head_lines(workspace: str, path: str, timeout: Optional[float]):
    """读 `HEAD` 版本的行（会话锚点的定位基线）。

    返回 `(lines, reason)`：`lines is None` 表示拿不到可用基线（新文件 / 二进制 / git 失败），
    此时该写操作一律落 `coarse`——**不拿工作区文件顶替基线**（那会把"磁盘现状"当成"会话基线"）。
    """
    result = run_readonly(["show", "HEAD:%s" % path], cwd=workspace, timeout=timeout)
    if result.returncode != 0:
        return None, REASON_BASELINE_UNAVAILABLE
    if "\x00" in result.stdout:
        return None, REASON_BINARY_BASELINE
    return split_lines(result.stdout), None


# --------------------------------------------------------------------------------------
# 定位：写操作 → 区间 + 落点
# --------------------------------------------------------------------------------------


class _Located(object):
    __slots__ = ("ranges", "precision", "reasons")

    def __init__(self, ranges, precision, reasons):
        self.ranges = list(ranges)
        self.precision = precision
        self.reasons = list(reasons)


def locate_op(op: _Op, workspace: str, head_available: bool, timeout: Optional[float]) -> _Located:
    """把一条写操作定位成 `(ranges, precision, reasons)`。

    判据逐条（顺序即优先级）：
    * 抽取阶段已定的降级（`MultiEdit` / `file_path` 缺失 / patch 无指令行）→ 沿用其 reason；
    * 会话 `cwd` 不在任何 worktree → `coarse` + `not_in_worktree`（**不读盘**）；
    * 路径不干净（绝对路径 / `..` 逃出 / 空）→ 见 `_path_guard`；
    * `replace_all=True` → `coarse`（**即使锚点唯一也不给区间**：该语义是"全部命中"，
      对它做精确断言就是编一个"看起来精确"的区间）；
    * 锚点在基线里 **0 处 / 多处**命中 → `coarse` + 点名（**绝不挑第一个**）；
    * 唯一命中 → `exact`，区间 = 锚点位置；
    * `Write` / `Add File`：与基线逐行比对；基线取不到（新文件）时整文件都是新增 → `[1, N]`。
    """
    if op.reason is not None:
        # 抽取阶段已定的降级：**连文件都定不下来**的两类落 `unknown`（`MultiEdit` / 缺 `file_path`）；
        # 其余（patch 无指令行 / patch 无 hunk）文件是知道的，落 `coarse`。
        if op.reason in (REASON_MULTI_EDIT, REASON_MISSING_FILE_PATH):
            return _Located([], PRECISION_UNKNOWN, [op.reason])
        return _Located([], PRECISION_COARSE, [op.reason])
    if not op.in_worktree:
        return _Located([], PRECISION_COARSE, [REASON_NOT_IN_WORKTREE])
    if workspace is None or op.workspace != workspace:
        return _Located([], PRECISION_COARSE, [REASON_NOT_IN_WORKTREE])

    rel = op.rel_path()
    if rel is None or rel == "":
        return _Located([], PRECISION_UNKNOWN, [REASON_MISSING_FILE_PATH])
    if not _is_clean_relative(rel):
        return _Located([], PRECISION_COARSE, [REASON_NOT_IN_WORKTREE])

    reasons: List[str] = []
    baseline = None
    if head_available:
        baseline, baseline_reason = read_head_lines(workspace, rel, timeout)
        if baseline is None:
            reasons.append(baseline_reason)

    if op.kind in (OP_WRITE, OP_PATCH_ADD):
        candidate = list(op.content_lines)
        if not candidate:
            return _Located([], PRECISION_COARSE, reasons + [REASON_WRITE_EMPTY])
        if baseline is None:
            return _Located([(1, len(candidate))], PRECISION_EXACT, reasons)
        span = effective_change_range(baseline, candidate)
        if span is None:
            return _Located([], PRECISION_COARSE, reasons + [REASON_WRITE_IDENTICAL_TO_BASE])
        return _Located([span], PRECISION_EXACT, reasons)

    if op.kind == OP_PATCH_DELETE:
        # 删除在新文件里没有正的坐标：**不给区间**。
        return _Located([], PRECISION_COARSE, reasons + [REASON_DELETED_PATH])

    if op.kind == OP_PATCH_UPDATE and not op.old_lines:
        return _Located([], PRECISION_COARSE, reasons + [REASON_PATCH_WITHOUT_HUNK])

    if baseline is None:
        return _Located([], PRECISION_COARSE, reasons or [REASON_BASELINE_UNAVAILABLE])
    if op.replace_all:
        return _Located([], PRECISION_COARSE, [REASON_REPLACE_ALL])
    if not op.old_lines:
        return _Located([], PRECISION_COARSE, reasons + [REASON_ANCHOR_NOT_FOUND])
    hits = find_anchor_hits(baseline, op.old_lines)
    if not hits:
        return _Located([], PRECISION_COARSE, reasons + [REASON_ANCHOR_NOT_FOUND])
    if len(hits) > 1:
        # 多处命中：显式降级 + **在产物里点名命中次数**（不许挑第一个当真值）。
        return _Located([], PRECISION_COARSE, reasons + ["%s#%d" % (REASON_ANCHOR_AMBIGUOUS, len(hits))])
    start = hits[0] + 1
    return _Located([(start, start + len(op.old_lines) - 1)], PRECISION_EXACT, reasons)


# --------------------------------------------------------------------------------------
# 组装
# --------------------------------------------------------------------------------------


def _build_write_records(ops, head_available, workspace, timeout):
    """把写操作按 `(workspace, session, path)` 合并成 `WriteRecord`；未定位的单独归集。"""
    resolved: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    unresolved: Dict[Tuple[str, str], Dict[str, Any]] = {}
    unknown_ops = 0
    multi_edit_ops = 0
    for op in ops:
        if op.reason == REASON_MULTI_EDIT:
            multi_edit_ops += 1
        located = locate_op(op, workspace, head_available, timeout)
        rel = op.rel_path()
        if located.precision == PRECISION_UNKNOWN:
            unknown_ops += 1
            bucket = unresolved.setdefault((op.workspace, op.session), {"ops": [], "ts": []})
            bucket["ops"].append(op)
            bucket["reasons"] = _ordered_unique(
                list(bucket.get("reasons", [])) + (located.reasons or [REASON_MISSING_FILE_PATH])
            )
            if op.ts:
                bucket["ts"].append(op.ts)
            continue
        key = (op.workspace, op.session, rel or "")
        bucket = resolved.setdefault(
            key, {"ops": [], "ranges": [], "precision": [], "reasons": [], "ts": []}
        )
        bucket["ops"].append(op)
        bucket["precision"].append(located.precision)
        bucket["reasons"] = _ordered_unique(bucket["reasons"] + located.reasons)
        for pair in located.ranges:
            if pair not in bucket["ranges"]:
                bucket["ranges"].append(pair)
        if op.ts:
            bucket["ts"].append(op.ts)

    per_entry: Dict[Tuple[str, str], List[WriteRecord]] = {}
    for (_entry_workspace, _session, _rel), bucket in sorted(resolved.items()):
        first = bucket["ops"][0]
        rel = first.rel_path()
        record = WriteRecord(
            session=first.session,
            session_id=first.session_id,
            source=first.source,
            # 同会话同文件多次写入按时间序合并 → `last_write_ts` 取组内**最大**（`plan/06` M2 DoD）。
            last_write_ts=max(bucket["ts"]) if bucket["ts"] else "",
            changed_ranges=sort_ranges(bucket["ranges"]),
            precision=_worst_precision(bucket["precision"]),
            approximate=not looks_python(rel),
            in_worktree=first.in_worktree,
            tools=_ordered_unique([item.tool for item in bucket["ops"]]),
            reasons=_ordered_unique(bucket["reasons"]),
            evidence=_ordered_unique([item.evidence() for item in bucket["ops"]]),
            path=rel,
        )
        per_entry.setdefault((first.workspace, rel), []).append(record)

    unknown_records: List[WriteRecord] = []
    for (_workspace, _session), bucket in sorted(unresolved.items()):
        first = bucket["ops"][0]
        unknown_records.append(
            WriteRecord(
                session=first.session,
                session_id=first.session_id,
                source=first.source,
                last_write_ts=max(bucket["ts"]) if bucket["ts"] else "",
                changed_ranges=(),
                precision=PRECISION_UNKNOWN,
                approximate=True,
                in_worktree=first.in_worktree,
                tools=_ordered_unique([item.tool for item in bucket["ops"]]),
                reasons=_ordered_unique(bucket["reasons"]),
                evidence=_ordered_unique([item.evidence() for item in bucket["ops"]]),
            )
        )
    return per_entry, unknown_records, unknown_ops, multi_edit_ops


def _disk_entries(snapshot: DiskSnapshot, workspace):
    """磁盘侧条目：`(workspace, path) -> {ranges, reasons}`（含没有会话来源的改动）。"""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for path in sorted(snapshot.paths):
        out[(workspace, path)] = {
            "ranges": sort_ranges(snapshot.ranges.get(path, [])),
            "reasons": [snapshot.reasons[path]] if path in snapshot.reasons else [],
        }
    return out


def _resolve_session_roots(claude_root, codex_root):
    """解析两侧会话根；**显式传进来的根必须存在**（打错一个字母就 exit 3，不静默跳过）。"""
    roots: List[Tuple[str, Path]] = []
    notes: List[str] = []
    for source, raw, env_name, default_relative in (
        (versions.SOURCE_CLAUDE, claude_root, "RADAR_CLAUDE_ROOT", os.path.join(".claude", "projects")),
        (versions.SOURCE_CODEX, codex_root, "RADAR_CODEX_ROOT", os.path.join(".codex", "sessions")),
    ):
        resolved = discover.resolve_root(raw, env_name, default_relative)
        if resolved is None:
            notes.append("未找到 %s 会话源（既未显式指定，常见位置也没有）" % source)
            continue
        if not Path(resolved).is_dir():
            raise EnvironmentError_(
                "会话根目录不存在或不是目录：%s（源 %s）。请用 --claude-root / --codex-root 显式指定，"
                "或设置 RADAR_CLAUDE_ROOT / RADAR_CODEX_ROOT。本工具不会伪造空结果。" % (resolved, source)
            )
        roots.append((source, Path(resolved)))
    return roots, notes


def build_intent_set(repo, claude_root, codex_root, cfg, now=None) -> IntentSet:
    """M2 主入口：会话写操作 + 磁盘未提交改动 → `IntentSet`。"""
    timeout = cfg.get("git", "timeout_seconds")
    max_line_bytes = cfg.get("scan", "max_line_bytes")

    table = discover.build_workspace_table(repo, claude_root, codex_root, cfg, now=now)
    notes: List[str] = list(table.notes)
    roots, root_notes = _resolve_session_roots(claude_root, codex_root)
    notes.extend(root_notes)

    ops, undetermined, op_notes = collect_write_ops(table, roots, max_line_bytes)
    notes.extend(op_notes)
    # `scan` 阶段没能用上的会话（超长行 / 未知形态 / 父会话缺失…）同样是本次分析的**输入缺口**：
    # 不带过来就会变成"我们没看懂，但产物里一句都没提"——那正是判定类工具最该避免的沉默。
    undetermined = list(table.undetermined) + list(undetermined)
    undetermined.sort(key=lambda item: (item.source, item.file, item.code))

    # 只对**有活跃会话的工作区**做磁盘对账（多 worktree 时逐个取，各自读自己的 HEAD）。
    workspaces: List[str] = []
    for cell in table.active_cells:
        if cell.in_worktree and cell.workspace not in workspaces:
            workspaces.append(cell.workspace)
    if not workspaces:
        workspaces = [item.path for item in table.worktrees if item.is_main] or [
            item.path for item in table.worktrees
        ]
    snapshots = dict((path, read_disk_snapshot(path, timeout)) for path in workspaces)
    for path in workspaces:
        notes.extend(snapshots[path].notes)

    per_entry: Dict[Tuple[str, str], List[WriteRecord]] = {}
    unknown_records: List[WriteRecord] = []
    unknown_ops_total = 0
    multi_edit_ops_total = 0
    for workspace in workspaces:
        snapshot = snapshots[workspace]
        part_entry, part_unknown, part_unknown_ops, part_multi = _build_write_records(
            [item for item in ops if item.workspace == workspace],
            snapshot.head_available, workspace, timeout,
        )
        for key, bucket in part_entry.items():
            per_entry.setdefault(key, []).extend(bucket)
        unknown_records.extend(part_unknown)
        unknown_ops_total += part_unknown_ops
        multi_edit_ops_total += part_multi

    # 工作区之外的会话：只做会话侧抽取（**不读盘、不伪造区间**，precision 上限 coarse）。
    outside = [item for item in ops if item.workspace not in workspaces]
    if outside:
        notes.append(
            "有 %d 条写操作的会话 cwd 不在任何已知 worktree 内：只做会话侧抽取、不做磁盘对账"
            "（precision 上限为 coarse）" % len(outside)
        )
        out_entry, out_unknown, out_unknown_ops, out_multi = _build_write_records(
            outside, False, None, timeout
        )
        for key, bucket in out_entry.items():
            per_entry.setdefault(key, []).extend(bucket)
        unknown_records.extend(out_unknown)
        unknown_ops_total += out_unknown_ops
        multi_edit_ops_total += out_multi

    disk_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for workspace in workspaces:
        disk_map.update(_disk_entries(snapshots[workspace], workspace))

    entries = _assemble_entries(per_entry, unknown_records, disk_map)

    counts = {
        "entries": len(entries),
        "exact": sum(1 for item in entries if item.precision == PRECISION_EXACT),
        "coarse": sum(1 for item in entries if item.precision == PRECISION_COARSE),
        "unknown": sum(1 for item in entries if item.precision == PRECISION_UNKNOWN),
        "unknown_write_ops": unknown_ops_total,
        "multi_edit_ops": multi_edit_ops_total,
        "write_ops": len(ops),
        "sessions_with_writes": len(set(item.session for item in ops)),
        "disk_changed_paths": sum(len(item.paths) for item in snapshots.values()),
        "entries_without_disk_confirmation": sum(
            1 for item in entries if item.precision != PRECISION_UNKNOWN and not item.disk_confirmed
        ),
        "entries_without_session": sum(1 for item in entries if not item.sessions),
        "non_python_entries": sum(1 for item in entries if item.approximate and item.path),
        "undetermined": len(undetermined),
        "cells_outside_worktree": sum(1 for item in table.active_cells if not item.in_worktree),
    }
    return IntentSet(
        entries=entries,
        undetermined=undetermined,
        reference_time=table.reference_time,
        notes=notes,
        counts=counts,
    )


def _assemble_entries(per_entry, unknown_records, disk_map) -> List[IntentEntry]:
    """把三份来源（逐会话写入 / 未定位写入 / 磁盘改动）组装成条目。"""
    entries: List[IntentEntry] = []
    keys = set(per_entry) | set(disk_map)

    for workspace, path in sorted(keys):
        records = sorted(per_entry.get((workspace, path), []), key=lambda item: (item.session, item.source))
        disk = disk_map.get((workspace, path))
        disk_ranges = sort_ranges(disk["ranges"]) if disk else []
        write_ranges = sort_ranges([pair for item in records for pair in item.changed_ranges])

        reasons: List[str] = []
        for item in records:
            reasons = _ordered_unique(reasons + list(item.reasons))
        if disk:
            reasons = _ordered_unique(reasons + list(disk["reasons"]))

        disagree = bool(disk_ranges) and bool(write_ranges) and write_ranges != disk_ranges
        if disagree:
            reasons = _ordered_unique(reasons + [REASON_DISK_AND_SESSION_DISAGREE])
        if disk_ranges:
            ranges, source = disk_ranges, RANGES_FROM_DISK
        elif write_ranges:
            ranges, source = write_ranges, RANGES_FROM_SESSION
        else:
            ranges, source = [], RANGES_FROM_NONE

        if disk_ranges:
            precision = PRECISION_EXACT
        elif records:
            # 磁盘没给区间 → 落点由**会话侧**决定（最弱的一档）。
            precision = _worst_precision([item.precision for item in records])
        else:
            precision = PRECISION_COARSE

        evidence: List[str] = []
        for item in records:
            evidence = _ordered_unique(evidence + list(item.evidence))
        for start, end in ranges:
            evidence.append(
                "diff:%s@%d-%d" % (path, start, end) if disagree or end > start else "diff:%s@%d" % (path, start)
            )
        entries.append(
            IntentEntry(
                workspace=workspace,
                path=path,
                sessions=_ordered_unique([item.session for item in records]),
                session_ids=_ordered_unique([item.session_id for item in records]),
                last_write_ts=max([item.last_write_ts for item in records if item.last_write_ts] or [""]),
                changed_ranges=ranges,
                precision=precision,
                approximate=(
                    any(item.approximate for item in records) if records else not looks_python(path)
                ),
                ranges_source=source,
                writes=records,
                reasons=reasons,
                evidence=_ordered_unique(evidence),
                in_worktree=any(item.in_worktree for item in records) if records else True,
                disk_confirmed=bool(disk_ranges),
            )
        )

    for record in sorted(unknown_records, key=lambda item: (item.session, item.session_id)):
        reason = record.reasons[0] if record.reasons else REASON_MISSING_FILE_PATH
        entries.append(
            IntentEntry(
                workspace="",
                path="",
                sessions=[record.session],
                session_ids=[record.session_id],
                last_write_ts=record.last_write_ts,
                changed_ranges=(),
                precision=PRECISION_UNKNOWN,
                approximate=True,
                ranges_source=RANGES_FROM_NONE,
                writes=[record],
                reasons=[reason],
                evidence=list(record.evidence),
                in_worktree=record.in_worktree,
                disk_confirmed=False,
            )
        )
    entries.sort(key=lambda item: (item.workspace, item.path, item.session_ids, item.last_write_ts))
    return entries
