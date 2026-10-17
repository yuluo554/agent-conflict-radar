"""`bench/` 合成冲突矩阵生成器：场景构造 + 植入真值 + 覆盖度台账 + 两层 `--check`（M1）。

上游：`plan/05-数据计划.md`（§三 白名单 / §4.2 场景→真值映射 / §五 覆盖度 / §六 生成与冻结纪律）、
`plan/07` K9 / K10 / K11、`data/README.md` §6.1 的 `merge-tree` 实测形态。

命令形态（`plan/05` §六）：

    py -X utf8 -m agent_conflict_radar.bench.gen --out bench        # 重建冻结产物
    py -X utf8 -m agent_conflict_radar.bench.gen --check            # 两层断言（CI 每棒必跑）
    py -X utf8 -m agent_conflict_radar.bench.gen --materialize <id> --dest <dir>

---
## 四条容易踩空的设计决定（写在这里，省下一位读者的推导）

1. **`.git` 不进冻结产物**：冻结的是 `repo/`（纯文本基线）、`sessions/`、`truth.json`、
   `manifest.json`。理由：`.git` 内部字节取决于 zlib/git 版本与随机化临时名，跨平台**不可能**
   逐字节重现；把它纳入"逐字节比对"会让 CI 四腿同点全红（假红的典型来源）。
   提交的可复现性改用**更强的判据**：提交 sha 记进真值，`--check` 重新物化并复算 sha——
   sha 是内容 + 固定元数据的纯函数，跨平台稳定。
2. **冻结产物里不许出现本机绝对路径**（`plan/05` §六"生成物不登记环境依赖事实"）：
   会话日志里的会话根写成占位符 `{{REPO_ROOT}}`，物化时才替换成本机路径。
   否则"在别人电脑上 `--check` 必红"——那不是生成器坏了，是产物里登记了环境事实。
3. **真值不得内嵌策略数值**（K3"禁第二份数值表"）：凡涉及阈值之处（6a/6b 的间距边界）写成
   `{"config_ref": "symbol.adjacent_tolerance", "offset": N}` 的**符号引用**，由 `--check`
   读 `config/radar.toml` 现场求值。于是"改了阈值而真值不动"当场变红。
4. **生成侧与生产侧的规范序各一份独立实现**（K10）：本文件的 `_dump_json` **不 import**
   `serialize.dumps_json`；两者一致性由逐字节测试断言（`tests/test_bench_matrix.py`）。
   顺手统一成一个 import，会让"两份契约漂移"永远测不出来。

## 与"只读纪律"的边界（K4）

K4 约束的是**分析路径**：不得对用户的仓库执行 merge/rebase/写索引。生成器要造的仓库是
**它自己临时目录里的合成仓库**，因此这里直接调 `git init/add/commit/checkout`，**不经过**
`gitio.run_readonly`（那条白名单会（正确地）拒绝这些子命令）。写明这条，避免读者以为
生成器绕过了 K4。
"""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import load as load_config
from ..paths import find_repo_root
from ..serialize import write_atomic
from . import rng as rng_module

#: 生成器版本（`manifest.json` 的 `generator_version` 从这里取——**不手写第二份**，`plan/05` §五）。
GENERATOR_VERSION = "m1-1"

#: 冻结产物里的会话根占位符（物化时替换为本机路径；见模块文档第 2 条）。
PLACEHOLDER_ROOT = "{{REPO_ROOT}}"

#: 冻结布局（`plan/05` §二）。
SCENARIOS_DIRNAME = "scenarios"
REPO_DIRNAME = "repo"
SESSIONS_DIRNAME = "sessions"
TRUTH_FILENAME = "truth.json"
MANIFEST_FILENAME = "manifest.json"

#: `levels` 的规范序（`plan/07` 决策记录的"一条记录 + 粒度集合"口径）。
LEVEL_ORDER = ("file", "block", "symbol")

#: 白名单假值（K11；`data/README.md` §三）——生成器**只允许**产出这些值。
FAKE_AUTHOR_NAME = "radar-user"
FAKE_AUTHOR_EMAIL = "radar-user@example.invalid"
TIME_BASE_DATE = "2026-01-01"

#: 合成会话里的源标识（与 `versions.py` 的对外取值一致）。
SOURCE_CLAUDE = "claude"
SOURCE_CODEX = "codex"

#: git 提交的固定时间戳（`plan/05` §六"git 提交稳定"）。
_GIT_DATE_BASE = "2026-01-01T00:00:00+00:00"
_GIT_DATE_BRANCH = "2026-01-01T00:01:00+00:00"

#: 覆盖度门槛：每类至少一条 + 集合覆盖（`plan/05` §五）。
MIN_COUNT_BY_TYPE = {
    "same_file_diff_symbol": 1,
    "same_symbol_diff_lines": 1,
    "whole_file_overwrite": 1,
    "subagent_derived": 1,
    "negative_no_overlap": 1,
    "threshold_adjacent": 1,
}

#: 阈值边界必须**成对**出现（`plan/05` §4.2 的硬要求）：只测"该命中"的用例，阈值写错永远不红。
THRESHOLD_PAIR = {"type": "threshold_adjacent", "hit_case": "threshold_exact", "miss_case": "threshold_near_miss"}

#: 真值里禁止出现的键名（K3：策略数值只有 `config/radar.toml` 一处定义）。
#: 例外：`thresholds_ref` 子树（它的**值**必须是 `config:` 引用，由 `_check_truth_payload` 单独管）。
FORBIDDEN_TRUTH_KEYS = frozenset(
    {
        "adjacent_tolerance",
        "min_overlap_lines",
        "active_minutes",
        "scan_days",
        "max_line_bytes",
        "same_symbol",
        "same_file_diff_symbol",
        "adjacent_lines",
        "file_only",
        "timeout_seconds",
        "merge_tree_enabled",
        "max_evidence_items",
    }
)

#: `thresholds_ref` 子树之外的键路径前缀白名单（见 `FORBIDDEN_TRUTH_KEYS` 的例外）。
_THRESHOLD_REF_PREFIX = "thresholds_ref"

#: 机盘绝对路径的形态（`--check` 用它断言"冻结产物未登记环境事实"）。
_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.])[A-Za-z]:[\\/]")

#: 本机路径片段的**目录名**清单；分隔符在运行时拼。
#: 写成成品片段（`/home/` 这种）会与 K16 门禁"源码里不得出现该片段"直接打架，而那条门禁是对的
#: （它拦的是硬编码路径）。拆成"目录名 + 两种分隔符"后判据反而更全（正斜杠/反斜杠形态都覆盖），
#: 也不必给门禁开例外。
_MACHINE_PATH_DIR_NAMES = ("home", "Users", "AppData")
_PATH_SEPARATORS = ("/", "\\")


def machine_path_markers() -> Tuple[str, ...]:
    """本机路径片段的完整形态（`--check` 扫冻结产物用；`/tmp/` 单独列，它不是用户目录）。"""
    markers = [
        "%s%s%s" % (separator, name, separator)
        for separator in _PATH_SEPARATORS
        for name in _MACHINE_PATH_DIR_NAMES
    ]
    markers.append("/tmp/")
    return tuple(markers)

#: 噪声文件里的反向样例（每个场景都要能指出"这个没被碰过的符号不许被报"）。
_NOISE_FORBIDDEN = {"path": "src/filler.py", "symbol": "noise_0"}


# --------------------------------------------------------------------------------------
# 合成仓库的基线内容（显式逐行写出：行号是几何的一部分，必须肉眼可核对）
# --------------------------------------------------------------------------------------


def _base_alpha_lines() -> List[str]:
    """`src/alpha.py`：`f()` 占 1–10 行、`g()` 占 14–19 行（中间 3 行空行——6a 的临界间距靠它凑）。"""
    return [
        "def f():",
        "    a = 1",
        "    b = 2",
        "    c = 3",
        "    d = 4",
        "    e = 5",
        "    h = 6",
        "    i = 7",
        "    j = 8",
        "    k = 9",
        "",
        "",
        "",
        "def g():",
        "    m = 10",
        "    n = 11",
        "    o = 12",
        "    p = 13",
        "    q = 14",
    ]


