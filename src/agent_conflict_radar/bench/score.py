"""`radar bench`：合成矩阵评分（M5）。

**为什么在 `bench/score.py` 而不是 `bench.py`**：`agent_conflict_radar.bench` 已经是
**生成器所在的包**（`bench.gen` / `bench.rng`）。同目录下再放一个 `bench.py` 会与包目录
撞名——Python 会静默选中包，`bench.py` 永远不生效（本机实测：`import pkg.bench` 拿到的是
`pkg/bench/__init__.py`）。评分因此作为包内模块落地，命令面仍是 `radar bench`（`plan/04` M5）。

**这一层做什么**：把冻结矩阵的每条场景**物化成真 git 仓库 + 真会话日志**，跑
`scan → intent → detect` 完整链路，再与 `truth.json` 的**期望集合**做集合精确匹配。
多报（extra）、漏报（missing）**均计失败**——"只断言该报的都报了"永远测不出误报。

四条硬约束（对应 `plan/07` 的 K）：

* **K9**：只读真值。评分结果写进 `last_run.json`，**绝不**回写真值（`observed_*` 仍是红线）。
* **K3**：阈值只从 config 读（链路内部本来就是这样）；本模块**零策略数值字面量**（K5 会扫）。
* **K2**：`last_run.json` 走 `serialize.write_atomic`，冻结序列化契约。
* **K17**：`last_run.json` 落在 `bench/` 下，因此**不得含本机路径 / 时间戳 / 用户名**——
  机器无关才可入仓复算。失败信息里的临时路径一律替换成 `{{WORK}}` 占位符。

**确定性**：合成会话的固定基准时间是 `2026-01-01T00:00:00Z` 起的确定偏移，参考时刻取固定常量
（模块常量 `REFERENCE_TIME`），**不读系统时钟**——否则同一份矩阵两次评分会出现不同的活跃窗口。
"""

import json
import os
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import detect as detect_module
from .. import discover as discover_module
from .. import intent as intent_module
from ..errors import EnvironmentError_, UsageError
from ..paths import find_repo_root
from ..serialize import write_atomic
from . import gen

#: `radar bench` 的汇总产物名（落在矩阵目录，`plan/05` §二）。
LAST_RUN_FILENAME = "last_run.json"

#: 评分参考时刻：合成会话从 `2026-01-01T00:00:00Z` 起按固定偏移生成，这里取基准 + 固定偏移。
#: **不读系统时钟**——同一个矩阵任何一天跑都必须得到同一份判定。
REFERENCE_TIME = "2026-01-01T00:10:00Z"

KIND_CONFLICT = "conflict"
KIND_INTENT = "intent"

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"

_PLACEHOLDER_WORK = "{{WORK}}"
_PLACEHOLDER_BENCH = "{{BENCH}}"

#: 场景结果里"该场景没跑起来"时的错误记录键名（与 `checks` 平级，便于一眼看出是环境问题）。
ERROR_KEY = "error"


# --------------------------------------------------------------------------------------
# 结果对象
# --------------------------------------------------------------------------------------


