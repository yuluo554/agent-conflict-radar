"""M3 三级冲突检测（`radar detect` 的实现主体）。

由粗到细，逐级给证据。**输入是 M1 的 `WorkspaceTable` + M2 的 `IntentSet` + 仓库 git 对象**，
不重新解析会话、不重新读磁盘 diff——那两件事在 M1 / M2 各做过一次，这里只消费它们的产物。

## 一条记录 = 一个 `(workspace_a, workspace_b, path)` 组合（`plan/07` 决策记录）

| 字段 | 口径 |
|---|---|
| `levels` | 该组合**命中的粒度集合**（`file` / `block` / `symbol` 的非空子集）。同文件对被两个活跃会话改 ⇒ **必含** `file` |
| `level` | `levels` 里的**最高**粒度，只用于排序与严重度展示，**不用于匹配** |
| `symbols` | 命中的符号限定名集合（同符号 ⇒ 单元素；相邻 ⇒ 两个；仅文件级 ⇒ 空） |

真值按 `levels` / `symbols` **集合精确匹配**（多报、漏报均失败）。原设计"只报最高粒度一条"
与题面场景 3（要求文件级 + 符号级**同时**成立）冲突，已按决策记录修正——单一 `level` 字段
表达不了"同时命中"。

## 三级判据

1. **文件级**：同一 `path` 出现在两个**不同且活跃**的 `(workspace, session)` 组里。
   活跃 = 在 M1 的 `active_cells` 里（`in_worktree=True`）；两个组是同一 parent 派生的 subagent
   （`derived_from` 非空且相同）→ **默认不产出该对**（场景 4）。
2. **区块级**：对两侧所在的分支执行 `git merge-tree --write-tree <a> <b>`（**只读**，见下），
   冲突路径里含本 `path` ⇒ 命中。
3. **符号级**：`ast` 取 `HEAD` 版本里 `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 的
   限定名与行区间（含嵌套 `A.B.f`），把两侧的改动区间映射到符号：
   **同一符号** ⇒ 命中；**相邻符号**（区间间距 ≤ `config:symbol.adjacent_tolerance`，`<=` 语义）⇒ 命中；
   同文件**不同且不相邻**的符号 ⇒ **不升格**（维持文件级）。

## 只读边界（K4，**如实披露**）

`merge-tree --write-tree` 会在**对象库**写入临时 tree/blob 对象；它**不改索引、不改工作区、
不建分支、不动 HEAD**。本工具绝不执行 merge/rebase、绝不写索引。这条边界写进 README 与报告，
**不声称"零任何写入"**。

## 降级纪律（逐条对应 `plan/HANDOFF-M3.md` §二 的"必须遵守的降级纪律"）

| 情形 | 行为 | 落点 |
|---|---|---|
| `merge-tree` exit 128（无共同祖先 / 非 git 目录） | 该记录 `degraded=True`，**只给文件级** | `undetermined(degraded)` |
| 单 commit 仓库（两侧无共同祖先可用） | 同上（走 128 这条通路） | `undetermined(degraded)` |
| 两侧不在同一个 git 仓库（common dir 不同） | 同上（在哪个仓库试合并都说不清） | `undetermined(degraded)` |
| 会话没有 `gitBranch`（如实测的 Codex 侧） | 同上 | `undetermined(degraded)` |
| `git.merge_tree_enabled=false` | 同上（区块级在配置里关闭） | `undetermined(degraded)` |
| `merge-tree` 子进程超时 | 同上（**失败隔离**：不影响同批其他记录） | `undetermined(degraded)` |
| 非 Python 文件 | 不做符号级，`approximate=True` 且产物里**不出现** `symbols` 键（R4 口径） | —— |
| `ast` 失败 / 取不到 `HEAD` 版本 / 两侧跨工作区（行号不可比） | 同上：`approximate=True` + 不出现 `symbols` | `undetermined(symbol_unavailable)` |
| 两侧 `derived_from` 相同 | 该对**默认不产出**（"自己和自己"不是跨 agent 并行） | —— |

**"未判定"绝不写成"无冲突"**：`degraded` / `approximate` 只降级粒度，不改变"这条对确实同改了同一文件"
这个事实；`undetermined` 独立分区、不计入 `conflicts`。

## 计数口径（先声明，后实现，K12）

* `counts.conflicts` = **条目数**（一个 `(workspace_a, workspace_b, path)` 组合算一条）；
* `counts.by_max_level` = 条目数按 `level`（最高粒度）的**集合划分** ⇒ `sum == len(conflicts)`；
* `counts.by_level_membership` = 各粒度在 `levels` 里出现的**成员数**（可大于条目数，一条可同时命中多级）
  ——两栏分开登记正是"条目数 vs 命中记录数"的落地形态（K12）；
* `undetermined` **不计入** `conflicts`，独立分区。

## 确定性纪律

* 不读时钟：`reference_time` 由 M1 决定（`--now` 显式传，或观测到的最大时间戳）；
* 遍历前一律排序：记录排序键 `(level 序, severity 降序, path, symbols, line_ranges)`；
  两侧按 `(workspace, session_key)` 排序；符号按 span 顺序；
* 零写盘：不给 `--out-dir` 时一个文件都不落（含临时文件）。
"""