def _base_beta_lines() -> List[str]:
    """`src/beta.py`：负样本场景里"另一侧改的文件"（`main()` 1–4 行、`helper()` 7–8 行）。"""
    return [
        "def main():",
        "    value = 1",
        "    total = value + 1",
        "    return total",
        "",
        "",
        "def helper():",
        "    return 0",
    ]


def _filler_lines(seed: int, functions: int) -> List[str]:
    """`src/filler.py`：**噪声文件**——两个会话都不碰它。

    它的存在让负样本更硬：仓库里有一堆无关符号时，检测器仍不得顺手报它们。
    内容由确定性 RNG 产出（非语义、不进真值），这是 `rng.py` 在 M1 的唯一用途。
    """
    stream = rng_module.Rng(seed)
    lines: List[str] = []
    for index in range(functions):
        lines.append("def noise_%d():" % index)
        lines.append("    slot_0 = %d" % stream.below(1000))
        for _step in range(3):
            lines.append("    slot_%d = %d" % (1 + stream.below(40), stream.below(1000)))
        lines.append("    return slot_0")
        lines.append("")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _repo_files() -> Dict[str, List[str]]:
    """合成仓库的基线文件表（冻结产物 `repo/` 的唯一来源）。"""
    return {
        "src/alpha.py": _base_alpha_lines(),
        "src/beta.py": _base_beta_lines(),
        "src/filler.py": _filler_lines(seed=20260101, functions=3),
    }


# --------------------------------------------------------------------------------------
# 场景表
# --------------------------------------------------------------------------------------


class Side(object):
    """一个会话侧：它改了什么、在哪个分支上、是不是 subagent。"""

    __slots__ = ("session_id", "source", "branch", "subagent_of", "edits", "start_minute")

    def __init__(self, session_id, source, branch=None, subagent_of=None, edits=(), start_minute=0):
        self.session_id = session_id
        self.source = source
        self.branch = branch
        self.subagent_of = subagent_of
        self.edits = tuple(edits)
        self.start_minute = start_minute


class Scenario(object):
    """一条场景：构造几何 + 期望（`levels` / `symbols` 集合）+ 覆盖类型 + 依据。"""

    __slots__ = (
        "ident",
        "types",
        "reason",
        "sides",
        "parent",
        "levels_expected",
        "levels_forbidden",
        "symbols_expected",
        "objects_forbidden",
        "git_expected_merge_exit",
        "gap_rule",
        "notes",
    )

    def __init__(
        self,
        ident,
        types,
        reason,
        sides,
        levels_expected,
        levels_forbidden,
        symbols_expected,
        objects_forbidden,
        git_expected_merge_exit,
        notes,
        parent=None,
        gap_rule=None,
    ):
        self.ident = ident
        self.types = tuple(types)
        self.reason = reason
        self.sides = tuple(sides)
        self.parent = parent
        self.levels_expected = tuple(levels_expected)
        self.levels_forbidden = tuple(levels_forbidden)
        self.symbols_expected = tuple(symbols_expected)
        self.objects_forbidden = tuple(objects_forbidden)
        self.git_expected_merge_exit = git_expected_merge_exit
        #: 构造间距与阈值的关系（**符号引用 config**，不写死数值）。`--check` 现场对 config 求值。
        self.gap_rule = gap_rule
        self.notes = notes


def _rule(op, config_key=None, offset=0, const=None):
    """构造一条间距关系：右端要么是 config 引用（+偏移），要么是构造常量。"""
    if config_key is not None:
        return {"lhs": "gap_lines", "op": op, "rhs": {"config_ref": "config:" + config_key, "offset": offset}}
    return {"lhs": "gap_lines", "op": op, "rhs": {"const": const}}


def _edit(path, line_start, line_end, new_lines):
    return {"kind": "edit", "path": path, "line_start": line_start, "line_end": line_end, "new_lines": tuple(new_lines)}


def _write(path, changed_start, changed_end, content_lines):
    return {
        "kind": "write",
        "path": path,
        "line_start": changed_start,
        "line_end": changed_end,
        "content_lines": tuple(content_lines),
    }


