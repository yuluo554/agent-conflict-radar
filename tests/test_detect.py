"""`detect.py` 的端到端对账（M3 DoD：精确匹配 / 负样本零误报 / 反向样例 / 只读 / 计数恒等）。

分工：

* `tests/test_detect_parse.py`：纯函数级（AST 符号区间 / 相邻容差 / merge-tree 解析 / 三态降级），不碰 git；
* 本文件：**端到端**——从合成冲突矩阵物化出真 git 仓库（两条分支）+ 真会话日志，跑 `radar detect`，
  再与 `bench/scenarios/<id>/truth.json` 逐条对账。

三条纪律：

1. **真值不当期望手抄**：期望值一律来自冻结真值（`levels_expected` / `symbols_expected` /
   `objects_forbidden`），矩阵里的每一条都由 `tests/test_bench_matrix.py` 独立复算过；
2. **多报 / 漏报都失败**：按**集合**精确匹配，不用"包含"；
3. **两侧会话根都显式传**（`plan/05` §七）：缺省探测会落到真实用户日志上。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import config as config_module
from agent_conflict_radar import detect, serialize, stages
from agent_conflict_radar.bench import gen
from agent_conflict_radar.exit_codes import EXIT_CONFLICTS_FOUND, EXIT_OK

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
BENCH_DIR = REPO_ROOT / "bench"

#: 合成会话时间戳的固定基准 + 偏移（K11）；显式传 `--now` 保证双跑一致。
NOW = "2026-01-01T00:10:00Z"


def _git_available():
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="物化合成仓库需要 git（缺依赖不是通过）")


def _root_flags(dest, scratch):
    """两侧都显式传根；场景里没有该源时传一个空目录（钉死探测面）。"""
    flags = []
    for name in ("claude", "codex"):
        path = Path(dest) / "sessions" / name
        if not path.is_dir():
            path = Path(scratch) / ("empty-%s" % name)
            path.mkdir(parents=True, exist_ok=True)
        flags += ["--%s-root" % name, str(path)]
    return flags


def _truth(scenario_id):
    return json.loads((BENCH_DIR / "scenarios" / scenario_id / "truth.json").read_text(encoding="utf-8"))


def _materialize(scenario_id, dest):
    gen.materialize_scenario(gen.scenario_by_id(scenario_id), str(dest))
    return dest


def _detect(dest, cfg=None, scratch=None):
    """进程内跑检测主体（快，且便于逐字段断言）。"""
    cfg = cfg or config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    roots = {}
    for name in ("claude", "codex"):
        path = Path(dest) / "sessions" / name
        if not path.is_dir():
            path = Path(scratch or (Path(dest) / "_scratch")) / ("empty-%s" % name)
            path.mkdir(parents=True, exist_ok=True)
        roots[name] = str(path)
    return detect.build_conflict_set(
        str(Path(dest) / "repo"), roots["claude"], roots["codex"], cfg, now=NOW
    )


def _run_cli(dest, extra=(), pre=(), cwd=None, scratch=None):
    """真子进程跑 `python -m agent_conflict_radar detect`，返回 (退出码, stdout 字节, stderr 文本)。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    scratch = Path(scratch or (Path(dest) / "_scratch"))
    scratch.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "agent_conflict_radar"] + list(pre) + [
        "detect", "--repo", str(Path(dest) / "repo"),
    ]
    argv += _root_flags(dest, scratch)
    argv += ["--now", NOW] + list(extra)
    completed = subprocess.run(
        argv, cwd=str(cwd or REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", errors="replace")


def _worktree_digest(repo_dir):
    """工作区 + 索引 + HEAD 的指纹（只读断言的判据：跑前跑后必须一致）。"""
    import hashlib

    digests = {}
    for path in sorted(Path(repo_dir).rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_dir).as_posix()
        if rel.startswith(".git/") and rel not in (".git/index", ".git/HEAD"):
            continue  # `.git/objects` 会被 `--write-tree` 写（这条边界在 README 里如实披露）
        digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


# --------------------------------------------------------------------------------------
# 逐场景精确匹配（DoD 主判据）
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario_id", gen.scenario_ids())
def test_scenario_detects_to_the_frozen_truth(scenario_id, tmp_path):
    """场景 1–6 的检出集合**精确匹配**（多报、漏报均失败），逐样本点名。"""
    dest = _materialize(scenario_id, tmp_path / scenario_id)
    truth = _truth(scenario_id)
    result = _detect(dest, scratch=tmp_path)

    levels = set()
    symbols = set()
    for conflict in result.conflicts:
        levels |= set(conflict.levels)
        symbols |= set(conflict.symbols)

    assert levels == set(truth["levels_expected"]), (
        "%s 的粒度集合不匹配：实际 %s ≠ 真值 %s（conflicts=%s）"
        % (scenario_id, sorted(levels), sorted(truth["levels_expected"]),
           [item.path for item in result.conflicts])
    )
    assert levels & set(truth["levels_forbidden"]) == set(), (
        "%s 报出了不该报的粒度：%s" % (scenario_id, sorted(levels & set(truth["levels_forbidden"])))
    )
    assert symbols == set(truth["symbols_expected"]), (
        "%s 的符号集合不匹配：实际 %s ≠ 真值 %s" % (scenario_id, sorted(symbols), sorted(truth["symbols_expected"]))
    )
    assert symbols & set(truth["symbols_forbidden"]) == set(), (
        "%s 报出了不该报的符号：%s" % (scenario_id, sorted(symbols & set(truth["symbols_forbidden"])))
    )

    # 反向样例：`objects_forbidden` 一个都不许命中（顺带把 filler.py 噪声也钉住）。
    for forbidden in truth["objects_forbidden"]:
        hits = [
            item.path for item in result.conflicts
            if item.path == forbidden["path"] and forbidden["symbol"] in item.symbols
        ]
        assert hits == [], "%s 命中了反向样例 %s" % (scenario_id, forbidden)

    # `objects_expected` 必须真的在场（`symbol: null` 表示"该条只到文件级"）。
    for expected in truth["objects_expected"]:
        hits = [
            item for item in result.conflicts
            if item.path == expected["path"]
            and (expected["symbol"] is None or expected["symbol"] in item.symbols)
        ]
        assert hits, "%s 缺少期望命中 %s（实际 %s）" % (
            scenario_id, expected, [item.path for item in result.conflicts]
        )


@pytest.mark.parametrize("scenario_id", gen.scenario_ids())
def test_reported_line_ranges_come_from_the_declared_geometry(scenario_id, tmp_path):
    """报出的行区间必须**逐条**来自真值登记的构造几何（可人工复算）。"""
    dest = _materialize(scenario_id, tmp_path / scenario_id)
    truth = _truth(scenario_id)
    result = _detect(dest, scratch=tmp_path)
    reported = set()
    for conflict in result.conflicts:
        for span in conflict.line_ranges:
            reported.add(tuple(span))
    declared = set(tuple(side["changed"]) for side in truth["geometry"]["sides"])
    assert reported <= declared, (
        "%s 报出了未登记的区间：%s" % (scenario_id, sorted(reported - declared))
    )
    if truth["levels_expected"]:
        assert reported == declared, (
            "%s 该命中的区间被漏报了：%s" % (scenario_id, sorted(declared - reported))
        )
    for conflict in result.conflicts:
        # 见证对的两个区间必须真的分属两侧（否则"谁改了哪一段"就说不清）。
        assert len(conflict.line_ranges) == 2, (
            "%s 的 line_ranges 不是一对：%s" % (scenario_id, conflict.line_ranges)
        )


def test_negative_sample_reports_nothing(tmp_path):
    """负样本（场景 5）空检出，且 `undetermined` 也为空——"没有"与"没看懂"分开。"""
    dest = _materialize("negative_no_overlap", tmp_path / "negative")
    result = _detect(dest, scratch=tmp_path)
    assert result.conflicts == ()
    assert result.counts()["conflicts"] == 0
    assert result.undetermined == ()


def test_subagent_siblings_are_deduplicated_by_derived_from(tmp_path):
    """场景 4：几何与场景 2 完全相同，差异只在 `derived_from` —— 一条都不报。"""
    derived = _materialize("subagent_derived", tmp_path / "derived")
    same_symbol = _materialize("same_symbol_diff_lines", tmp_path / "same_symbol")
    derived_result = _detect(derived, scratch=tmp_path)
    same_symbol_result = _detect(same_symbol, scratch=tmp_path)

    assert same_symbol_result.counts()["conflicts"] == 1, "对照组（场景 2）本身应有一条冲突"
    assert derived_result.conflicts == (), "同一 parent 派生的 subagent 不该产出跨 agent 冲突"
    assert derived_result.counts()["derived_sibling_pairs_skipped"] == 1, (
        "去重必须**有痕迹**：产物里要登记'有一对被派生关系消掉了'"
    )


def test_whole_file_overwrite_hits_all_three_levels_and_exits_one(tmp_path):
    """场景 3：三粒度齐全（含 git 试合并 exit 1），且这是**退出码 1** 的实物。"""
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    code, out, err = _run_cli(dest, scratch=tmp_path)
    assert code == EXIT_CONFLICTS_FOUND, err
    payload = json.loads(out.decode("utf-8"))
    record = payload["conflicts"][0]
    assert record["levels"] == ["file", "block", "symbol"]
    assert record["level"] == "symbol"
    assert record["symbols"] == ["f"]
    assert record["severity"] == config_module.load(
        str(REPO_ROOT / "config" / "radar.toml")
    ).get("severity", "same_symbol")
    assert any(item.startswith("merge-tree:src/alpha.py@exit=1") for item in record["evidence"])


def test_clean_scenario_exits_zero(tmp_path):
    """无冲突 → exit 0（这是"退出码 1 真的有语义"的对照组）。"""
    dest = _materialize("negative_no_overlap", tmp_path / "negative")
    code, out, err = _run_cli(dest, scratch=tmp_path)
    assert code == EXIT_OK, err
    assert json.loads(out.decode("utf-8"))["conflicts"] == []


# --------------------------------------------------------------------------------------
# 计数口径（K12）
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario_id", gen.scenario_ids())
def test_counts_are_a_set_partition_and_a_membership_count(scenario_id, tmp_path):
    dest = _materialize(scenario_id, tmp_path / scenario_id)
    result = _detect(dest, scratch=tmp_path)
    counts = result.counts()
    assert sum(counts["by_max_level"].values()) == len(result.conflicts), "by_max_level 必须是划分"
    assert counts["conflicts"] == len(result.conflicts)
    assert counts["undetermined"] == len(result.undetermined)
    # 成员数 ≥ 条目数：一条记录可以同时命中多级（`by_max_level` 只记最高的一档）。
    for level in ("file", "block", "symbol"):
        assert counts["by_level_membership"][level] >= counts["by_max_level"][level]


def test_membership_count_exceeds_entry_count_when_one_record_hits_two_levels(tmp_path):
    """两栏分开登记的**实物**：场景 2 一条记录命中 file+symbol ⇒ by_max_level 之和 1、成员数 2。"""
    dest = _materialize("same_symbol_diff_lines", tmp_path / "same_symbol")
    counts = _detect(dest, scratch=tmp_path).counts()
    assert counts["by_max_level"] == {"file": 0, "block": 0, "symbol": 1}
    assert counts["by_level_membership"] == {"file": 1, "block": 0, "symbol": 1}


# --------------------------------------------------------------------------------------
# 只读（K4）
# --------------------------------------------------------------------------------------


def test_detect_is_read_only_for_worktree_and_index(tmp_path):
    """跑完 `merge-tree` 后工作区与索引 hash 前后一致（K4 的测试断言）。"""
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    repo = str(Path(dest) / "repo")
    before = _worktree_digest(repo)
    before_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, stdout=subprocess.PIPE
    ).stdout
    before_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, stdout=subprocess.PIPE
    ).stdout

    result = _detect(dest, scratch=tmp_path)
    assert result.counts()["merge_tree_runs"] >= 1, "这条用例要真的跑过 merge-tree 才有意义"

    assert _worktree_digest(repo) == before, "detect 改了工作区或索引（只读纪律被破坏）"
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, stdout=subprocess.PIPE
    ).stdout == before_status
    assert subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, stdout=subprocess.PIPE
    ).stdout == before_branch, "detect 动了 HEAD / 切换了分支"