class BenchResult(object):
    """一次评分的结果（可序列化为 `last_run.json`，也可渲染成人读文本）。"""

    def __init__(self, scenarios, global_checks, only, generator_version, notes=(), bench_dir=None):
        self.scenarios = list(scenarios)
        self.global_checks = list(global_checks)
        self.only = list(only) if only is not None else None
        self.generator_version = generator_version
        self.notes = list(notes)
        #: 本轮解析出的矩阵目录（CLI 落默认 `last_run.json` 时要用**这一处**，不能另算一遍）。
        self.bench_dir = bench_dir

    def as_dict(self) -> Dict[str, Any]:
        failed_checks = [
            check
            for scenario in self.scenarios
            for check in scenario.get("checks", [])
            if check.get("verdict") != VERDICT_PASS
        ] + [check for check in self.global_checks if check.get("verdict") != VERDICT_PASS]
        total_checks = sum(len(item.get("checks", [])) for item in self.scenarios) + len(self.global_checks)
        passed = sum(1 for item in self.scenarios if item.get("verdict") == VERDICT_PASS)
        return {
            "bench": {
                "generator_version": self.generator_version,
                "reference_time": REFERENCE_TIME,
                "kinds": [KIND_CONFLICT, KIND_INTENT],
                "parameter_source": {
                    "note": "数值只有一个来源：config/radar.toml（K3）。本产物不复制任何数值，只登记键名。",
                    "config_relative_path": "config/radar.toml",
                    "keys": [
                        "window.active_minutes",
                        "window.scan_days",
                        "symbol.adjacent_tolerance",
                        "symbol.min_overlap_lines",
                        "severity.same_symbol",
                        "severity.same_file_diff_symbol",
                        "severity.adjacent_lines",
                        "severity.file_only",
                        "git.merge_tree_enabled",
                        "git.timeout_seconds",
                    ],
                },
                "counting_unit": "用例条目数（一条场景一条）",
            },
            "only": self.only,
            "global_checks": self.global_checks,
            "scenarios": self.scenarios,
            "summary": {
                "scenarios": len(self.scenarios),
                "passed": passed,
                "failed": len(self.scenarios) - passed,
                "checks": total_checks,
                "checks_failed": len(failed_checks),
                "coverage_ok": all(
                    check.get("verdict") == VERDICT_PASS
                    for check in self.global_checks
                    if check.get("name", "").startswith("coverage.")
                ),
                "all_passed": passed == len(self.scenarios)
                and all(check.get("verdict") == VERDICT_PASS for check in self.global_checks),
            },
            "notes": self.notes,
        }

    def all_passed(self) -> bool:
        return bool(self.as_dict()["summary"]["all_passed"])


# --------------------------------------------------------------------------------------
# 小工具：集合比较（多报/漏报都要能被点名）
# --------------------------------------------------------------------------------------


def _jsonable(value):
    """JSON 可写形态（set 也要能写：`last_run.json` 是冻结产物，写不进去就是硬失败）。"""
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_jsonable(item) for item in sorted(value, key=_sort_key)]
    if isinstance(value, dict):
        return dict((key, _jsonable(item)) for key, item in value.items())
    return value


def _sort_key(value):
    return json.dumps(_jsonable(value), sort_keys=True, ensure_ascii=False)


def _sorted_items(values: Iterable) -> List:
    return sorted((_jsonable(item) for item in values), key=_sort_key)


def _freeze(value):
    """把任意形态归一成可哈希的**规范形态**（tuple 与 list 必须比较相等）。"""
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def _set_check(name: str, expected: Iterable, actual: Iterable) -> Dict[str, Any]:
    """集合精确匹配：`missing` 是漏报，`extra` 是多报。两者都非空即失败。"""
    expected_norm = set(_freeze(item) for item in expected)
    actual_norm = set(_freeze(item) for item in actual)
    missing = expected_norm - actual_norm
    extra = actual_norm - expected_norm
    return {
        "name": name,
        "expected": _sorted_items(expected_norm),
        "actual": _sorted_items(actual_norm),
        "missing": _sorted_items(missing),
        "extra": _sorted_items(extra),
        "verdict": VERDICT_PASS if not missing and not extra else VERDICT_FAIL,
    }


def _value_check(name: str, expected: Any, actual: Any) -> Dict[str, Any]:
    """逐值比较（用于计数这类必须**完全相等**的字段）。"""
    return {
        "name": name,
        "expected": _jsonable(expected),
        "actual": _jsonable(actual),
        "missing": [],
        "extra": [],
        "verdict": VERDICT_PASS if _freeze(expected) == _freeze(actual) else VERDICT_FAIL,
    }


def _error_scenario(ident, kind, types, exc, work_dir, bench_dir):
    return {
        "id": ident,
        "kind": kind,
        "types": sorted(types),
        "verdict": VERDICT_FAIL,
        "expected": {},
        "actual": {},
        "checks": [],
        "error": "%s: %s" % (type(exc).__name__, _sanitize(str(exc), work_dir, bench_dir)),
    }