def _scenarios() -> Tuple[Scenario, ...]:
    """七条场景，逐条对应 `plan/05` §4.2 的场景 1 / 2 / 3 / 4 / 5 / 6a / 6b。

    行号一律相对 `repo/` 根、1-based 闭区间；**声明即校验**（生成时用 ast 复核"改动落在所声明的符号内"，
    再用逐行比对复核"声明的区间 == 实测的有效改动区间"）。
    """
    alpha = "src/alpha.py"
    beta = "src/beta.py"

    # 场景 3 的 A 侧：整文件 Write。相对基线只改了第 2 行——"整文件覆盖"的**有效改动**就是这一行。
    overwrite_content = list(_base_alpha_lines())
    overwrite_content[1] = "    a = 100"

    return (
        Scenario(
            ident="same_file_diff_symbol",
            types=("same_file_diff_symbol",),
            reason="different_symbol_not_adjacent",
            sides=(
                Side("sess-radar-0001", SOURCE_CLAUDE, "feat/agent-a", edits=(_edit(alpha, 2, 2, ["    a = 101"]),)),
                Side("sess-radar-0002", SOURCE_CLAUDE, "feat/agent-b", edits=(_edit(alpha, 19, 19, ["    q = 114"]),)),
            ),
            levels_expected=("file",),
            levels_forbidden=("block", "symbol"),
            symbols_expected=(),
            objects_forbidden=(
                {"path": alpha, "symbol": "f"},
                {"path": alpha, "symbol": "g"},
                dict(_NOISE_FORBIDDEN),
            ),
            git_expected_merge_exit=0,
            gap_rule=_rule("gt", config_key="symbol.adjacent_tolerance"),
            notes="两侧各改一个不同符号（f 与 g），间距远大于相邻容差：git 自动合并成功（exit 0），"
            "故区块级不得报；符号级也不得报（既不是同一符号、也不相邻）。",
        ),
        Scenario(
            ident="same_symbol_diff_lines",
            types=("same_symbol_diff_lines",),
            reason="same_symbol",
            sides=(
                Side("sess-radar-0003", SOURCE_CLAUDE, "feat/agent-a", edits=(_edit(alpha, 2, 2, ["    a = 301"]),)),
                Side("sess-radar-0004", SOURCE_CLAUDE, "feat/agent-b", edits=(_edit(alpha, 9, 9, ["    j = 308"]),)),
            ),
            levels_expected=("file", "symbol"),
            levels_forbidden=("block",),
            symbols_expected=("f",),
            objects_forbidden=({"path": alpha, "symbol": "g"}, dict(_NOISE_FORBIDDEN)),
            git_expected_merge_exit=0,
            gap_rule=_rule("ge", const=4),
            notes="同一函数 f() 的首段与尾段（相隔 6 行）：git 自动合并成功（exit 0）——**这正是符号级的"
            "价值窗口**：git 说没问题，我们报同一符号。",
        ),
        Scenario(
            ident="whole_file_overwrite",
            types=("whole_file_overwrite",),
            reason="same_symbol_and_block_conflict",
            sides=(
                Side(
                    "sess-radar-0005",
                    SOURCE_CLAUDE,
                    "feat/agent-a",
                    edits=(_write(alpha, 2, 2, overwrite_content),),
                ),
                Side("sess-radar-0006", SOURCE_CLAUDE, "feat/agent-b", edits=(_edit(alpha, 2, 2, ["    a = 7"]),)),
            ),
            levels_expected=("file", "block", "symbol"),
            levels_forbidden=(),
            symbols_expected=("f",),
            objects_forbidden=({"path": alpha, "symbol": "g"}, dict(_NOISE_FORBIDDEN)),
            git_expected_merge_exit=1,
            notes="一侧整文件 Write（有效改动落在第 2 行）、另一侧局部 Edit 同一行：git 试合并 exit 1，"
            "区块级必须报；被覆盖的符号是 f（g 的内容逐行未变，故不得报 g）。",
        ),
        Scenario(
            ident="subagent_derived",
            types=("subagent_derived",),
            reason="same_parent_derived_no_cross_agent",
            parent={"session_id": "sess-radar-0007", "source": SOURCE_CODEX},
            sides=(
                Side(
                    "sess-radar-0008",
                    SOURCE_CODEX,
                    "feat/agent-a",
                    subagent_of="sess-radar-0007",
                    edits=(_edit(alpha, 2, 2, ["    a = 801"]),),
                ),
                Side(
                    "sess-radar-0009",
                    SOURCE_CODEX,
                    "feat/agent-b",
                    subagent_of="sess-radar-0007",
                    edits=(_edit(alpha, 9, 9, ["    j = 809"]),),
                ),
            ),
            levels_expected=(),
            levels_forbidden=("file", "block", "symbol"),
            symbols_expected=(),
            objects_forbidden=({"path": alpha, "symbol": "f"}, dict(_NOISE_FORBIDDEN)),
            git_expected_merge_exit=0,
            gap_rule=_rule("ge", const=4),
            notes="几何与场景 2 相同（同文件、同一函数、间距 6），但两侧是**同一 parent 派生的 subagent**"
            "→ 默认不构成跨 agent 并行，一条都不报。派生关系必须由 derived_from 认定（读 parent_thread_id），"
            "不是靠几何猜出来的。",
        ),
        Scenario(
            ident="negative_no_overlap",
            types=("negative_no_overlap",),
            reason="different_files",
            sides=(
                Side("sess-radar-0010", SOURCE_CLAUDE, "feat/agent-a", edits=(_edit(alpha, 2, 2, ["    a = 1001"]),)),
                Side("sess-radar-0011", SOURCE_CODEX, "feat/agent-b", edits=(_edit(beta, 3, 3, ["    total = value + 11"]),)),
            ),
            levels_expected=(),
            levels_forbidden=("file", "block", "symbol"),
            symbols_expected=(),
            objects_forbidden=(
                {"path": alpha, "symbol": "f"},
                {"path": beta, "symbol": "main"},
                dict(_NOISE_FORBIDDEN),
            ),
            git_expected_merge_exit=0,
            notes="两侧改完全不同的文件（alpha.py / beta.py）→ 空检出，这是防误报的主力用例；"
            "仓库里还有 rng 生成的 filler.py 噪声，检测器不得顺手报它。",
        ),
        Scenario(
            ident="threshold_exact",
            types=("threshold_adjacent",),
            reason="adjacent_range_within_tolerance",
            sides=(
                Side("sess-radar-0012", SOURCE_CLAUDE, "feat/agent-a", edits=(_edit(alpha, 10, 10, ["    k = 1201"]),)),
                Side("sess-radar-0013", SOURCE_CLAUDE, "feat/agent-b", edits=(_edit(alpha, 14, 14, ["def g():  # touched"]),)),
            ),
            levels_expected=("file", "symbol"),
            levels_forbidden=("block",),
            symbols_expected=("f", "g"),
            objects_forbidden=(dict(_NOISE_FORBIDDEN),),
            git_expected_merge_exit=0,
            gap_rule=_rule("eq", config_key="symbol.adjacent_tolerance"),
            notes="两侧落在**不同符号**（f 的末行 / g 的首行），间距恰好等于 `symbol.adjacent_tolerance`"
            "→ 按 `<=` 语义命中相邻符号（符号级报两侧符号）。间距值不在真值里写死，改成引用 config。",
        ),
        Scenario(
            ident="threshold_near_miss",
            types=("threshold_adjacent",),
            reason="adjacent_range_beyond_tolerance",
            sides=(
                Side("sess-radar-0014", SOURCE_CLAUDE, "feat/agent-a", edits=(_edit(alpha, 10, 10, ["    k = 1401"]),)),
                Side("sess-radar-0015", SOURCE_CLAUDE, "feat/agent-b", edits=(_edit(alpha, 15, 15, ["    m = 1402"]),)),
            ),
            levels_expected=("file",),
            levels_forbidden=("block", "symbol"),
            symbols_expected=(),
            objects_forbidden=(
                {"path": alpha, "symbol": "f"},
                {"path": alpha, "symbol": "g"},
                dict(_NOISE_FORBIDDEN),
            ),
            git_expected_merge_exit=0,
            gap_rule=_rule("eq", config_key="symbol.adjacent_tolerance", offset=1),
            notes="与 `threshold_exact` 成对：间距 = 容差 + 1 → **不命中**相邻符号，只报文件级。"
            "没有这一条，阈值的下边界从未被测过（写错永远不红）。",
        ),
    )


def scenario_ids() -> Tuple[str, ...]:
    return tuple(scenario.ident for scenario in _scenarios())


def scenario_by_id(ident: str) -> Scenario:
    for scenario in _scenarios():
        if scenario.ident == ident:
            return scenario
    raise KeyError("未知场景 id：%r（已知：%s）" % (ident, list(scenario_ids())))


# --------------------------------------------------------------------------------------
# 序列化（**生成侧独立实现**，K10）
# --------------------------------------------------------------------------------------