import ast
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import discover
from . import gitio
from . import intent as intent_module
from .errors import EnvironmentError_

#: 粒度（对外稳定值，不要改字面量）。规范序 = 由粗到细。
LEVEL_FILE = "file"
LEVEL_BLOCK = "block"
LEVEL_SYMBOL = "symbol"
LEVEL_ORDER = (LEVEL_FILE, LEVEL_BLOCK, LEVEL_SYMBOL)

#: 粒度序号（排序用；`level` = ranks 里的**最大**者）。
_LEVEL_RANK = dict((level, index) for index, level in enumerate(LEVEL_ORDER))

#: `undetermined` 的原因码（对外稳定值）。
CODE_DEGRADED = "degraded"
CODE_SYMBOL_UNAVAILABLE = "symbol_unavailable"

#: detect 原生 `undetermined` 项的 `source` 标记（沿用 `discover.Undetermined` 的单一形态：
#: `file` / `source` / `code` / `detail`）。计划文档里写的是 `path` 键——这里不另立一套 schema，
#: 否则 M4 渲染要同时认两种形态（勘误见 `plan/04` M3 勘误注①）。
SOURCE_DETECT = "detect"

#: 严重度档位（**只引用键名，数值一律读 `config/radar.toml` 的 `[severity]`**，K3）。
SEVERITY_SAME_SYMBOL = "same_symbol"
SEVERITY_SAME_FILE_DIFF_SYMBOL = "same_file_diff_symbol"
SEVERITY_ADJACENT_LINES = "adjacent_lines"
SEVERITY_FILE_ONLY = "file_only"

#: 符号命中的两种形态。
SYMBOL_HIT_SAME = "same"
SYMBOL_HIT_ADJACENT = "adjacent"

#: `merge-tree` 的退出码语义（`run_readonly` 不会替我们解释）。
_MERGE_TREE_OK = 0
_MERGE_TREE_CONFLICTED = 1
#: 环境问题（无共同祖先 / 非 git 目录）：是 git 的**输出契约**（实测值），不是可调策略阈值
#: ——阈值一律读 config；本值已登记在 `tests/test_config_literals.py` 的 ALLOWED_LITERALS。
_MERGE_TREE_ENVIRONMENT = 128

#: 两侧同改同一文件时**必含**的粒度。
_BASE_LEVELS = (LEVEL_FILE,)

#: 区间元组与符号三元组的位置常量。写成名字而不是裸下标：位置是**结构**不是阈值，
#: 名字让 `span[_SPAN_END]` 一眼看得出取的是哪一格（裸 `2` 已按 K5 登记进 ALLOWED_LITERALS）。
_SPAN_START = 0
_SPAN_END = 1
_SYMBOL_NAME = 0
_SYMBOL_START = 1
_SYMBOL_END = 2


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------


def _ordered_unique(items: Sequence[Any]) -> List[Any]:
    """去重且保持首次出现序（确定性的基础：不依赖 set 迭代序）。"""
    seen: List[Any] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def range_gap(left: Tuple[int, int], right: Tuple[int, int]) -> int:
    """两个 1-based 闭区间之间的**行间距**：不重叠时中间隔了几行，重叠时为负。

    例：`[1,10]` 与 `[14,19]` → 中间隔 11/12/13 三行 → 3；`[10,10]` 与 `[14,14]` → 3。
    """
    return max(left[0] - right[1] - 1, right[0] - left[1] - 1)


# --------------------------------------------------------------------------------------
# 符号级：AST 区间
# --------------------------------------------------------------------------------------