def _sanitize(text: str, work_dir: str, bench_dir: str) -> str:
    """把本机路径替换成占位符（K17：`bench/` 下的文本必须机器无关）。

    只影响失败信息；成功路径不含任何路径。
    """
    for raw, placeholder in ((work_dir, _PLACEHOLDER_WORK), (bench_dir, _PLACEHOLDER_BENCH)):
        if raw:
            text = text.replace(raw.replace("\\", "/"), placeholder).replace(raw, placeholder)
    return text


# --------------------------------------------------------------------------------------
# 真值 / 台账加载
# --------------------------------------------------------------------------------------


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return json.loads(handle.read())


def _truth_path(bench_dir: str, kind: str, ident: str) -> str:
    if kind == KIND_CONFLICT:
        return os.path.join(bench_dir, gen.SCENARIOS_DIRNAME, ident, gen.TRUTH_FILENAME)
    return os.path.join(bench_dir, gen.INTENTS_DIRNAME, ident, gen.INTENT_TRUTH_FILENAME)


def _manifest_path(bench_dir: str, kind: str) -> str:
    if kind == KIND_CONFLICT:
        return os.path.join(bench_dir, gen.MANIFEST_FILENAME)
    return os.path.join(bench_dir, gen.INTENTS_DIRNAME, gen.MANIFEST_FILENAME)