def _dump_json(payload: Any) -> str:
    """冻结契约的生成侧独立实现：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行。

    故意不 import `serialize.dumps_json`（K10）：两份实现的一致性由逐字节测试断言。
    """
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def _dump_jsonl_line(payload: Any) -> str:
    """JSONL 的一行：紧凑、键序固定、不带行尾换行（换行由写盘层统一加）。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------------------
# 行区间工具
# --------------------------------------------------------------------------------------


def _symbol_ranges(lines: Sequence[str]) -> Dict[str, Tuple[int, int]]:
    """用 `ast` 取顶层函数/类的行区间（1-based 闭区间）。取不到就取不到，**不做符号级近似**。"""
    tree = ast.parse("\n".join(lines) + "\n")
    ranges: Dict[str, Tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ranges[node.name] = (node.lineno, node.end_lineno)
    return ranges


def _changed_range(base_lines: Sequence[str], candidate_lines: Sequence[str]) -> Tuple[int, int]:
    """逐行比对求**有效改动区间**（1-based 闭区间）；不连续改动一律报错（几何必须是单块）。"""
    if len(base_lines) != len(candidate_lines):
        raise AssertionError("行数变了：几何会漂移（edit 的替换必须等行数，write 必须整文件等长）")
    changed = [index + 1 for index, (before, after) in enumerate(zip(base_lines, candidate_lines)) if before != after]
    if not changed:
        raise AssertionError("该改动与基线逐行相同：它不构成任何改动，真值会变成空断言")
    if changed != list(range(changed[0], changed[-1] + 1)):
        raise AssertionError("改动行不连续（%s）：真值里的 changed 区间会骗人" % changed)
    return changed[0], changed[-1]


def _side_result(side: Side, repo_files: Dict[str, List[str]]):
    """把一侧的改动渲染成"每文件的最终全文 + 有效改动区间"。**声明即校验**。"""
    results = []
    for edit in side.edits:
        path = edit["path"]
        base_lines = list(repo_files[path])
        if edit["kind"] == "edit":
            start, end = edit["line_start"], edit["line_end"]
            new_lines = list(edit["new_lines"])
            if len(new_lines) != end - start + 1:
                raise AssertionError("edit 的替换行数与声明区间不等长：%s %r" % (side.session_id, edit))
            result_lines = base_lines[: start - 1] + new_lines + base_lines[end:]
        elif edit["kind"] == "write":
            result_lines = list(edit["content_lines"])
            if len(result_lines) != len(base_lines):
                raise AssertionError("write 的整文件内容与基线行数不等长：%s" % (side.session_id,))
        else:
            raise AssertionError("未知改动类别：%r" % (edit["kind"],))
        changed_start, changed_end = _changed_range(base_lines, result_lines)
        if (changed_start, changed_end) != (edit["line_start"], edit["line_end"]):
            raise AssertionError(
                "声明的改动区间 %r 与实测 %r 不符：真值的几何必须与内容一致"
                % ((edit["line_start"], edit["line_end"]), (changed_start, changed_end))
            )
        results.append(
            {
                "path": path,
                "kind": edit["kind"],
                "base_lines": base_lines,
                "result_lines": result_lines,
                "changed_start": changed_start,
                "changed_end": changed_end,
                "old_lines": base_lines[changed_start - 1 : changed_end],
                "new_lines": result_lines[changed_start - 1 : changed_end],
            }
        )
    return results


# --------------------------------------------------------------------------------------
# 会话日志渲染
# --------------------------------------------------------------------------------------


def _stamp(minute: int) -> str:
    """`2026-01-01T00:MM:00Z`——固定基准 + 确定偏移（K11）。"""
    hours, minutes = divmod(minute, 60)
    return "%sT%02d:%02d:00Z" % (TIME_BASE_DATE, hours, minutes)


def _claude_lines(side: Side, results, root: str) -> List[Dict[str, Any]]:
    """仿 Claude Code 会话行。

    **首行刻意不是消息行**（实测 58/125 是 `last-prompt`）：解析器若只看首行，就会把这份文件
    判成"没有消息行"——这正是 M1 只读探针推翻 M0 猜测的那一条，必须能被测试打中。
    """
    base = side.start_minute
    common = {
        "sessionId": side.session_id,
        "cwd": root,
        "gitBranch": side.branch or "",
        "isSidechain": side.subagent_of is not None,
    }
    lines: List[Dict[str, Any]] = []
    head = dict(common)
    head.update({"type": "last-prompt", "uuid": "%s-lp" % side.session_id, "timestamp": _stamp(base)})
    lines.append(head)

    minute = base + 1
    for index, result in enumerate(results):
        file_path = "%s/%s" % (root, result["path"])
        if result["kind"] == "write":
            tool_name = "Write"
            tool_input = {"file_path": file_path, "content": "\n".join(result["result_lines"]) + "\n"}
        else:
            tool_name = "Edit"
            tool_input = {
                "file_path": file_path,
                "old_string": "\n".join(result["old_lines"]),
                "new_string": "\n".join(result["new_lines"]),
                "replace_all": False,
            }
        record = dict(common)
        record.update(
            {
                "type": "assistant",
                "uuid": "%s-msg-%d" % (side.session_id, index),
                "timestamp": _stamp(minute),
                "message": {
                    "id": "msg-%s-%d" % (side.session_id, index),
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu-%s-%d" % (side.session_id, index),
                            "name": tool_name,
                            "input": tool_input,
                        }
                    ],
                },
            }
        )
        lines.append(record)
        minute += 1

    tail = dict(common)
    tail.update({"type": "queue-operation", "uuid": "%s-qo" % side.session_id, "timestamp": _stamp(base + 5)})
    lines.append(tail)
    return lines


def _apply_patch_text(root: str, results) -> str:
    """Codex 侧 `apply_patch` 的**字符串**载荷（R2 实测形态：以 `*** Begin Patch` 开头）。"""
    chunks = ["*** Begin Patch"]
    for result in results:
        chunks.append("*** Update File: %s/%s" % (root, result["path"]))
        chunks.append("@@")
        for line in result["old_lines"]:
            chunks.append("-%s" % line)
        for line in result["new_lines"]:
            chunks.append("+%s" % line)
    chunks.append("*** End Patch")
    chunks.append("")
    return "\n".join(chunks)


def _codex_lines(side: Side, results, root: str) -> List[Dict[str, Any]]:
    """仿 Codex 会话行：首行恒为 `session_meta`（实测 220/220）。"""
    base = side.start_minute
    payload = {
        "id": side.session_id,
        "timestamp": _stamp(base),
        "cwd": root,
        "originator": "codex_cli",
        "cli_version": "0.0.0-synthetic",
        "thread_source": "user",
    }
    if side.subagent_of is None:
        # 实测：`session_id` 只有主会话有（63/220）；子会话靠 `id`。
        payload["session_id"] = side.session_id
    else:
        payload["parent_thread_id"] = side.subagent_of
        payload["agent_nickname"] = "subagent-%s" % side.session_id[-4:]

    lines: List[Dict[str, Any]] = [{"timestamp": _stamp(base), "type": "session_meta", "payload": payload}]
    minute = base + 1
    if results:
        lines.append(
            {
                "timestamp": _stamp(minute),
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "input": _apply_patch_text(root, results),
                },
            }
        )
        minute += 1
    lines.append({"timestamp": _stamp(minute), "type": "event_msg", "payload": {"type": "token_count"}})
    return lines


def _render_session_texts(scenario: Scenario, root: str) -> Dict[str, str]:
    """渲染某场景的全部会话文件：{相对 `sessions/` 的 posix 路径: 文本}。

    `root` 既可以是占位符（冻结）也可以是本机路径（物化）——同一段代码，两种根。
    """
    repo_files = _repo_files()
    texts: Dict[str, str] = {}
    if scenario.parent is not None:
        parent = Side(scenario.parent["session_id"], scenario.parent["source"], None, edits=(), start_minute=0)
        rendered = _codex_lines(parent, [], root)
        texts["%s/%s.jsonl" % (parent.source, parent.session_id)] = _join_jsonl(rendered)
    for side in scenario.sides:
        results = _side_result(side, repo_files)
        rendered = _claude_lines(side, results, root) if side.source == SOURCE_CLAUDE else _codex_lines(side, results, root)
        texts["%s/%s.jsonl" % (side.source, side.session_id)] = _join_jsonl(rendered)
    return texts


def _join_jsonl(records) -> str:
    return "".join(_dump_jsonl_line(record) + "\n" for record in records)


def session_roots(scenario: Scenario) -> Tuple[str, ...]:
    """该场景出现的会话源目录名（物化与 `--check` 共用）。"""
    sources = {side.source for side in scenario.sides}
    if scenario.parent is not None:
        sources.add(scenario.parent["source"])
    return tuple(sorted(sources))


# --------------------------------------------------------------------------------------
# 真值
# --------------------------------------------------------------------------------------


def build_truth(scenario: Scenario, repo_paths: Dict[str, Any], repo_shas: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构造植入真值（`plan/05` §4.1）：**只存输入与期望**，禁 `observed_*`。

    `geometry` 让期望值可由输入**独立复算**：符号区间来自 `repo/` 原文的 ast，改动区间来自
    会话声明，间距与阈值的关系写成对 config 的**符号引用**（不复制数值）。
    """
    repo_files = _repo_files()
    sides_geometry: List[Dict[str, Any]] = []
    involved_files: List[str] = []
    for side in scenario.sides:
        for result in _side_result(side, repo_files):
            path = result["path"]
            if path not in involved_files:
                involved_files.append(path)
            symbols = _symbol_ranges(repo_files[path])
            containing = None
            for name in sorted(symbols):
                start, end = symbols[name]
                if start <= result["changed_start"] and result["changed_end"] <= end:
                    containing = name
                    break
            if containing is None:
                raise AssertionError(
                    "场景 %s 的改动区间 [%d,%d] 不落在任何符号内：这条场景需要符号级判据"
                    % (scenario.ident, result["changed_start"], result["changed_end"])
                )
            sides_geometry.append(
                {
                    "session": side.session_id,
                    "path": path,
                    "kind": result["kind"],
                    "changed": [result["changed_start"], result["changed_end"]],
                    "symbol": containing,
                }
            )

    symbols_expected = list(scenario.symbols_expected)
    if symbols_expected:
        objects_expected = [{"path": involved_files[0], "symbol": name} for name in symbols_expected]
    elif scenario.levels_expected:
        objects_expected = [{"path": involved_files[0], "symbol": None}]
    else:
        objects_expected = []

    return {
        "scenario": scenario.ident,
        "types": sorted(scenario.types),
        "reason": scenario.reason,
        "levels_expected": sorted(scenario.levels_expected, key=LEVEL_ORDER.index),
        "levels_forbidden": sorted(scenario.levels_forbidden, key=LEVEL_ORDER.index),
        "symbols_expected": symbols_expected,
        "symbols_forbidden": sorted({item["symbol"] for item in scenario.objects_forbidden if item.get("symbol")}),
        "objects_expected": objects_expected,
        "objects_forbidden": [dict(item) for item in scenario.objects_forbidden],
        "sessions": sorted(
            [side.session_id for side in scenario.sides] + ([scenario.parent["session_id"]] if scenario.parent else [])
        ),
        "git_expected_merge_exit": scenario.git_expected_merge_exit,
        "thresholds_ref": {
            "adjacent_tolerance": "config:symbol.adjacent_tolerance",
            "min_overlap_lines": "config:symbol.min_overlap_lines",
            "note": "阈值一律**引用** config，不在真值里复制数值（K3：禁第二份数值表）。",
        },
        "geometry": {
            "coord": "1-based 闭区间行号（相对 repo/ 根）；changed = 有效改动区间（与基线逐行比对得出）",
            "symbols": {
                path: {name: list(span) for name, span in sorted(_symbol_ranges(repo_files[path]).items())}
                for path in involved_files
            },
            "sides": sides_geometry,
            "pair": _pair_geometry(scenario, sides_geometry),
            "recompute": (
                "把检测引擎注释掉也能算出期望：读 repo/ 原文用 ast 取符号区间 → 两个 changed 区间是否同符号、"
                "间距是否 <= config:symbol.adjacent_tolerance → block 级看 git_expected_merge_exit → "
                "若 pair.derived_same_parent 为真则整对不出记录。"
            ),
        },
        "repo_paths": repo_paths,
        "repo_shas": repo_shas or {},
        "notes": scenario.notes,
    }