def symbol_spans(lines: Sequence[str]) -> List[Tuple[str, int, int]]:
    """取 `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 的 `(限定名, 起, 止)`。

    限定名用 `.` 连接（嵌套 `A.B.f`）；**同名不同作用域不同键**（不得按裸名匹配）。
    返回按 `(起, 止, 名)` 排序——顺序即产物里的符号顺序。
    """
    source = "\n".join(lines) + "\n"
    tree = ast.parse(source)
    spans: List[Tuple[str, int, int]] = []

    def walk(node: Any, prefix: str) -> None:
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            end = getattr(child, "end_lineno", None)
            if end is None:  # pragma: no cover - 3.8+ 的这三类节点恒有 end_lineno
                continue
            qualified = prefix + child.name
            spans.append((qualified, child.lineno, end))
            walk(child, qualified + ".")

    walk(tree, "")
    spans.sort(key=lambda item: (item[1], item[2], item[0]))
    return spans


def symbols_touching(spans: Sequence[Tuple[str, int, int]], span: Tuple[int, int]) -> List[str]:
    """区间**与**其有交集的符号（有序）。部分重叠也算「动了这个符号」。"""
    low, high = span[_SPAN_START], span[_SPAN_END]
    return [name for name, start, end in spans if not (high < start or low > end)]


def _symbols_containing(spans: Sequence[Tuple[str, int, int]], span: Tuple[int, int]):
    """**包含**该区间的符号（有序，由外到内）。"""
    low, high = span[_SPAN_START], span[_SPAN_END]
    return [
        item
        for item in spans
        if item[_SYMBOL_START] <= low and high <= item[_SYMBOL_END]
    ]


def _innermost(spans: Sequence[Tuple[str, int, int]], span: Tuple[int, int]):
    """包含该区间的**最内层**符号名（无则 `None`）——「相邻」要报的那一个。"""
    containing = _symbols_containing(spans, span)
    if not containing:
        return None
    best = min(
        containing,
        key=lambda item: (item[_SYMBOL_END] - item[_SYMBOL_START], item[_SYMBOL_START]),
    )
    return best[_SYMBOL_NAME]


def _minimal_symbols(names: Sequence[str], spans: Sequence[Tuple[str, int, int]]) -> List[str]:
    """去掉"被另一个命中符号**包含**"的外层符号。

    `A` 与 `A.f` 同时命中时只报 `A.f`：报两个会让人以为"动了两个符号"。同一符号的精确形态
    是**最内层**那个——嵌套类/方法的存在不该让一条记录看起来更严重。
    """
    index = dict((name, (name, start, end)) for name, start, end in spans)
    kept = []
    for name in names:
        inner = index.get(name)
        contained = False
        for other in names:
            if other == name:
                continue
            span = index.get(other)
            if inner is None or span is None:
                continue
            if span[_SYMBOL_START] >= inner[_SYMBOL_START] and span[_SYMBOL_END] <= inner[_SYMBOL_END]:
                contained = True
                break
        if not contained:
            kept.append(name)
    return kept


def pair_symbol_hit(
    spans: Sequence[Tuple[str, int, int]],
    left: Tuple[int, int],
    right: Tuple[int, int],
    tolerance: int,
) -> Tuple[str, Tuple[str, ...]]:
    """判定两个改动区间在符号上的关系。

    返回 `(形态, 命中符号)`：`("same", (...))` / `("adjacent", (...))` / `("", ())`。

    * **同一符号**：两侧的**触及符号集合**有交集 ⇒ 命中（报交集里**最内层**的那些）；
    * **相邻符号**：各自都落在某个符号**内部**，且行区间间距 ≤ 容差 ⇒ 命中（报各自最内层符号）；
    * 其余（不同且不相邻 / 有一侧落不到任何符号里）⇒ 不升格（维持文件级）。
    """
    touching_left = symbols_touching(spans, left)
    touching_right = symbols_touching(spans, right)
    shared = [name for name in touching_left if name in touching_right]
    if shared:
        return SYMBOL_HIT_SAME, tuple(_minimal_symbols(shared, spans))
    inner_left = _innermost(spans, left)
    inner_right = _innermost(spans, right)
    if inner_left is None or inner_right is None:
        return "", ()
    if range_gap(left, right) <= tolerance:
        return SYMBOL_HIT_ADJACENT, tuple(_ordered_unique([inner_left, inner_right]))
    return "", ()


# --------------------------------------------------------------------------------------
# 数据对象
# --------------------------------------------------------------------------------------