def _manifest_entries(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict((entry.get("id"), entry) for entry in manifest.get("scenarios", []))


def _truth_digest(path: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return gen._sha256_text(handle.read())  # noqa: SLF001 - 生成侧的 sha 实现只有一个


def known_ids() -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """`(冲突场景 ids, 意图场景 ids)`——排序后的冻结顺序。"""
    return tuple(gen.scenario_ids()), tuple(gen.intent_scenario_ids())


def known_all() -> List[Tuple[str, str]]:
    """全部 `(kind, id)`（不受 `--only` 影响）。"""
    conflict_ids, intent_ids = known_ids()
    return [(KIND_CONFLICT, ident) for ident in conflict_ids] + [
        (KIND_INTENT, ident) for ident in intent_ids
    ]


def _kind_of(ident: str) -> str:
    conflict_ids, _intent_ids = known_ids()
    return KIND_CONFLICT if ident in conflict_ids else KIND_INTENT


def _select(only: Optional[Sequence[str]]) -> List[Tuple[str, str]]:
    """把 `--only` 解析成 `[(kind, id)]`；未知 id / 过滤后为空都是**用法错误**（exit 2）。"""
    conflict_ids, intent_ids = known_ids()
    known = known_all()
    if only is None:
        return known

    requested = [item.strip() for item in only if item.strip()]
    if not requested:
        raise UsageError("--only 过滤后为空：至少给一个场景 id（否则“零条通过”会被读成成功）")

    known_map = dict(((ident, kind) for kind, ident in known))
    unknown = [ident for ident in requested if ident not in known_map]
    if unknown:
        raise UsageError(
            "--only 指定了不存在的场景 id：%s（已知冲突场景 %s；意图场景 %s）"
            % (unknown, list(conflict_ids), list(intent_ids))
        )
    wanted = set(requested)
    return [(kind, ident) for kind, ident in known if ident in wanted]


# --------------------------------------------------------------------------------------
# 场景执行
# --------------------------------------------------------------------------------------


def _empty_dir(work_dir: str) -> str:
    path = os.path.join(work_dir, "empty-session-root")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _session_roots(dest: str, work_dir: str) -> Tuple[str, str]:
    """两侧**都**显式传根；场景里没有该源时传一个空目录（`plan/05` §七）。

    缺省探测会落到真实用户日志上——评分绝不能因为"顺手"读进真实会话。
    """
    roots = []
    for name in ("claude", "codex"):
        path = os.path.join(dest, gen.SESSIONS_DIRNAME, name)
        roots.append(path if os.path.isdir(path) else _empty_dir(work_dir))
    return roots[0], roots[1]


def _run_conflict(ident, truth, bench_dir, cfg, work_dir) -> Dict[str, Any]:
    scenario = gen.scenario_by_id(ident)
    dest = os.path.join(work_dir, "scenarios", ident)
    gen.materialize_scenario(scenario, dest)
    repo = os.path.join(dest, gen.REPO_DIRNAME)
    claude_root, codex_root = _session_roots(dest, work_dir)

    table = discover_module.build_workspace_table(
        repo, claude_root, codex_root, cfg, now=REFERENCE_TIME
    )
    intents = intent_module.build_intent_set(
        repo, claude_root, codex_root, cfg, now=REFERENCE_TIME
    )
    conflicts = detect_module.build_conflict_set(
        repo, claude_root, codex_root, cfg, now=REFERENCE_TIME
    )

    # ---- M1：会话归集（集合精确匹配）----
    actual_sessions = set(item.session_id for item in table.sessions)
    scans = [_set_check("scan.sessions", truth.get("sessions", []), actual_sessions)]

    # ---- M2：改动意图（`(path, session)` 集合精确匹配）----
    expected_pairs = set(
        (side.get("path"), side.get("session")) for side in truth.get("geometry", {}).get("sides", [])
    )
    actual_pairs = set()
    for entry in intents.entries:
        if not entry.path:
            continue
        for session_id in entry.session_ids:
            actual_pairs.add((entry.path, session_id))
    scans.append(_set_check("intent.path_sessions", expected_pairs, actual_pairs))

    # ---- M3：检出集合（K20：levels / symbols 集合精确匹配）----
    actual_levels = set()
    actual_symbols = set()
    actual_objects = set()
    for conflict in conflicts.conflicts:
        actual_levels |= set(conflict.levels)
        actual_symbols |= set(conflict.symbols)
        if conflict.symbols_in_product():
            for symbol in conflict.symbols or (None,):
                actual_objects.add((conflict.path, symbol))
        else:
            # `approximate=True`：产物里**没有**符号字段（R4）。该条只能按文件级对象核验。
            actual_objects.add((conflict.path, None))

    expected_objects = set(
        (item.get("path"), item.get("symbol")) for item in truth.get("objects_expected", [])
    )
    forbidden_objects = set(
        (item.get("path"), item.get("symbol")) for item in truth.get("objects_forbidden", [])
    )
    hits_forbidden = actual_objects & forbidden_objects

    checks = scans + [
        _set_check("detect.levels", truth.get("levels_expected", []), actual_levels),
        _set_check("detect.symbols", truth.get("symbols_expected", []), actual_symbols),
        _set_check("detect.objects", expected_objects, actual_objects),
        _set_check("detect.forbidden_objects", set(), hits_forbidden),
    ]
    # 反向样例也要在 `levels` / `symbols` 上落一道（几何对得上但适用域写错时会在这里红）。
    checks.append(
        _set_check(
            "detect.forbidden_levels",
            set(),
            actual_levels & set(truth.get("levels_forbidden", [])),
        )
    )
    checks.append(
        _set_check(
            "detect.forbidden_symbols",
            set(),
            actual_symbols & set(truth.get("symbols_forbidden", [])),
        )
    )
    # 退出码口径（K20 ③）：有期望冲突 → 1，否则 0。评分消费的是"判定"，不是"条数"。
    expected_exit = 1 if truth.get("levels_expected") else 0
    actual_exit = 1 if conflicts.conflicts else 0
    checks.append(_value_check("detect.exit_code", expected_exit, actual_exit))

    expected_view = {
        "sessions": sorted(truth.get("sessions", [])),
        "levels": sorted(truth.get("levels_expected", [])),
        "symbols": sorted(truth.get("symbols_expected", [])),
        "objects": _sorted_items(expected_objects),
        "exit_code": expected_exit,
    }
    actual_view = {
        "sessions": sorted(actual_sessions),
        "levels": sorted(actual_levels),
        "symbols": sorted(actual_symbols),
        "objects": _sorted_items(actual_objects),
        "exit_code": actual_exit,
    }
    return _scenario_record(ident, KIND_CONFLICT, truth.get("types", []), checks, expected_view, actual_view)


def _run_intent(ident, truth, bench_dir, cfg, work_dir) -> Dict[str, Any]:
    scenario = gen.intent_scenario_by_id(ident)
    dest = os.path.join(work_dir, gen.INTENTS_DIRNAME, ident)
    gen.materialize_intent_scenario(scenario, dest)
    repo = os.path.join(dest, gen.INTENT_REPO_DIRNAME)
    claude_root, codex_root = _session_roots(dest, work_dir)

    intents = intent_module.build_intent_set(
        repo, claude_root, codex_root, cfg, now=REFERENCE_TIME
    )

    # ---- 条目集合：`(path, session_id, precision)` 展开后精确匹配（多报/漏报均失败）----
    def expand(entries):
        out = set()
        for item in entries:
            path = item.get("path", "")
            if not path:
                continue
            ids = item.get("session_ids") or ([item["session_id"]] if item.get("session_id") else [None])
            for session_id in ids:
                out.add((path, session_id or "", item.get("precision", "")))
        return out

    expected_entries = expand(truth.get("entries_expected", []))
    actual_entries = expand([entry.as_dict() for entry in intents.entries])

    located = [entry for entry in intents.entries if entry.path]
    unknown = [entry for entry in intents.entries if not entry.path]

    checks = [
        _set_check("intent.entries", expected_entries, actual_entries),
        _value_check(
            "intent.unknown_entries",
            truth.get("unknown_expected", {}).get("entries", 0),
            len(unknown),
        ),
    ]
    if unknown:
        expected_reasons = sorted(truth.get("unknown_expected", {}).get("reasons", []))
        actual_reasons = sorted(unknown[0].reasons)
        checks.append(_set_check("intent.unknown_reasons", expected_reasons, actual_reasons))

    for name in sorted(truth.get("counts_expected", {})):
        checks.append(
            _value_check(
                "intent.counts.%s" % name,
                truth["counts_expected"][name],
                intents.counts().get(name),
            )
        )

    forbidden = set(truth.get("paths_forbidden", []))
    checks.append(
        _set_check(
            "intent.forbidden_paths",
            set(),
            set(entry.path for entry in located) & forbidden,
        )
    )

    expected_view = {
        "entries": _sorted_items(expected_entries),
        "unknown_entries": truth.get("unknown_expected", {}).get("entries", 0),
        "counts": dict(truth.get("counts_expected", {})),
    }
    actual_view = {
        "entries": _sorted_items(actual_entries),
        "unknown_entries": len(unknown),
        "counts": intents.counts(),
    }
    return _scenario_record(ident, KIND_INTENT, truth.get("types", []), checks, expected_view, actual_view)


def _scenario_record(ident, kind, types, checks, expected_view, actual_view) -> Dict[str, Any]:
    return {
        "id": ident,
        "kind": kind,
        "types": sorted(types),
        "verdict": VERDICT_PASS if all(c["verdict"] == VERDICT_PASS for c in checks) else VERDICT_FAIL,
        "expected": expected_view,
        "actual": actual_view,
        "checks": checks,
    }


# --------------------------------------------------------------------------------------
# 台账与覆盖度（消费侧再验一遍，而不是只信生成器）
# --------------------------------------------------------------------------------------


def _check_manifest(bench_dir, kind, truths, entries) -> List[Dict[str, Any]]:
    """真值 sha256 + 覆盖度门槛（`min_count_by_type` / `missing_types`）。

    **为什么评分也要验**：生成器 `--check` 是"生产侧自检"，评分是**消费侧**。
    只信生产侧的话，"台账被手改过但生成器恰好看不出"的形态在这里会照常给出 PASS——
    基准就变成了"比对两份预先算好的答案"（K9 的判别句）。

    **`truths` 必须是整棵矩阵**（不受 `--only` 影响的完整集合）：覆盖度是矩阵的属性，
    不是"这次跑了哪几条"的属性。用过滤后的子集算覆盖度，会让 `--only` 一次就报"缺类"，
    那等于把"只跑一条"误判成"矩阵坏了"。
    """
    checks: List[Dict[str, Any]] = []
    ordered = sorted(truths)
    mismatched = []
    for ident in ordered:
        truth_path = _truth_path(bench_dir, kind, ident)
        digest = _truth_digest(truth_path)
        entry = entries.get(ident)
        if entry is None:
            mismatched.append(ident)
            continue
        if entry.get("truth_sha256") != digest:
            mismatched.append(ident)
        cases = entry.get("cases", [])
        if len(cases) != 1 or cases[0].get("truth_sha256") != digest:
            mismatched.append(ident)
    checks.append(
        _set_check("manifest.%s.truth_sha256" % kind, set(), set(mismatched))
    )

    manifest = _read_json(_manifest_path(bench_dir, kind))
    coverage = manifest.get("coverage", {})
    count_by_type: Dict[str, int] = {}
    for ident in ordered:
        for type_name in truths[ident].get("types", []):
            count_by_type[type_name] = count_by_type.get(type_name, 0) + 1

    checks.append(_value_check("coverage.%s.count_by_type" % kind, coverage.get("count_by_type", {}), count_by_type))

    minimum = coverage.get("min_count_by_type", {})
    short = sorted(name for name, value in minimum.items() if count_by_type.get(name, 0) < value)
    checks.append(
        _value_check(
            "coverage.%s.min_count_by_type" % kind,
            [],
            short,
        )
    )
    checks.append(_value_check("coverage.%s.missing_types" % kind, [], coverage.get("missing_types", [])))
    checks.append(
        _value_check("coverage.%s.missing_types_matches" % kind, short, coverage.get("missing_types", []))
    )
    checks.append(
        _set_check(
            "manifest.%s.scenario_set" % kind,
            set(truths),
            set(entries),
        )
    )
    return checks


def _threshold_pair_check(bench_dir, truths) -> Dict[str, Any]:
    """阈值成对样例必须在矩阵里，且一命中一不命中（`plan/05` §4.2 的硬要求）。"""
    manifest = _read_json(_manifest_path(bench_dir, KIND_CONFLICT))
    pair = manifest.get("coverage", {}).get("threshold_pair", {})
    hit, miss = pair.get("hit_case"), pair.get("miss_case")
    problems = []
    if hit not in truths or miss not in truths:
        problems.append("成对样例缺失")
    else:
        if "symbol" not in truths[hit].get("levels_expected", []):
            problems.append("hit 侧未期望符号级命中")
        if "symbol" in truths[miss].get("levels_expected", []):
            problems.append("miss 侧竟期望符号级命中")
    return _value_check("coverage.conflict.threshold_pair", [], problems)


# --------------------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------------------


def default_bench_dir() -> str:
    root = find_repo_root()
    if root is None:
        raise EnvironmentError_(
            "找不到仓库根（向上未发现 pyproject.toml）：请用 --bench-dir 显式指定合成矩阵目录。"
        )
    return os.path.join(str(root), "bench")


def run_bench(
    bench_dir: Optional[str] = None,
    out_dir: Optional[str] = None,
    only: Optional[Sequence[str]] = None,
    cfg=None,
) -> BenchResult:
    """跑完整矩阵评分，返回 `BenchResult`；给了 `out_dir` 就落 `last_run.json`（K2 原子写）。"""
    bench_dir = os.path.abspath(bench_dir or default_bench_dir())
    if not os.path.isdir(bench_dir):
        raise EnvironmentError_("合成矩阵目录不存在：%s（先跑生成器 --out 或显式传 --bench-dir）" % bench_dir)
    selected = _select(only)

    manifest_entries = {}
    manifest_entries[KIND_CONFLICT] = _manifest_entries(
        _read_json(_manifest_path(bench_dir, KIND_CONFLICT))
    )
    manifest_entries[KIND_INTENT] = _manifest_entries(
        _read_json(_manifest_path(bench_dir, KIND_INTENT))
    )

    truths: Dict[str, Dict[str, Any]] = {}
    missing_truths: List[str] = []
    for kind, ident in selected:
        path = _truth_path(bench_dir, kind, ident)
        if not os.path.isfile(path):
            missing_truths.append(ident)
            continue
        truths[ident] = _read_json(path)

    # ---- 覆盖度与台账复核：按**整棵矩阵**算（覆盖度是矩阵的属性，不是"这次跑了哪几条"）----
    all_truths: Dict[str, Dict[str, Any]] = {}
    missing_all: List[str] = []
    for kind, ident in known_all():
        path = _truth_path(bench_dir, kind, ident)
        if not os.path.isfile(path):
            missing_all.append(ident)
            continue
        # 已加载过的（被 `--only` 选中的）复用；其余仍要读进来算覆盖度。
        all_truths[ident] = truths.get(ident) or _read_json(path)

    global_checks: List[Dict[str, Any]] = []
    for kind in (KIND_CONFLICT, KIND_INTENT):
        subset = dict(
            (ident, truth) for ident, truth in all_truths.items() if _kind_of(ident) == kind
        )
        if subset:
            global_checks.extend(_check_manifest(bench_dir, kind, subset, manifest_entries[kind]))
    global_checks.append(_threshold_pair_check(bench_dir, all_truths))
    global_checks.append(
        _set_check(
            "manifest.truth_files_present",
            set(),
            set(sorted(set(missing_all) | set(missing_truths))),
        )
    )

    tips = [
        "抽样覆盖非穷举：本基准声明的是「每类至少一条 + 集合覆盖」，不是穷举所有几何。",
        "评分只读真值：实际检出写进本产物，不回写真值（K9）。",
        "阈值只在 config/radar.toml 定义；本产物只登记键名，不复制数值（K3）。",
        "参考时刻是固定常量，不读系统时钟——同一矩阵任何时候跑都得到同一判定。",
    ]
    if all(check["verdict"] == VERDICT_PASS for check in global_checks):
        tips.append("覆盖度门槛与台账 sha 复核通过。")

    scenarios: List[Dict[str, Any]] = []
    work_dir = tempfile.mkdtemp(prefix="radar-bench-run-")
    try:
        for kind, ident in selected:
            truth = truths.get(ident)
            if truth is None:
                scenarios.append(
                    {
                        "id": ident,
                        "kind": kind,
                        "types": sorted(manifest_entries[kind].get(ident, {}).get("types", [])),
                        "verdict": VERDICT_FAIL,
                        "expected": {},
                        "actual": {},
                        "checks": [],
                        ERROR_KEY: "真值文件缺失：%s" % _sanitize(
                            _truth_path(bench_dir, kind, ident), work_dir, bench_dir
                        ),
                    }
                )
                continue
            try:
                if kind == KIND_CONFLICT:
                    scenarios.append(_run_conflict(ident, truth, bench_dir, cfg, work_dir))
                else:
                    scenarios.append(_run_intent(ident, truth, bench_dir, cfg, work_dir))
            except Exception as exc:  # noqa: BLE001 - 单场景失败不拖垮整轮（逐条点名）
                scenarios.append(
                    _error_scenario(
                        ident, kind, truth.get("types", []), exc, work_dir, bench_dir
                    )
                )
    finally:
        # Windows 上 git 对象带只读位：复用生成器的降权删除实现（不在这里复制一份常量）。
        gen._rmtree(work_dir)  # noqa: SLF001

    result = BenchResult(
        scenarios=scenarios,
        global_checks=global_checks,
        only=only,
        generator_version=gen.GENERATOR_VERSION,
        notes=tips,
        bench_dir=bench_dir,
    )
    if out_dir is not None:
        write_last_run(out_dir, result)
    return result


def write_last_run(out_dir: str, result: BenchResult) -> str:
    """把评分结果按冻结契约写进 `<out_dir>/last_run.json`（K2 唯一写盘点）。"""
    from ..serialize import dumps_json

    target_dir = os.path.abspath(out_dir)
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir)
    path = os.path.join(target_dir, LAST_RUN_FILENAME)
    write_atomic(path, dumps_json(result.as_dict()))
    return path


# --------------------------------------------------------------------------------------
# 人读渲染（逐场景 期望 / 实际 / 判定）
# --------------------------------------------------------------------------------------


def _show(value) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_show(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join("%s=%s" % (key, _show(value[key])) for key in sorted(value)) + "}"
    return "%s" % (value,)


def render_summary(result: BenchResult) -> str:
    payload = result.as_dict()
    lines: List[str] = []
    add = lines.append

    add("== 合成基准评分（radar bench）==")
    add("矩阵生成器版本：%s" % payload["bench"]["generator_version"])
    add("参考时刻：%s（固定常量，不读系统时钟）" % payload["bench"]["reference_time"])
    add(
        "本轮场景：%d 条（冲突 %d + 意图 %d）"
        % (
            len(payload["scenarios"]),
            sum(1 for item in payload["scenarios"] if item["kind"] == KIND_CONFLICT),
            sum(1 for item in payload["scenarios"] if item["kind"] == KIND_INTENT),
        )
    )
    add("")

    for item in payload["scenarios"]:
        add("[%s] %s（%s）" % (item["verdict"].upper(), item["id"], "冲突场景" if item["kind"] == KIND_CONFLICT else "意图场景"))
        if item.get(ERROR_KEY):
            add("       期望：（场景未能执行）")
            add("       实际：%s" % item[ERROR_KEY])
            add("       判定：%s" % VERDICT_FAIL)
            add("")
            continue
        add("       期望：%s" % _show(item["expected"]))
        add("       实际：%s" % _show(item["actual"]))
        add("       判定：%s" % item["verdict"])
        for check in item["checks"]:
            if check["verdict"] == VERDICT_PASS:
                continue
            detail = []
            if check["missing"]:
                detail.append("漏报 %s" % _show(check["missing"]))
            if check["extra"]:
                detail.append("多报 %s" % _show(check["extra"]))
            if not detail:
                detail.append("期望 %s ≠ 实际 %s" % (_show(check["expected"]), _show(check["actual"])))
            add("       - %s：%s" % (check["name"], "；".join(detail)))
        add("")

    add("== 覆盖度门槛与台账复核 ==")
    for check in payload["global_checks"]:
        add(
            "   [%s] %s%s"
            % (
                check["verdict"].upper(),
                check["name"],
                "" if check["verdict"] == VERDICT_PASS else "（期望 %s ≠ 实际 %s）" % (_show(check["expected"]), _show(check["actual"])),
            )
        )
    add("")

    summary = payload["summary"]
    add("== 汇总 ==")
    add("   场景 %d 条：通过 %d，失败 %d" % (summary["scenarios"], summary["passed"], summary["failed"]))
    add("   检查 %d 项：失败 %d" % (summary["checks"], summary["checks_failed"]))
    add("   覆盖度门槛：%s" % ("达标" if summary["coverage_ok"] else "未达标"))
    if summary["all_passed"]:
        add("结论：PASS（退出码 0）")
    else:
        add("结论：FAIL（退出码 1：基准未达标，不是“检出冲突”）")
    add(
        "退出码语义提醒：`bench` 的 1 是「基准未达标」，与 `detect` / `report` 的"
        "「检出冲突」不是同一件事——不要因为评分失败去改仓库代码。"
    )
    return "\n".join(lines) + "\n"