def _pair_geometry(scenario: Scenario, sides_geometry) -> Dict[str, Any]:
    """两个改动侧的成对几何：同文件 / 符号关系 / 间距 / 交集 / 是否同一 parent 派生。"""
    derived = any(side.subagent_of is not None for side in scenario.sides)
    if len(sides_geometry) != 2:
        return {"same_file": False, "symbol_relation": "unknown", "gap_lines": None, "overlap_lines": 0,
                "derived_same_parent": derived, "gap_rule": None}
    first, second = sides_geometry[0], sides_geometry[1]
    if first["path"] != second["path"]:
        return {"same_file": False, "symbol_relation": "cross_file", "gap_lines": None, "overlap_lines": 0,
                "derived_same_parent": derived, "gap_rule": None}
    low, high = sorted([first["changed"], second["changed"]], key=lambda item: item[0])
    return {
        "same_file": True,
        "symbol_relation": "same" if first["symbol"] == second["symbol"] else "different",
        #: 负值表示两区间重叠（= `overlap_lines` 的反面），见 `coord` 的说明。
        "gap_lines": high[0] - low[1] - 1,
        "overlap_lines": max(0, min(low[1], high[1]) - max(low[0], high[0]) + 1),
        "derived_same_parent": derived,
        # 构造间距与阈值的关系由场景**声明**（不在这里"按当前 config 反推"）：
        # 反推会让真值随 config 自动漂移，边界语义就再也测不出来了。
        "gap_rule": dict(scenario.gap_rule) if scenario.gap_rule else None,
    }


# --------------------------------------------------------------------------------------
# 冻结产物
# --------------------------------------------------------------------------------------


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_file_texts() -> Dict[str, str]:
    return {path: "\n".join(lines) + "\n" for path, lines in sorted(_repo_files().items())}


def _build_scenario_artifacts(scenario: Scenario) -> Dict[str, str]:
    """某场景的全部冻结文本（相对 `<bench>/scenarios/<id>/` 的 posix 路径 → 文本）。"""
    artifacts: Dict[str, str] = {}
    for path, text in _repo_file_texts().items():
        artifacts["%s/%s" % (REPO_DIRNAME, path)] = text
    for path, text in _render_session_texts(scenario, PLACEHOLDER_ROOT).items():
        artifacts["%s/%s" % (SESSIONS_DIRNAME, path)] = text
    return artifacts