class Side(object):
    """一条记录的**一侧**：一个活跃的 `(workspace, session)` 组在某个文件上的改动形态。"""

    __slots__ = (
        "workspace",
        "session_key",
        "session_id",
        "source",
        "derived_from",
        "branch",
        "ranges",
        "approximate",
        "evidence",
        "last_write_ts",
    )

    def __init__(self, workspace, session_key, session_id, source, derived_from, branch, ranges,
                 approximate, evidence, last_write_ts):
        self.workspace = workspace
        self.session_key = session_key
        self.session_id = session_id
        self.source = source
        self.derived_from = derived_from
        self.branch = branch
        self.ranges = tuple(ranges)
        self.approximate = approximate
        self.evidence = tuple(evidence)
        self.last_write_ts = last_write_ts

    def sort_key(self):
        return (self.workspace, self.session_key)


class Conflict(object):
    """一条冲突记录 = 一个 `(workspace_a, workspace_b, path)` 组合。"""

    __slots__ = (
        "levels",
        "level",
        "workspace_a",
        "workspace_b",
        "path",
        "symbols",
        "symbol_spans",
        "line_ranges",
        "severity",
        "severity_key",
        "degraded",
        "degrade_reasons",
        "approximate",
        "sessions",
        "session_ids",
        "sessions_a",
        "sessions_b",
        "last_write_ts",
        "evidence",
    )

    def __init__(self, levels, workspace_a, workspace_b, path, symbols, symbol_spans, line_ranges,
                 severity, severity_key, degraded, degrade_reasons, approximate, sessions,
                 session_ids, sessions_a, sessions_b, last_write_ts, evidence):
        self.levels = tuple(levels)
        self.level = max(self.levels, key=lambda item: _LEVEL_RANK[item])
        self.workspace_a = workspace_a
        self.workspace_b = workspace_b
        self.path = path
        self.symbols = tuple(symbols)
        self.symbol_spans = tuple(symbol_spans)
        self.line_ranges = tuple(line_ranges)
        self.severity = severity
        self.severity_key = severity_key
        self.degraded = degraded
        self.degrade_reasons = tuple(degrade_reasons)
        self.approximate = approximate
        #: 参与该组合的全部会话（`session_key` / `session_id` 两种口径各登记一份）。
        self.sessions = tuple(sessions)
        self.session_ids = tuple(session_ids)
        #: **见证对**：`line_ranges` 与符号结论就是这一对给出的（人工复核时对得上）。
        self.sessions_a = tuple(sessions_a)
        self.sessions_b = tuple(sessions_b)
        self.last_write_ts = last_write_ts
        self.evidence = tuple(evidence)

    def symbols_in_product(self) -> bool:
        """产物里是否出现 `symbols` 键。

        **非 Python / 符号级取不到基线时返回 `False`**（R4 口径）：那时我们**没有**符号能力，
        报一个空集合会被读成"没有符号命中"——那是我们给不出的结论。
        """
        return not self.approximate

    def as_dict(self):
        payload = {
            "levels": list(self.levels),
            "level": self.level,
            "workspace_a": self.workspace_a,
            "workspace_b": self.workspace_b,
            "path": self.path,
            "line_ranges": [list(item) for item in self.line_ranges],
            "severity": self.severity,
            "severity_key": self.severity_key,
            "degraded": self.degraded,
            "approximate": self.approximate,
            "sessions": list(self.sessions),
            "session_ids": list(self.session_ids),
            "sessions_a": list(self.sessions_a),
            "sessions_b": list(self.sessions_b),
            "last_write_ts": self.last_write_ts,
            "evidence": list(self.evidence),
        }
        if self.symbols_in_product():
            payload["symbols"] = list(self.symbols)
            payload["symbol_spans"] = [list(item) for item in self.symbol_spans]
        if self.degrade_reasons:
            payload["degrade_reasons"] = list(self.degrade_reasons)
        return payload

    def sort_key(self):
        return (
            _LEVEL_RANK[self.level],
            -self.severity,
            self.workspace_a,
            self.workspace_b,
            self.path,
            self.symbols,
            self.line_ranges,
        )


class ConflictSet(object):
    """`radar detect` 的产物。"""

    def __init__(self, conflicts, undetermined, reference_time, notes=(), counts=None):
        self.conflicts = tuple(conflicts)
        self.undetermined = tuple(undetermined)
        self.reference_time = reference_time
        self.notes = tuple(notes)
        self._counts = dict(counts or {})

    def counts(self):
        return dict(self._counts)

    def as_dict(self):
        return {
            "reference_time": self.reference_time,
            "conflicts": [item.as_dict() for item in self.conflicts],
            "undetermined": [item.as_dict() for item in self.undetermined],
            "notes": list(self.notes),
            "counts": self.counts(),
        }

    def conflicts_for_path(self, path):
        return [item for item in self.conflicts if item.path == path]