def test_readonly_boundary_is_disclosed_in_the_product(tmp_path):
    """`--write-tree` 会写对象库——**如实披露**，不得声称"零任何写入"（K4）。"""
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    result = _detect(dest, scratch=tmp_path)
    joined = "\n".join(result.notes)
    assert "merge-tree" in joined and "对象库" in joined
    assert "零任何写入" not in joined


# --------------------------------------------------------------------------------------
# 确定性（双跑逐字节一致 / 零写盘）
# --------------------------------------------------------------------------------------


def test_detect_is_byte_identical_across_two_real_processes(tmp_path):
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    first = _run_cli(dest, scratch=tmp_path / "a")[1]
    second = _run_cli(dest, scratch=tmp_path / "b")[1]
    assert first == second, "同一输入两次真子进程运行的 stdout 不逐字节一致"


def test_detect_out_dir_writes_conflicts_json_with_identical_bytes(tmp_path):
    dest = _materialize("same_symbol_diff_lines", tmp_path / "same_symbol")
    out_dir = tmp_path / "products"
    code, out, err = _run_cli(dest, extra=["--out-dir", str(out_dir)], scratch=tmp_path / "run")
    assert code == EXIT_CONFLICTS_FOUND, err
    written = out_dir / "conflicts.json"
    assert written.is_file()
    raw = written.read_bytes()
    # stdout 在 Windows 上会被文本层翻译成 CRLF；比较前两边都归一（行尾契约另有一条断言）。
    assert raw.replace(b"\r\n", b"\n") == out.replace(b"\r\n", b"\n"), "落盘产物与 stdout 内容不一致"
    assert b"\r\n" not in raw, "落盘产物必须是 LF 行尾（冻结契约）"
    assert raw.endswith(b"}\n"), "冻结契约要求结尾正好一个换行"
    payload = json.loads(raw.decode("utf-8"))
    assert raw.decode("utf-8") == serialize.dumps_json(payload), "产物不满足冻结序列化契约（K2）"


def test_detect_creates_no_file_without_out_dir(tmp_path):
    """零写盘：不给 `--out-dir` 时 CWD 里连一个文件都不该出现。"""
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    _run_cli(dest, scratch=tmp_path / "run", cwd=sandbox)
    assert sorted(os.listdir(str(sandbox))) == [], "detect 在 CWD 落了中间产物（含临时文件）"


# --------------------------------------------------------------------------------------
# K15：阶段表退役（反幽灵）
# --------------------------------------------------------------------------------------


def test_detect_is_not_staged_anymore():
    """`detect` 已交付 ⇒ 不得残留在阶段未就绪表里（幽灵语义）。"""
    assert "detect" in stages.DELIVERED_COMMANDS
    assert "detect" not in stages.STAGE_NOT_READY