def build_manifest(scenario_entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """覆盖度台账（`plan/05` §五）：每类最低条数 + **集合覆盖** + 显式 `missing_types`。"""
    count_by_type: Dict[str, int] = {}
    for entry in scenario_entries:
        for type_name in entry["types"]:
            count_by_type[type_name] = count_by_type.get(type_name, 0) + 1
    missing_types = sorted(
        name for name in MIN_COUNT_BY_TYPE if count_by_type.get(name, 0) < MIN_COUNT_BY_TYPE[name]
    )
    return {
        "generator_version": GENERATOR_VERSION,
        "coverage": {
            "min_count_by_type": dict(MIN_COUNT_BY_TYPE),
            "count_by_type": count_by_type,
            "missing_types": missing_types,
            "counting_unit": "用例条目数（一个 case 一条），不是命中记录数（K12 的口径声明）",
            "sampling_notice": "抽样覆盖非穷举：本矩阵声明的是「每类至少一条 + 集合覆盖」，不是穷举所有几何。",
            "threshold_pair": dict(THRESHOLD_PAIR),
        },
        "scenarios": list(scenario_entries),
    }


def write_frozen(dest: str) -> Dict[str, Any]:
    """把整棵冻结树写到 `dest`（`--out`）。

    先建到临时目录再落 `dest`：中途失败不会留下半棵树。落盘前会清掉 `dest` 下**我们自己的**
    `scenarios/` 与 `manifest.json`（只动这两处，绝不碰其他文件），避免陈旧产物混进新树。
    """
    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    staging = tempfile.mkdtemp(prefix="radar-bench-staging-")
    work = tempfile.mkdtemp(prefix="radar-bench-work-")
    try:
        scenario_entries = []
        for scenario in _scenarios():
            sdir = os.path.join(staging, SCENARIOS_DIRNAME, scenario.ident)
            for rel, text in _build_scenario_artifacts(scenario).items():
                _write_text(os.path.join(sdir, rel), text)
            repo_shas = materialize_scenario(scenario, os.path.join(work, scenario.ident))
            truth = build_truth(
                scenario,
                {
                    "repo": "%s/%s/%s" % (SCENARIOS_DIRNAME, scenario.ident, REPO_DIRNAME),
                    "sessions": "%s/%s/%s" % (SCENARIOS_DIRNAME, scenario.ident, SESSIONS_DIRNAME),
                    "session_roots": list(session_roots(scenario)),
                    "placeholder_root": PLACEHOLDER_ROOT,
                },
                repo_shas,
            )
            truth_text = _dump_json(truth)
            _write_text(os.path.join(sdir, TRUTH_FILENAME), truth_text)
            scenario_entries.append(
                {
                    "id": scenario.ident,
                    "types": sorted(scenario.types),
                    "reason": scenario.reason,
                    "sessions": truth["sessions"],
                    "cases": [{"case_id": scenario.ident, "truth_sha256": _sha256_text(truth_text)}],
                    "truth_sha256": _sha256_text(truth_text),
                    "repo_shas": repo_shas,
                }
            )
        manifest = build_manifest(scenario_entries)
        _write_text(os.path.join(staging, MANIFEST_FILENAME), _dump_json(manifest))

        if os.path.isdir(dest):
            _clear_own_products(dest)
        else:
            os.makedirs(dest)
        _overlay(staging, dest)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def _write_text(path: str, text: str) -> str:
    """写盘一律经 `serialize.write_atomic`（K2 的唯一写盘点）。父目录由这里先建。"""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    return str(write_atomic(path, text))


def _clear_own_products(dest: str) -> None:
    """只清 `scenarios/` 与 `manifest.json`——生成器的产物面，其他文件一律不动。"""
    scenarios_root = os.path.join(dest, SCENARIOS_DIRNAME)
    if os.path.isdir(scenarios_root):
        shutil.rmtree(scenarios_root)
    manifest_path = os.path.join(dest, MANIFEST_FILENAME)
    if os.path.isfile(manifest_path):
        os.remove(manifest_path)


def _overlay(source: str, dest: str) -> None:
    for root, dirnames, filenames in os.walk(source):
        dirnames.sort()
        rel = os.path.relpath(root, source)
        target_root = dest if rel == "." else os.path.join(dest, rel)
        if not os.path.isdir(target_root):
            os.makedirs(target_root)
        for filename in sorted(filenames):
            shutil.copyfile(os.path.join(root, filename), os.path.join(target_root, filename))


# --------------------------------------------------------------------------------------
# 物化（真 git 仓库 + 真会话目录；M2/M3 与测试用）
# --------------------------------------------------------------------------------------


def _git_env() -> Dict[str, str]:
    """git 子进程环境：关掉一切会随机器变化或带副作用的开关。"""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # 用户的 ~/.gitconfig 可能带 gpgsign / autocrlf / 别名 —— 一律隔离，
    # 否则"提交 sha 可复算"这条守门会依赖"跑它的人是谁"。
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["LC_ALL"] = "C"
    return env


#: git 的固定配置（`-c` 传参，不写进仓库 config——config 文件里会带平台事实）。
_GIT_CONSTANTS = (
    "-c", "core.autocrlf=false",
    "-c", "core.safecrlf=false",
    "-c", "core.filemode=false",
    "-c", "commit.gpgsign=false",
    "-c", "init.defaultBranch=main",
    "-c", "user.name=" + FAKE_AUTHOR_NAME,
    "-c", "user.email=" + FAKE_AUTHOR_EMAIL,
)


def _run_git(args: Sequence[str], cwd: str, extra_env: Optional[Dict[str, str]] = None) -> str:
    env = _git_env()
    if extra_env:
        env.update(extra_env)
    command = ["git"] + list(_GIT_CONSTANTS) + list(args)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # 显式 utf-8：子进程解码不继承 `-X utf8`（K8）。
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise RuntimeError("无法执行 git（生成器需要 git 造合成仓库）：%s" % exc)
    if completed.returncode != 0:
        raise RuntimeError(
            "git %s 失败（rc=%s）：%s" % (" ".join(args), completed.returncode, completed.stderr.strip())
        )
    return completed.stdout


def materialize_scenario(scenario: Scenario, dest: str) -> Dict[str, Any]:
    """把场景物化成 `dest/repo`（真 git 仓库）+ `dest/sessions/<source>/`（真会话日志）。

    返回 `{"base_commit": sha, "branches": {branch: sha}}`——**这是"提交可复算"的判据**：
    sha 只由内容与固定元数据决定，跨平台稳定（见模块文档第 1 条）。
    """
    dest = os.path.abspath(dest)
    repo_dir = os.path.join(dest, REPO_DIRNAME)
    _rmtree(repo_dir)
    os.makedirs(repo_dir)
    repo_files = _repo_files()
    for path, lines in sorted(repo_files.items()):
        _write_text(os.path.join(repo_dir, path), "\n".join(lines) + "\n")

    _run_git(["init", "--quiet"], repo_dir)
    _commit_all(repo_dir, "base: synthetic demo repository", _GIT_DATE_BASE)
    base_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir).strip()
    base_commit = _run_git(["rev-parse", "HEAD"], repo_dir).strip()

    branches: Dict[str, str] = {}
    for side in scenario.sides:
        if not side.branch:
            continue
        _run_git(["checkout", "--quiet", "-b", side.branch, base_branch], repo_dir)
        for result in _side_result(side, repo_files):
            _write_text(os.path.join(repo_dir, result["path"]), "\n".join(result["result_lines"]) + "\n")
        _commit_all(repo_dir, "feat: %s" % side.session_id, _GIT_DATE_BRANCH)
        branches[side.branch] = _run_git(["rev-parse", "HEAD"], repo_dir).strip()
        _run_git(["checkout", "--quiet", base_branch], repo_dir)

    # 会话里的 `{{REPO_ROOT}}` 指向**合成仓库根**（`<dest>/repo`），不是场景目录——
    # 否则 `in_worktree` 永远是 false，"会话 ↔ 工作区匹配"这条通路就从没被真跑过。
    # 用正斜杠形态：JSON 里反斜杠要转义，且 git 自己输出 worktree 路径也用正斜杠。
    root = repo_dir.replace(os.sep, "/")
    for rel, text in _render_session_texts(scenario, root).items():
        _write_text(os.path.join(dest, SESSIONS_DIRNAME, rel), text)

    return {"base_commit": base_commit, "branches": branches}


def _commit_all(repo_dir: str, message: str, iso_date: str) -> None:
    _run_git(["add", "-A"], repo_dir)
    _run_git(
        ["commit", "--quiet", "--no-verify", "-m", message],
        repo_dir,
        {"GIT_AUTHOR_DATE": iso_date, "GIT_COMMITTER_DATE": iso_date},
    )