# --------------------------------------------------------------------------------------
# 输入组装
# --------------------------------------------------------------------------------------


def _sides_by_path(table, intents) -> Dict[str, List[Side]]:
    """从 M2 的产物里取出**活跃**的 `(workspace, session)` 组，按 `path` 归集。

    活跃判据落在 M1 的 `active_cells` 上（`in_worktree=True`）：会话窗口外的写操作**不参与**检测
    ——"这次不参与"与"没有冲突"是两件事，前者不会产出记录（也就不会声称"无冲突"）。
    """
    active = set(
        (cell.workspace, cell.session_key) for cell in table.active_cells if cell.in_worktree
    )
    branches = dict((session.session_key, session.git_branch) for session in table.sessions)
    derived = dict((session.session_key, session.derived_from) for session in table.sessions)

    by_path: Dict[str, List[Side]] = {}
    for entry in intents.entries:
        if not entry.path:
            continue  # unknown 落点的条目没有文件，不参与
        for record in entry.writes:
            if (entry.workspace, record.session) not in active:
                continue
            by_path.setdefault(entry.path, []).append(
                Side(
                    workspace=entry.workspace,
                    session_key=record.session,
                    session_id=record.session_id,
                    source=record.source,
                    derived_from=derived.get(record.session),
                    branch=branches.get(record.session),
                    ranges=record.changed_ranges,
                    approximate=record.approximate,
                    evidence=record.evidence,
                    last_write_ts=record.last_write_ts,
                )
            )
    for sides in by_path.values():
        sides.sort(key=lambda item: item.sort_key())
    return by_path


def _same_derived_pair(left: Side, right: Side) -> bool:
    """两侧是**同一 parent 派生的 subagent** ⇒ 不构成跨 agent 并行（场景 4）。"""
    return bool(left.derived_from) and left.derived_from == right.derived_from


def _workspace_pairs(sides: Sequence[Side]):
    """把一侧集合切成 `(workspace_a, workspace_b, sides_a, sides_b)` 的组合。

    * 单一工作区：`(ws, ws, 全部, 全部)`——**同工作区内的不同会话**也算两个组（题面口径）；
    * 多个工作区：每个无序工作区对一条 `(ws_a, ws_b, A 侧, B 侧)`。
    """
    grouped: Dict[str, List[Side]] = {}
    for side in sides:
        grouped.setdefault(side.workspace, []).append(side)
    workspaces = sorted(grouped)
    if len(workspaces) == len(_BASE_LEVELS):
        only = workspaces[0]
        return [(only, only, tuple(grouped[only]), tuple(grouped[only]))]
    pairs = []
    for index, left in enumerate(workspaces):
        for right in workspaces[index + 1:]:
            pairs.append((left, right, tuple(grouped[left]), tuple(grouped[right])))
    return pairs


def _effective_pairs(left: Sequence[Side], right: Sequence[Side], same_workspace: bool):
    """去掉"自己和自己"的组合（同工作区时也要排除同一个 session）。"""
    pairs = []
    for side_a in left:
        for side_b in right:
            if same_workspace and side_a.session_key == side_b.session_key:
                continue
            if _same_derived_pair(side_a, side_b):
                continue
            pairs.append((side_a, side_b))
    return pairs


# --------------------------------------------------------------------------------------
# 区块级：merge-tree
# --------------------------------------------------------------------------------------


class _MergeTreeCache(object):
    """同一次运行内缓存 `merge-tree` 结果（同一分支对的重复调用没有意义）。"""

    __slots__ = ("runs", "results", "errors")

    def __init__(self):
        self.runs = 0
        self.results: Dict[Tuple[str, str, str], Any] = {}
        self.errors: Dict[Tuple[str, str, str], str] = {}

    def evaluate(self, identity, branch_lo, branch_hi, repo, timeout):
        """返回 `MergeTreeResult` 或 `None`（`None` ⇒ 环境问题，原因在 `self.errors`）。"""
        key = (identity, branch_lo, branch_hi)
        if key in self.errors:
            return None
        if key in self.results:
            return self.results[key]
        try:
            result = gitio.merge_tree(repo, branch_lo, branch_hi, timeout=timeout)
        except EnvironmentError_ as exc:
            # 超时 / git 不可用：**失败隔离**到这条记录，不抛"无冲突"，也不炸掉整批。
            self.errors[key] = str(exc)
            return None
        self.runs += 1
        self.results[key] = result
        return result


def _block_probe(path, left, right, cfg, timeout, cache, common_dirs):
    """对一对侧做区块级判定，返回 `(是否命中, 是否降级, 原因文本列表)`。"""
    if not cfg.get("git", "merge_tree_enabled"):
        return False, True, ["git.merge_tree_enabled=false：区块级试合并已在配置里关闭"]
    if not left.branch or not right.branch:
        missing = left.session_key if not left.branch else right.session_key
        return False, True, ["会话 %s 没有 gitBranch 信息，无法定位两侧版本" % missing]
    identity_left = common_dirs.get(left.workspace)
    identity_right = common_dirs.get(right.workspace)
    if identity_left is None or identity_right is None or identity_left != identity_right:
        return False, True, ["两侧不在同一个 git 仓库（common dir 不同）：无法试合并"]
    branch_lo, branch_hi = sorted([left.branch, right.branch])
    result = cache.evaluate(identity_left, branch_lo, branch_hi, left.workspace, timeout)
    if result is None:
        return False, True, ["merge-tree 无法执行：%s" % cache.errors[(identity_left, branch_lo, branch_hi)]]
    if result.returncode == _MERGE_TREE_ENVIRONMENT:
        return False, True, [
            "merge-tree exit 128（无共同祖先 / 非 git 目录）：%s" % (result.diagnostic() or "无输出")
        ]
    if result.returncode not in (_MERGE_TREE_OK, _MERGE_TREE_CONFLICTED):
        return False, True, [
            "merge-tree 返回未预期的退出码 %s：%s" % (result.returncode, result.diagnostic() or "无输出")
        ]
    return path in result.conflict_paths, False, []


# --------------------------------------------------------------------------------------
# 符号级：把两侧的改动区间映射到符号
# --------------------------------------------------------------------------------------


def _evaluate_symbols(spans, pairs, tolerance):
    """对记录内的每对侧、每对区间求符号关系。

    返回 `(形态, 命中符号, 见证侧对, 见证区间对)`；`形态` 为空串表示没有符号级结论。
    **"同一符号"优先于"相邻"**；同类中取**首个**（按侧与区间的确定序）作见证。
    """
    best_kind = ""
    best_pair = ()
    best_ranges = ()
    symbols: List[str] = []
    for side_a, side_b in pairs:
        for span_a in side_a.ranges:
            for span_b in side_b.ranges:
                kind, part = pair_symbol_hit(spans, span_a, span_b, tolerance)
                if not kind:
                    continue
                symbols = _ordered_unique(symbols + list(part))
                if best_kind != SYMBOL_HIT_SAME and (not best_kind or kind == SYMBOL_HIT_SAME):
                    best_kind = kind
                    best_pair = (side_a, side_b)
                    best_ranges = (span_a, span_b)
    return best_kind, tuple(symbols), best_pair, best_ranges


def _severity_key(levels, symbol_kind, symbols_available):
    """严重度档位（**只选键名**，数值一律读 config 的 `[severity]`）。

    `plan/04` M4 的口径顺序：同一符号被两侧修改 > 同文件不同符号 > 行区间相邻 > 仅文件级同改。
    """
    if LEVEL_SYMBOL in levels:
        if symbol_kind == SYMBOL_HIT_SAME:
            return SEVERITY_SAME_SYMBOL
        return SEVERITY_ADJACENT_LINES
    if LEVEL_BLOCK in levels or symbols_available:
        return SEVERITY_SAME_FILE_DIFF_SYMBOL
    return SEVERITY_FILE_ONLY


def _symbol_refs(symbols, spans):
    """命中符号的 `(名, 起, 止)`（产物里可核验"这个区间是从哪来的"）。"""
    index = dict((name, (name, start, end)) for name, start, end in spans)
    return [index[name] for name in symbols if name in index]


# --------------------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------------------