def merge_tree_exit(repo_dir: str, branch_a: str, branch_b: str) -> int:
    """只读调用 `git merge-tree --write-tree`，返回退出码（0 自动合并成功 / 1 有冲突 / 128 环境问题）。"""
    completed = subprocess.run(
        ["git"] + list(_GIT_CONSTANTS) + ["merge-tree", "--write-tree", branch_a, branch_b],
        cwd=repo_dir,
        env=_git_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode


# --------------------------------------------------------------------------------------
# 两层 `--check`
# --------------------------------------------------------------------------------------


def check(bench_dir: str) -> List[str]:
    """两层断言（K10）+ 提交可复算。返回失败项列表；空列表 = 全过。"""
    bench_dir = os.path.abspath(bench_dir)
    manifest_path = os.path.join(bench_dir, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return ["冻结产物缺失：%s（先跑 --out 重建）" % manifest_path]
    manifest = json.loads(_read_text(manifest_path))

    failures = _check_shape(bench_dir, manifest)

    # ---- 层 2：重跑生成器到临时目录 → 与冻结产物逐字节比对 ----
    staging = tempfile.mkdtemp(prefix="radar-bench-recheck-")
    try:
        write_frozen(staging)
        failures.extend(_compare_trees(os.path.join(staging), bench_dir))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    # ---- 提交可复算 + merge-tree 形态实测 ----
    work = tempfile.mkdtemp(prefix="radar-bench-git-")
    try:
        for scenario in _scenarios():
            truth_path = os.path.join(bench_dir, SCENARIOS_DIRNAME, scenario.ident, TRUTH_FILENAME)
            if not os.path.isfile(truth_path):
                continue
            truth = json.loads(_read_text(truth_path))
            shas = materialize_scenario(scenario, os.path.join(work, scenario.ident))
            if truth.get("repo_shas") != shas:
                failures.append(
                    "场景 %s 的提交 sha 复算不一致：真值 %r ≠ 本次物化 %r（仓库内容或提交元数据漂了）"
                    % (scenario.ident, truth.get("repo_shas"), shas)
                )
            branches = sorted(shas["branches"])
            if len(branches) == 2:
                actual = merge_tree_exit(os.path.join(work, scenario.ident, REPO_DIRNAME), branches[0], branches[1])
                expected = truth.get("git_expected_merge_exit")
                if actual != expected:
                    failures.append(
                        "场景 %s 的 merge-tree 实测 exit=%s ≠ 真值声明 %s：期望值建立在"
                        "「git 会不会自己报冲突」这一事实上，实测不符必须改真值（不许改声明）"
                        % (scenario.ident, actual, expected)
                    )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return failures


def _rmtree(path: str) -> None:
    """删目录树：**先降权再删**。

    Windows 上 git 落的对象文件带只读位，`shutil.rmtree` 会在 `os.unlink` 处直接
    `PermissionError`（本机实测：重跑物化到同一目录时必现）。这里把先权限放开再删，
    免得"第二次物化"这种正常操作变成偶发失败。
    """
    if not os.path.exists(path):
        return
    for root, dirnames, filenames in os.walk(path, topdown=True):
        for target in [root] + [os.path.join(root, name) for name in dirnames + filenames]:
            try:
                os.chmod(target, 0o700)
            except OSError:
                pass
    shutil.rmtree(path)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _check_shape(bench_dir: str, manifest: Dict[str, Any]) -> List[str]:
    """层 1：冻结产物自身形态（真值 schema / 反向样例 / 几何自洽 / 覆盖度 / 无环境事实）。"""
    failures: List[str] = []
    if manifest.get("generator_version") != GENERATOR_VERSION:
        failures.append(
            "manifest.generator_version=%r 与包内常量 %r 不一致（台账被手改过？）"
            % (manifest.get("generator_version"), GENERATOR_VERSION)
        )
    entries = {entry.get("id"): entry for entry in manifest.get("scenarios", [])}
    expected_ids = list(scenario_ids())
    if sorted(entries) != sorted(expected_ids):
        failures.append("manifest 的场景集合与生成器不一致：%s ≠ %s" % (sorted(entries), sorted(expected_ids)))

    coverage = manifest.get("coverage", {})
    count_by_type: Dict[str, int] = {}
    truths: Dict[str, Dict[str, Any]] = {}
    for ident in expected_ids:
        truth_path = os.path.join(bench_dir, SCENARIOS_DIRNAME, ident, TRUTH_FILENAME)
        if not os.path.isfile(truth_path):
            failures.append("场景 %s 缺少真值文件：%s" % (ident, truth_path))
            continue
        text = _read_text(truth_path)
        truth = json.loads(text)
        truths[ident] = truth
        for type_name in truth.get("types", []):
            count_by_type[type_name] = count_by_type.get(type_name, 0) + 1
        entry = entries.get(ident)
        if entry is not None:
            digest = _sha256_text(text)
            if entry.get("truth_sha256") != digest:
                failures.append("场景 %s 的 truth_sha256 与台账不一致（台账禁手改）" % ident)
            cases = entry.get("cases", [])
            if len(cases) != 1 or cases[0].get("truth_sha256") != digest:
                failures.append("场景 %s 的 case 级 sha256 与真值不一致" % ident)
        failures.extend(_check_truth_payload(ident, truth, bench_dir))

    if coverage.get("count_by_type") != count_by_type:
        failures.append(
            "覆盖度计数不一致：台账 %r ≠ 实算 %r（计数口径 = 用例条目数，K12）"
            % (coverage.get("count_by_type"), count_by_type)
        )
    min_counts = coverage.get("min_count_by_type", {})
    short = sorted(name for name, minimum in min_counts.items() if count_by_type.get(name, 0) < minimum)
    if short:
        failures.append("覆盖度不达标（低于每类最低条数）：%s" % short)
    if coverage.get("missing_types") != short:
        failures.append("missing_types 未如实登记：台账 %r ≠ 实算 %r" % (coverage.get("missing_types"), short))

    pair = coverage.get("threshold_pair", {})
    hit_case, miss_case = pair.get("hit_case"), pair.get("miss_case")
    if hit_case not in truths or miss_case not in truths:
        failures.append("阈值边界成对样例缺失：hit=%r miss=%r" % (hit_case, miss_case))
    else:
        if "symbol" not in truths[hit_case].get("levels_expected", []):
            failures.append("阈值成对样例的 hit 侧 %r 未期望符号级命中" % hit_case)
        if "symbol" in truths[miss_case].get("levels_expected", []):
            failures.append("阈值成对样例的 miss 侧 %r 竟期望符号级命中" % miss_case)
        gap_hit = truths[hit_case]["geometry"]["pair"].get("gap_lines")
        gap_miss = truths[miss_case]["geometry"]["pair"].get("gap_lines")
        if gap_hit is None or gap_miss != gap_hit + 1:
            failures.append("阈值成对样例的间距不是相差 1 行（hit=%r miss=%r）：未卡在边界两侧" % (gap_hit, gap_miss))
        if count_by_type.get(pair.get("type"), 0) != 2:
            failures.append("阈值边界类型 %r 必须恰好两条（成对出现）" % pair.get("type"))

    failures.extend(_check_no_machine_paths(bench_dir))
    return failures


def _check_truth_payload(ident: str, truth: Dict[str, Any], bench_dir: str) -> List[str]:
    failures: List[str] = []
    for key in (
        "scenario",
        "types",
        "reason",
        "levels_expected",
        "levels_forbidden",
        "symbols_expected",
        "objects_expected",
        "objects_forbidden",
        "sessions",
        "geometry",
        "thresholds_ref",
    ):
        if key not in truth:
            failures.append("场景 %s 的真值缺少键 %r" % (ident, key))
    if truth.get("scenario") != ident:
        failures.append("场景 %s 的真值里 scenario=%r 不自洽" % (ident, truth.get("scenario")))

    for key_path in _walk_keys(truth):
        if key_path.startswith("observed"):
            failures.append("场景 %s 的真值出现 observed_* 字段（%s）：K9 禁止把观测写进真值" % (ident, key_path))
            continue
        if key_path.startswith(_THRESHOLD_REF_PREFIX):
            # 例外：`thresholds_ref` 的**值**必须是 config 引用，由下面单独断言。
            continue
        leaf = key_path.rsplit(".", 1)[-1].split("[")[0]
        if leaf in FORBIDDEN_TRUTH_KEYS:
            failures.append(
                "场景 %s 的真值内嵌了策略数值键 %r：阈值必须写成 config 引用（K3 禁第二份数值表）" % (ident, leaf)
            )

    levels_expected = set(truth.get("levels_expected", []))
    levels_forbidden = set(truth.get("levels_forbidden", []))
    unknown = sorted((levels_expected | levels_forbidden) - set(LEVEL_ORDER))
    if unknown:
        failures.append("场景 %s 的 levels 出现未知粒度：%s" % (ident, unknown))
    if levels_expected & levels_forbidden:
        failures.append("场景 %s 的期望与禁忌粒度重叠：%s" % (ident, sorted(levels_expected & levels_forbidden)))
    if not truth.get("objects_forbidden"):
        failures.append("场景 %s 缺反向样例 objects_forbidden（K9：只测该命中的用例，阈值写错永不红）" % ident)

    for key, value in sorted(truth.get("thresholds_ref", {}).items()):
        if key == "note":
            continue
        if not isinstance(value, str) or not value.startswith("config:"):
            failures.append("场景 %s 的 thresholds_ref.%s=%r 不是 config 引用" % (ident, key, value))

    failures.extend(_check_geometry(ident, truth, bench_dir))
    return failures


def _check_geometry(ident: str, truth: Dict[str, Any], bench_dir: str) -> List[str]:
    """几何自洽 + 与 `repo/` 原文互证（ast 复算）+ 与 config 的阈值关系成立。"""
    failures: List[str] = []
    geometry = truth.get("geometry", {})
    sides = geometry.get("sides", [])
    if len(sides) != 2:
        failures.append("场景 %s 的 geometry.sides 不是两条：%r" % (ident, len(sides)))
        return failures
    repo_root = os.path.join(bench_dir, SCENARIOS_DIRNAME, ident, REPO_DIRNAME)
    for side in sides:
        path = side.get("path", "")
        if os.path.isabs(path) or path.startswith("..") or "\\" in path:
            failures.append("场景 %s 的真值路径 %r 不是干净的仓库相对路径" % (ident, path))
            continue
        source_path = os.path.join(repo_root, path.replace("/", os.sep))
        if not os.path.isfile(source_path):
            failures.append("场景 %s 的真值引用了不存在的仓库文件 %r" % (ident, path))
            continue
        actual = {name: tuple(span) for name, span in _symbol_ranges(_read_lines(source_path)).items()}
        declared = geometry.get("symbols", {}).get(path)
        if declared is None:
            failures.append("场景 %s 的 geometry.symbols 未登记 %r" % (ident, path))
            continue
        if {name: tuple(span) for name, span in declared.items()} != actual:
            failures.append("场景 %s 的真值符号区间与 repo/ 原文的 ast 不一致：%r ≠ %r" % (ident, declared, actual))
            continue
        start, end = side["changed"]
        containing = [name for name, (low, high) in actual.items() if low <= start and end <= high]
        if side.get("symbol") not in containing:
            failures.append(
                "场景 %s 的改动区间 %r 与所声明的符号 %r 不符（实际落在 %r）"
                % (ident, side.get("changed"), side.get("symbol"), containing)
            )

    pair = geometry.get("pair", {})
    low, high = sorted([sides[0]["changed"], sides[1]["changed"]], key=lambda item: item[0])
    expected_gap = high[0] - low[1] - 1
    if pair.get("same_file") and pair.get("gap_lines") != expected_gap:
        failures.append("场景 %s 的 gap_lines=%r 与声明区间复算的 %r 不符" % (ident, pair.get("gap_lines"), expected_gap))
    if pair.get("gap_rule"):
        failures.extend(_check_gap_rule(ident, pair, pair["gap_rule"]))
    return failures


def _read_lines(path: str) -> List[str]:
    return _read_text(path).rstrip("\n").split("\n")


def _check_gap_rule(ident: str, pair: Dict[str, Any], rule: Dict[str, Any]) -> List[str]:
    """把 `gap_rule` 求值：右端是 config 引用时**现场读 config**（改阈值而真值不动 → 这里变红）。"""
    rhs = rule.get("rhs", {})
    if "config_ref" in rhs:
        ref = rhs.get("config_ref", "")
        if not ref.startswith("config:"):
            return ["场景 %s 的 gap_rule 右端不是 config 引用：%r" % (ident, ref)]
        section, _, key = ref[len("config:") :].partition(".")
        try:
            expected = load_config().get(section, key) + rhs.get("offset", 0)
        except Exception as exc:  # 配置坏了就直说，不回落默认值
            return ["场景 %s 的 gap_rule 引用了不可读的 config 键 %r：%s" % (ident, ref, exc)]
        shown = "%s + offset %r" % (ref, rhs.get("offset", 0))
    elif "const" in rhs:
        expected = rhs["const"]
        shown = "构造常量"
    else:
        return ["场景 %s 的 gap_rule 缺少右端（config_ref 或 const）：%r" % (ident, rule)]

    actual = pair.get(rule.get("lhs"))
    holds = {
        "eq": actual == expected,
        "le": actual is not None and actual <= expected,
        "ge": actual is not None and actual >= expected,
        "lt": actual is not None and actual < expected,
        "gt": actual is not None and actual > expected,
    }.get(rule.get("op"))
    if holds is None:
        return ["场景 %s 的 gap_rule.op=%r 不受支持" % (ident, rule.get("op"))]
    if not holds:
        return [
            "场景 %s 的边界关系不成立：%s=%r %s (%s)=%r —— 阈值或几何动了，真值必须同步重生成"
            % (ident, rule.get("lhs"), actual, rule.get("op"), shown, expected)
        ]
    return []


def _walk_keys(node, prefix: str = "") -> List[str]:
    """递归列出键路径（用于 `observed_*` 与策略数值键的扫描）。"""
    found: List[str] = []
    if isinstance(node, dict):
        for key in sorted(node):
            path = "%s.%s" % (prefix, key) if prefix else str(key)
            found.append(path)
            found.extend(_walk_keys(node[key], path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_walk_keys(item, "%s[%d]" % (prefix, index)))
    return found


def _check_no_machine_paths(bench_dir: str) -> List[str]:
    """冻结产物不得登记环境依赖事实（`plan/05` §六）——本机绝对路径就是头号环境事实。"""
    failures: List[str] = []
    for rel, text in _tree_files(bench_dir).items():
        if _ABSOLUTE_PATH_RE.search(text):
            failures.append("%s 出现盘符式绝对路径：冻结产物必须用 %s 占位符" % (rel, PLACEHOLDER_ROOT))
        for marker in machine_path_markers():
            if marker in text:
                failures.append("%s 出现本机路径片段 %r（冻结产物必须与机器无关）" % (rel, marker))
    return failures


def _tree_files(root: str) -> Dict[str, str]:
    files: Dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            files[os.path.relpath(full, root).replace(os.sep, "/")] = _read_text(full)
    return files


def _compare_trees(left: str, right: str) -> List[str]:
    left_files = _tree_files(left)
    right_files = _tree_files(right)
    failures: List[str] = []
    missing = sorted(set(right_files) - set(left_files))
    extra = sorted(set(left_files) - set(right_files))
    if missing:
        failures.append("重跑生成器后缺失这些产物：%s" % missing)
    if extra:
        failures.append("冻结目录里有生成器不再产出的陈旧文件：%s" % extra)
    for rel in sorted(set(left_files) & set(right_files)):
        if left_files[rel] != right_files[rel]:
            failures.append("产物 %s 与冻结产物不逐字节一致" % rel)
    if not left_files:
        failures.append("比对面为空：重跑生成器一个文件都没产出（门禁在空转）")
    return failures


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    from ..cli import _ensure_utf8_stdio

    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="python -m agent_conflict_radar.bench.gen",
        description="合成冲突矩阵生成器（M1）：重建冻结产物 / 两层自检 / 物化场景",
    )
    parser.add_argument("--out", metavar="DIR", help="重建冻结产物到该目录（仓库根的 bench/）")
    parser.add_argument("--check", action="store_true", help="两层断言：冻结产物形态 + 重生成逐字节")
    parser.add_argument("--bench-dir", metavar="DIR", default=None, help="--check 的比对基准目录")
    parser.add_argument("--materialize", metavar="SCENARIO_ID", default=None, help="物化某场景到 --dest")
    parser.add_argument("--dest", metavar="DIR", default=None, help="配合 --materialize 的输出目录")
    args = parser.parse_args(list(argv) if argv is not None else None)

    chosen = [name for name, flag in (("--out", args.out), ("--check", args.check), ("--materialize", args.materialize)) if flag]
    if len(chosen) != 1:
        parser.error("请恰好选择一种动作：--out / --check / --materialize（收到 %s）" % (chosen or "无"))

    if args.materialize:
        if not args.dest:
            parser.error("--materialize 需要 --dest")
        scenario = scenario_by_id(args.materialize)
        shas = materialize_scenario(scenario, args.dest)
        sys.stdout.write(
            _dump_json({"scenario": scenario.ident, "dest": os.path.abspath(args.dest), "repo_shas": shas})
        )
        return 0

    if args.out:
        manifest = write_frozen(args.out)
        sys.stdout.write("已重建 %d 条场景 → %s\n" % (len(manifest["scenarios"]), os.path.abspath(args.out)))
        return 0

    bench_dir = args.bench_dir or _default_bench_dir()
    failures = check(bench_dir)
    if failures:
        sys.stderr.write("生成器自检未通过（%d 项）：\n" % len(failures))
        for item in failures:
            sys.stderr.write("  - %s\n" % item)
        return 1
    sys.stdout.write("生成器自检通过：冻结产物形态 + 重生成逐字节 + 提交 sha 复算（%s）\n" % bench_dir)
    return 0


def _default_bench_dir() -> str:
    root = find_repo_root()
    if root is None:
        raise RuntimeError("找不到仓库根（向上未发现 pyproject.toml）：请用 --bench-dir 显式指定冻结目录")
    return os.path.join(str(root), "bench")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