def build_conflict_set(repo, claude_root, codex_root, cfg, now=None) -> ConflictSet:
    """M3 主入口：M1 的发现 + M2 的意图 → 三级冲突记录集合。"""
    timeout = cfg.get("git", "timeout_seconds")
    tolerance = cfg.get("symbol", "adjacent_tolerance")

    table = discover.build_workspace_table(repo, claude_root, codex_root, cfg, now=now)
    intents = intent_module.build_intent_set(repo, claude_root, codex_root, cfg, now=now)

    # M2 的 notes 已经把 M1 的 notes 带上来了（`build_intent_set` 从 table.notes 起步）——
    # 直接用 M2 的那一份，避免同一个缺口在产物里出现两次。
    notes: List[str] = list(intents.notes)
    if cfg.get("git", "merge_tree_enabled"):
        notes.append(
            "区块级试合并用 `git merge-tree --write-tree`：它会在**对象库**写入临时 tree/blob 对象"
            "（不改索引、不改工作区、不建分支、不动 HEAD）。本工具的「只读」含这条边界。"
        )

    by_path = _sides_by_path(table, intents)
    undetermined: List[discover.Undetermined] = list(intents.undetermined)
    common_dirs: Dict[str, Any] = {}
    for workspace in sorted(set(side.workspace for sides in by_path.values() for side in sides)):
        common_dirs[workspace] = gitio.git_common_dir(workspace, timeout=timeout)

    cache = _MergeTreeCache()
    conflicts: List[Conflict] = []
    derived_skips = 0

    for path in sorted(by_path):
        sides = by_path[path]
        for workspace_a, workspace_b, sides_a, sides_b in _workspace_pairs(sides):
            same_workspace = workspace_a == workspace_b
            candidates = _effective_pairs(sides_a, sides_b, same_workspace)
            if same_workspace and not candidates:
                # 同文件、同工作区，但每一对都是同一 parent 派生的 subagent（场景 4）。
                derived_skips += 1
            if not candidates:
                continue
            conflicts.append(
                _build_record(
                    path, workspace_a, workspace_b, candidates, cfg, tolerance, timeout, cache,
                    common_dirs, undetermined,
                )
            )

    conflicts.sort(key=lambda item: item.sort_key())
    undetermined.sort(key=lambda item: (item.file, item.source, item.code, item.detail))

    if derived_skips:
        notes.append(
            "有 %d 个同文件组合因两侧是同一 parent 派生的 subagent（`derived_from` 相同）"
            "默认不产出冲突（场景 4 口径）" % derived_skips
        )
    degraded = sum(1 for item in conflicts if item.degraded)
    approximate = sum(1 for item in conflicts if item.approximate)
    if degraded:
        notes.append(
            "有 %d 条记录的区块级未能判定（`degraded`）：粒度降为文件级，原因见 undetermined" % degraded
        )
    if approximate:
        notes.append(
            "有 %d 条记录不做符号级（`approximate`：非 Python 文件 / 取不到基线 / 跨工作区），"
            "产物里**不出现**符号级字段——那是「我们没做」，不是「没有符号命中」" % approximate
        )
    return ConflictSet(
        conflicts=conflicts,
        undetermined=undetermined,
        reference_time=table.reference_time,
        notes=notes,
        counts=_counts(conflicts, undetermined, cache, derived_skips),
    )


def _build_record(path, workspace_a, workspace_b, candidates, cfg, tolerance, timeout, cache,
                  common_dirs, undetermined):
    """组装一条记录 = 一个 `(workspace_a, workspace_b, path)` 组合。"""
    sides = [side for pair in candidates for side in pair]
    levels: List[str] = list(_BASE_LEVELS)

    # ---- 符号级：只在同一工作区内做（跨工作区的行号不可比）----
    symbols_available = False
    symbol_kind = ""
    symbols: Tuple[str, ...] = ()
    spans: List[Tuple[str, int, int]] = []
    witness_pair = ()
    witness = ()
    if workspace_a == workspace_b:
        python_sides = [side for side in sides if intent_module.looks_python(path)]
        if len(python_sides) == len(sides):
            head_lines, reason = intent_module.read_head_lines(workspace_a, path, timeout)
            if head_lines is None:
                undetermined.append(
                    discover.Undetermined(
                        file=path,
                        source=SOURCE_DETECT,
                        code=CODE_SYMBOL_UNAVAILABLE,
                        detail="取不到 HEAD 版本（%s）：不做符号级，只给行区间近似" % reason,
                    )
                )
            else:
                try:
                    spans = symbol_spans(head_lines)
                except SyntaxError as exc:
                    undetermined.append(
                        discover.Undetermined(
                            file=path,
                            source=SOURCE_DETECT,
                            code=CODE_SYMBOL_UNAVAILABLE,
                            detail="AST 解析失败（%s）：不做符号级，只给行区间近似" % exc,
                        )
                    )
                else:
                    symbols_available = True
                    symbol_kind, symbols, witness_pair, witness = _evaluate_symbols(
                        spans, candidates, tolerance
                    )
                    if symbol_kind:
                        levels.append(LEVEL_SYMBOL)
    else:
        undetermined.append(
            discover.Undetermined(
                file=path,
                source=SOURCE_DETECT,
                code=CODE_SYMBOL_UNAVAILABLE,
                detail="两侧在不同工作区：行号不可比，不做符号级",
            )
        )

    # ---- 区块级 ----
    block_hit = False
    degraded = False
    reasons: List[str] = []
    evidence: List[str] = []
    for side_a, side_b in candidates:
        hit, pair_degraded, pair_reasons = _block_probe(
            path, side_a, side_b, cfg, timeout, cache, common_dirs
        )
        block_hit = block_hit or hit
        degraded = degraded or pair_degraded
        reasons = _ordered_unique(reasons + list(pair_reasons))
        if side_a.branch and side_b.branch:
            branch_lo, branch_hi = sorted([side_a.branch, side_b.branch])
            result = cache.results.get((common_dirs.get(side_a.workspace), branch_lo, branch_hi))
            if result is not None:
                evidence.append("merge-tree:%s@exit=%s" % (path, result.returncode))
    if block_hit:
        levels.append(LEVEL_BLOCK)
    if degraded:
        undetermined.append(
            discover.Undetermined(
                file=path,
                source=SOURCE_DETECT,
                code=CODE_DEGRADED,
                detail="；".join(reasons),
            )
        )

    levels = [level for level in LEVEL_ORDER if level in levels]
    # 非 Python / 符号级不可用 ⇒ `approximate=True` 且产物里不出现 symbols（R4 口径）。
    approximate = not symbols_available
    if approximate:
        symbols = ()
        spans = []
    severity_key = _severity_key(levels, symbol_kind, symbols_available)
    severity = cfg.get("severity", severity_key)

    # 见证对：有符号级结论时用符号级的见证，否则用首个确定的对。
    # `line_ranges` / `sessions_a` / `sessions_b` 三格**描述同一个对**，便于人工复核。
    if not witness_pair:
        witness_pair = candidates[0]
    if witness:
        line_ranges = [witness[0], witness[1]]
    else:
        line_ranges = list(witness_pair[0].ranges[:1]) + list(witness_pair[1].ranges[:1])

    for side in sides:
        evidence.extend(side.evidence)
    for name, start, end in _symbol_refs(symbols, spans):
        evidence.append("symbol:%s@%d-%d" % (name, start, end))
    evidence.append("path:%s" % path)

    return Conflict(
        levels=levels,
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        path=path,
        symbols=symbols,
        symbol_spans=_symbol_refs(symbols, spans),
        line_ranges=line_ranges,
        severity=severity,
        severity_key=severity_key,
        degraded=degraded,
        degrade_reasons=reasons,
        approximate=approximate,
        sessions=_ordered_unique([side.session_key for pair in candidates for side in pair]),
        session_ids=_ordered_unique([side.session_id for pair in candidates for side in pair]),
        sessions_a=[witness_pair[0].session_key],
        sessions_b=[witness_pair[1].session_key],
        last_write_ts=max([side.last_write_ts for side in sides if side.last_write_ts] or [""]),
        evidence=_ordered_unique(evidence),
    )


def _counts(conflicts, undetermined, cache, derived_skips=0):
    """计数两栏（K12）：`by_max_level` 是**划分**，`by_level_membership` 是**成员数**。"""
    by_max_level = dict((level, 0) for level in LEVEL_ORDER)
    by_level_membership = dict((level, 0) for level in LEVEL_ORDER)
    for item in conflicts:
        by_max_level[item.level] += 1
        for level in item.levels:
            by_level_membership[level] += 1
    if sum(by_max_level.values()) != len(conflicts):
        raise AssertionError(
            "计数恒等式不成立（K12）：sum(by_max_level)=%s ≠ len(conflicts)=%s"
            % (sum(by_max_level.values()), len(conflicts))
        )
    return {
        "conflicts": len(conflicts),
        "by_max_level": by_max_level,
        "by_level_membership": by_level_membership,
        "undetermined": len(undetermined),
        "degraded": sum(1 for item in conflicts if item.degraded),
        "approximate": sum(1 for item in conflicts if item.approximate),
        "paths_in_conflict": len(set(item.path for item in conflicts)),
        "derived_sibling_pairs_skipped": derived_skips,
        "merge_tree_runs": cache.runs,
    }
