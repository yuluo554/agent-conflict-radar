"""`intent.py` 的字段级对账（M2 DoD：解析对账 / 不猜测 / 幂等合并 / 确定性）。

分工：

* `tests/test_intent_parse.py`：纯函数级（patch 解析 / 锚点定位 / 三分法），不碰 git；
* 本文件：**端到端**——从合成矩阵物化出真 git 仓库 + 真会话日志，跑 `radar intent`，
  再与 `bench/intents/<id>/truth.json` 逐条对账。

纪律（`plan/05` §七）：所有用例都显式传两侧会话根。缺省值会走"常见位置探测"落到真实用户日志上
（M1 实测踩过：一次 `scan` 顺手读进 125 个真实会话文件）。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import stages
from agent_conflict_radar.bench import gen
from agent_conflict_radar.exit_codes import EXIT_ENVIRONMENT, EXIT_OK

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
BENCH_DIR = REPO_ROOT / "bench"

#: 物化出来的场景里，会话时间戳的固定基准 + 偏移（K11）；显式传 `--now` 保证双跑一致。
NOW = "2026-01-01T00:10:00Z"


def _git_available():
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="物化合成仓库需要 git（缺依赖不是通过）")


def _materialize_intent(scenario_id, dest):
    gen.materialize_intent_scenario(gen.intent_scenario_by_id(scenario_id), str(dest))
    return dest


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


def _run_intent(dest, extra=(), cwd=None, scratch=None, repo=None, pre=()):
    """真子进程跑 `python -m agent_conflict_radar intent`，返回 (退出码, stdout 字节, stderr 文本)。

    `pre` 是**写在子命令之前**的全局选项（如 `--config`）——位置写错会被 argparse 拒绝，
    这本身也是一条指令面契约（README 的写法是 `radar --config path config`）。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    scratch = scratch or (Path(dest).parent / "_scratch")
    scratch.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "agent_conflict_radar"] + list(pre) + [
        "intent",
        "--repo", str(repo or (Path(dest) / "repo")),
    ]
    argv += _root_flags(dest, scratch)
    argv += ["--now", NOW] + list(extra)
    completed = subprocess.run(
        argv, cwd=str(cwd or REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", errors="replace")


def _payload(dest, extra=(), pre=()):
    code, out, err = _run_intent(dest, extra=extra, pre=pre)
    assert code == EXIT_OK, err
    return json.loads(out.decode("utf-8"))


def _truth(scenario_id):
    path = BENCH_DIR / "intents" / scenario_id / "truth.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# 冻结产物存在性与布局（M2 的矩阵本体）
# --------------------------------------------------------------------------------------


def test_intent_matrix_is_frozen_with_truth_for_every_scenario():
    manifest = json.loads((BENCH_DIR / "intents" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator_version"] == gen.GENERATOR_VERSION
    assert sorted(entry["id"] for entry in manifest["scenarios"]) == sorted(gen.intent_scenario_ids())
    for entry in manifest["scenarios"]:
        sdir = BENCH_DIR / "intents" / entry["id"]
        assert (sdir / "truth.json").is_file(), "缺少意图真值：%s" % entry["id"]
        assert (sdir / "repo" / "src" / "alpha.py").is_file(), "缺少基线仓库：%s" % entry["id"]
        assert list((sdir / "sessions").rglob("*.jsonl")), "缺少会话日志：%s" % entry["id"]


def test_intent_manifest_coverage_has_no_missing_types():
    manifest = json.loads((BENCH_DIR / "intents" / "manifest.json").read_text(encoding="utf-8"))
    coverage = manifest["coverage"]
    assert coverage["missing_types"] == [], "意图矩阵覆盖度缺类：%s" % coverage["missing_types"]
    for name, minimum in coverage["min_count_by_type"].items():
        assert coverage["count_by_type"].get(name, 0) >= minimum, "%s 未达最低条数" % name
    assert coverage["counting_unit"].startswith("用例条目数"), "计数口径必须先声明（K12）"


def test_intent_truth_has_no_observed_fields_and_counts_partition():
    """K9 + K12：真值只存输入与期望；三分法必须是**集合划分**（恒等式）。"""
    for scenario_id in gen.intent_scenario_ids():
        truth = _truth(scenario_id)
        flattened = json.dumps(truth, ensure_ascii=False)
        assert "observed_" not in flattened, "%s 出现 observed_* 字段" % scenario_id
        counts = truth["counts_expected"]
        assert counts["exact"] + counts["coarse"] + counts["unknown"] == counts["entries"], (
            "%s 的三分法计数不守恒" % scenario_id
        )
        assert counts["unknown_write_ops"] >= counts["unknown"]


# --------------------------------------------------------------------------------------
# 逐场景对账（解析结果 == 真值）
# --------------------------------------------------------------------------------------


def _compare_entries(actual, expected):
    """按 `(path, session_id, precision)` 集合精确匹配（多报/漏报均失败）。

    `actual` 是产物条目（会话标识在 `session_ids[]` 里），`expected` 是真值条目（`session_id`）。
    产物侧一个条目可以聚合**多个会话**，真值侧则逐会话登记——所以产物侧展开成多条键再比。
    """
    def expand(items):
        out = {}
        for item in items:
            ids = item.get("session_ids") or ([item["session_id"]] if item.get("session_id") else [None])
            for sid in ids:
                out[(item["path"], sid or "", item["precision"])] = (item, sid)
        return out

    actual_map = expand(actual)
    expected_map = expand(expected)
    assert sorted(actual_map) == sorted(expected_map), (
        "条目集合与真值不符：多出 %r / 缺少 %r"
        % (sorted(set(actual_map) - set(expected_map)), sorted(set(expected_map) - set(actual_map)))
    )
    for k in sorted(expected_map):
        got, _sid = actual_map[k]
        want, _wsid = expected_map[k]
        assert [list(item) for item in got["changed_ranges"]] == want["changed_ranges"], (
            "%r 的改动区间不符：%r ≠ %r" % (k, got["changed_ranges"], want["changed_ranges"])
        )
        assert got["ranges_source"] == want["ranges_source"], "%r 的区间来源不符" % (k,)
        assert got["approximate"] is want["approximate"], "%r 的 approximate 不符" % (k,)
        assert got["last_write_ts"] == want["last_write_ts"], (
            "%r 的 last_write_ts 不符：%r ≠ %r（同会话同文件多次写入应取组内最大值）"
            % (k, got["last_write_ts"], want["last_write_ts"])
        )
        expected_records = 1 if want["session_id"] else 0
        assert len(got["writes"]) == expected_records, (
            "%r 的逐会话记录数不符：%d ≠ %d（有会话来源的条目应恰有一条逐会话记录；"
            "只有磁盘来源的条目没有会话记录）" % (k, len(got["writes"]), expected_records)
        )
        merged_ops = sum(len(item["evidence"]) for item in got["writes"])
        assert merged_ops == want["write_ops"], (
            "%r 的写操作条数不符：逐会话证据 %d 条 ≠ 真值 %r（合并后的证据必须逐条保留）"
            % (k, merged_ops, want["write_ops"])
        )
        assert sorted(got["reasons"]) == sorted(want["reasons"]), (
            "%r 的降级原因不符：%r ≠ %r" % (k, got["reasons"], want["reasons"])
        )


@pytest.mark.parametrize("scenario_id", gen.intent_scenario_ids())
def test_scenario_parses_to_the_frozen_truth(tmp_path, scenario_id):
    """每条意图场景：解析结果必须与冻结真值逐条一致（含 `coarse` / `unknown` 分支）。

    真值把"有路径的条目"（`entries_expected`）与"未定位的写操作"（`unknown_expected`）分开登记，
    因为两者的计数口径不同（K12）：前者是**条目数**，后者是**写操作条数**。
    """
    dest = _materialize_intent(scenario_id, tmp_path / scenario_id)
    payload = _payload(dest)
    truth = _truth(scenario_id)
    located = [item for item in payload["entries"] if item["path"]]
    _compare_entries(located, truth["entries_expected"])

    unknown = [item for item in payload["entries"] if not item["path"]]
    assert len(unknown) == truth["unknown_expected"]["entries"], (
        "场景 %s 的 unknown 条目数不符：%r ≠ %r"
        % (scenario_id, len(unknown), truth["unknown_expected"]["entries"])
    )
    if unknown:
        assert sorted(unknown[0]["reasons"]) == sorted(truth["unknown_expected"]["reasons"])
        assert unknown[0]["precision"] == "unknown" and unknown[0]["changed_ranges"] == []

    # 计数也要对：三分法条目数 + 未定位写操作条数（后者是**写操作条数**，口径不同）。
    for name in ("entries", "exact", "coarse", "unknown", "unknown_write_ops", "write_ops", "multi_edit_ops"):
        assert payload["counts"][name] == truth["counts_expected"][name], (
            "场景 %s 的 counts.%s 不符：%r ≠ %r" % (scenario_id, name, payload["counts"][name], truth["counts_expected"][name])
        )


def test_noise_tools_do_not_produce_entries(tmp_path):
    """反例：同一条会话里的 `Read` 与不含 patch 标记的 `exec` **不得**产出条目。

    这两条反例与正例在**同一份日志**里，所以"整个文件没有写操作"这种蒙对方式在这里不成立。
    """
    for scenario_id in ("intent_edit_exact", "intent_codex_exec_patch"):
        dest = _materialize_intent(scenario_id, tmp_path / scenario_id)
        payload = _payload(dest)
        paths = [item["path"] for item in payload["entries"]]
        assert "src/filler.py" not in paths
        assert payload["counts"]["write_ops"] == 1, (
            "场景 %s 的写操作条数应为 1（反例不得被认成写操作）：%r" % (scenario_id, payload["counts"])
        )


def test_forbidden_paths_never_appear(tmp_path):
    for scenario_id in gen.intent_scenario_ids():
        truth = _truth(scenario_id)
        if not truth["paths_forbidden"]:
            continue
        dest = _materialize_intent(scenario_id, tmp_path / ("f-" + scenario_id))
        payload = _payload(dest)
        seen = {item["path"] for item in payload["entries"]}
        assert not (seen & set(truth["paths_forbidden"])), (
            "场景 %s 报出了反向样例 %r" % (scenario_id, sorted(seen & set(truth["paths_forbidden"])))
        )


# --------------------------------------------------------------------------------------
# 三分法与降级纪律（逐条可指认）
# --------------------------------------------------------------------------------------


def test_multi_write_same_file_is_merged_with_max_timestamp(tmp_path):
    """**幂等合并**（M2 DoD）：同一会话在同一文件上的两次写入合并成一条记录，
    区间取并集、`last_write_ts` 取组内最大值；而 `write_ops` 仍是 2（两个口径分开登记）。

    这条不能用"两个会话各改一处"替代：那种情况下合并与不合并的结果一样，
    "按时间序合并 + 取最大值"这两条语义**根本不会被测到**。
    """
    dest = _materialize_intent("intent_multi_write_merge", tmp_path / "merge")
    payload = _payload(dest)
    assert payload["counts"]["entries"] == 1, "同会话同文件的两条写入必须合并成一条条目"
    assert payload["counts"]["write_ops"] == 2, "写操作条数仍是 2（口径不同，不能跟着条目数一起变）"
    entry = payload["entries"][0]
    assert entry["path"] == "src/alpha.py"
    assert [list(item) for item in entry["changed_ranges"]] == [[2, 2], [9, 9]], "区间应取并集且有序"
    assert entry["last_write_ts"] == "2026-01-01T00:02:00Z", "last_write_ts 必须取组内最大值（第二次写入）"
    assert len(entry["writes"]) == 1, "逐会话记录也应合并（两次写入属于同一会话）"
    assert len(entry["writes"][0]["evidence"]) == 2, "两次写入的证据都要保留（可回指到两条工具调用）"


def test_replace_all_is_coarse_and_carries_no_range(tmp_path):
    """`replace_all=True` → `coarse`，且**没有**"看起来精确"的区间。"""
    dest = _materialize_intent("intent_replace_all_coarse", tmp_path / "ra")
    payload = _payload(dest)
    entry = payload["entries"][0]
    assert entry["precision"] == "coarse"
    assert entry["changed_ranges"] == []
    assert "replace_all" in entry["reasons"]


def test_ambiguous_anchor_degrades_and_names_the_hit_count(tmp_path):
    """锚点两处命中 → 降级，并**点名命中次数**（不许挑第一个）。"""
    dest = _materialize_intent("intent_ambiguous_anchor_coarse", tmp_path / "amb")
    payload = _payload(dest)
    entry = payload["entries"][0]
    assert entry["precision"] == "coarse"
    assert entry["changed_ranges"] == []
    assert entry["reasons"] == ["anchor_ambiguous#2"]


def test_multi_edit_is_unknown_with_a_note_not_silently_supported(tmp_path):
    """`MultiEdit` 本机 0 次出现 → `unknown` + 计注记；同一会话的另一条 `Edit` 仍精确落点。"""
    dest = _materialize_intent("intent_multi_edit_unknown", tmp_path / "me")
    payload = _payload(dest)
    unknown = [item for item in payload["entries"] if item["precision"] == "unknown"]
    assert len(unknown) == 1
    assert unknown[0]["path"] == ""
    assert unknown[0]["reasons"] == ["multi_edit_unsupported"]
    assert payload["counts"]["multi_edit_ops"] == 1
    exact = [item for item in payload["entries"] if item["precision"] == "exact"]
    assert len(exact) == 1 and exact[0]["path"] == "src/alpha.py"


def test_non_python_files_are_approximate_and_carry_no_symbol_field(tmp_path):
    """R4 闭环：非 Python → `approximate=True`；产物里**不出现任何符号字段**。"""
    dest = _materialize_intent("intent_write_and_non_python", tmp_path / "np")
    payload = _payload(dest)
    entry = [item for item in payload["entries"] if item["path"] == "docs/notes.md"][0]
    assert entry["approximate"] is True
    assert entry["changed_ranges"] == [[3, 3]], "行区间近似仍要给出（它可复算）"
    blob = json.dumps(payload, ensure_ascii=False)
    assert '"symbol"' not in blob and '"symbols"' not in blob, (
        "R4 未闭环前不得在产物里出现符号字段（否则等于对外宣称已支持）"
    )
    py_entry = [item for item in payload["entries"] if item["path"] == "src/alpha.py"][0]
    assert py_entry["approximate"] is False


def test_write_effective_range_is_recomputed_against_the_baseline(tmp_path):
    """整文件 `Write` 的区间是**有效改动**（逐行比对基线），不是"整个文件"。

    这条同时证明我们真的读了 `HEAD` 基线：若拿工作区顶替，基线就会等于写后内容，区间会空。
    """
    dest = _materialize_intent("intent_write_and_non_python", tmp_path / "wr")
    payload = _payload(dest)
    entry = [item for item in payload["entries"] if item["path"] == "src/alpha.py"][0]
    assert entry["changed_ranges"] == [[2, 2]], "整文件 Write 只改了第 2 行，区间就只能是 [2,2]"


# --------------------------------------------------------------------------------------
# 磁盘对账：磁盘是事实
# --------------------------------------------------------------------------------------


def test_disk_diff_wins_and_disagreement_is_named(tmp_path):
    """磁盘与会话不一致 → 以磁盘为准 + 点名 `disk_and_session_disagree`（不悄悄改数字）。"""
    dest = _materialize_intent("intent_disk_wins", tmp_path / "dw")
    payload = _payload(dest)
    by_path = dict((item["path"], item) for item in payload["entries"])
    alpha = by_path["src/alpha.py"]
    assert alpha["changed_ranges"] == [[9, 9]], "磁盘说第 9 行 → 必须取磁盘"
    assert alpha["ranges_source"] == "disk"
    assert "disk_and_session_disagree" in alpha["reasons"]
    # 会话侧的原值必须保留在 writes[] 里（"谁说了什么"可回指）。
    assert alpha["writes"][0]["changed_ranges"] == [[2, 2]]
    # 只有磁盘来源的改动（没有会话）也要出现在条目里。
    assert by_path["src/beta.py"]["sessions"] == []
    assert payload["counts"]["entries_without_session"] == 1


def test_staged_and_unstaged_diffs_are_both_consulted(tmp_path):
    """`git diff` 与 `git diff --cached` **两条通路都真跑**：一条改动只进了索引、一条只在工作区。"""
    dest = _materialize_intent("intent_disk_wins", tmp_path / "st")
    repo = Path(dest) / "repo"
    unstaged = subprocess.run(
        ["git", "diff", "--name-only"], cwd=str(repo), stdout=subprocess.PIPE
    ).stdout.decode("utf-8").split()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=str(repo), stdout=subprocess.PIPE
    ).stdout.decode("utf-8").split()
    assert unstaged == ["src/beta.py"], "夹具应有一条只在工作区的改动"
    assert staged == ["src/alpha.py"], "夹具应有一条只在索引的改动"
    payload = _payload(dest)
    assert set(item["path"] for item in payload["entries"]) == {"src/alpha.py", "src/beta.py"}


# --------------------------------------------------------------------------------------
# 确定性 / 零写盘 / 落盘产物
# --------------------------------------------------------------------------------------


def test_intent_is_byte_identical_across_two_real_processes(tmp_path):
    dest = _materialize_intent("intent_disk_wins", tmp_path / "det")
    first = _run_intent(dest)
    second = _run_intent(dest)
    assert first[0] == second[0] == EXIT_OK, first[2]
    assert first[1] == second[1], "同输入双跑 stdout 不逐字节一致（端到端锁一次）"


def test_intent_out_dir_writes_intent_json_with_identical_bytes(tmp_path):
    dest = _materialize_intent("intent_disk_wins", tmp_path / "out")
    out_dir = tmp_path / "products"
    code, out, err = _run_intent(dest, extra=["--out-dir", str(out_dir)])
    assert code == EXIT_OK, err
    written = (out_dir / "intent.json").read_bytes()
    assert written.replace(b"\r\n", b"\n") == out.replace(b"\r\n", b"\n")
    assert b"\r\n" not in written, "落盘产物必须是 LF 行尾（冻结契约）"
    assert written.endswith(b"}\n"), "冻结契约要求结尾正好一个换行"


def test_intent_creates_no_intermediate_files_without_out_dir(tmp_path):
    """零写盘纪律：不给 `--out-dir` 时**一个文件都不落**（连临时文件都不许有）。"""
    dest = _materialize_intent("intent_edit_exact", tmp_path / "clean")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    code, _out, err = _run_intent(dest, cwd=sandbox)
    assert code == EXIT_OK, err
    assert sorted(os.listdir(str(sandbox))) == [], "intent 在 CWD 落了中间产物"


# --------------------------------------------------------------------------------------
# 环境与降级：源缺失 / 非 git / 会话在 worktree 之外
# --------------------------------------------------------------------------------------


def test_missing_explicit_root_is_exit_3_with_empty_stdout(tmp_path):
    dest = _materialize_intent("intent_edit_exact", tmp_path / "miss")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "intent", "--repo", str(Path(dest) / "repo"),
         "--claude-root", str(tmp_path / "no-such-root"), "--codex-root", str(tmp_path / "no-such-2"),
         "--now", NOW],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == EXIT_ENVIRONMENT
    assert b"no-such-root" in completed.stderr
    assert completed.stdout == b"", "源缺失时不得吐出任何会被当成结果的产物"


def test_non_git_repo_is_exit_3(tmp_path):
    """`--repo` 不在 git 仓库内 → exit 3（与 `scan` 同口径：试合并/磁盘对账都依赖 git）。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    root = tmp_path / "conf" / "claude"
    root.mkdir(parents=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "intent", "--repo", str(plain),
         "--claude-root", str(root), "--now", NOW],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == EXIT_ENVIRONMENT
    assert completed.stdout == b""


def test_session_cwd_outside_every_worktree_is_coarse_not_a_crash(tmp_path):
    """会话 `cwd` 落在任何 worktree 之外（本机 37 个改文件的会话里 30 个如此）→
    只做会话侧抽取、`coarse`、不崩、不伪造区间、不丢会话。"""
    dest = _materialize_intent("intent_edit_exact", tmp_path / "outside")
    session_file = sorted((Path(dest) / "sessions" / "claude").glob("*.jsonl"))[0]
    text = session_file.read_text(encoding="utf-8")
    outside = str(tmp_path / "elsewhere" / "demo-radar-beta").replace("\\", "/")
    replaced = text.replace(str((Path(dest) / "repo").resolve()).replace("\\", "/"), outside)
    replaced = replaced.replace(str(Path(dest) / "repo").replace("\\", "/"), outside)
    assert replaced != text, "测试自身失配：会话里的 cwd 没被替换掉（夹具形态变了？）"
    session_file.write_text(replaced, encoding="utf-8")

    payload = _payload(dest)
    assert payload["counts"]["cells_outside_worktree"] == 1
    entry = payload["entries"][0]
    assert entry["precision"] == "coarse", "工作区之外不得声称精确"
    assert entry["changed_ranges"] == [], "不得伪造区间"
    assert entry["sessions"], "会话不得被丢弃"
    assert "not_in_worktree" in entry["reasons"]
    assert any("不在任何已知 worktree 内" in note for note in payload["notes"])


def test_overlong_session_line_is_reported_as_undetermined(tmp_path):
    """超长行 → `undetermined(line_too_long)`（不静默截断）。"""
    dest = _materialize_intent("intent_edit_exact", tmp_path / "long")
    session_file = sorted((Path(dest) / "sessions" / "claude").glob("*.jsonl"))[0]
    with open(str(session_file), "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"type":"assistant","blob":"%s"}\n' % ("x" * 5000))

    cfg_text = (REPO_ROOT / "config" / "radar.toml").read_text(encoding="utf-8")
    mutated = cfg_text.replace("max_line_bytes = 2000000", "max_line_bytes = 2000")
    assert mutated != cfg_text
    config_path = tmp_path / "radar.toml"
    config_path.write_text(mutated, encoding="utf-8")

    code, out, err = _run_intent(dest, pre=["--config", str(config_path)])
    assert code == EXIT_OK, err
    payload = json.loads(out.decode("utf-8"))
    assert [item["code"] for item in payload["undetermined"]] == ["line_too_long"]
    assert payload["undetermined"][0]["file"].endswith(".jsonl")


# --------------------------------------------------------------------------------------
# K15：`intent` 的阶段未就绪断言已退役
# --------------------------------------------------------------------------------------


def test_intent_is_not_staged_anymore():
    assert "intent" in stages.DELIVERED_COMMANDS
    assert "intent" not in stages.STAGE_NOT_READY


def test_intent_help_mentions_no_milestone_gate(tmp_path):
    """交付后的 `radar intent --help` 必须是正常帮助（exit 0），不是阶段拦截。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "intent", "--help"],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == EXIT_OK
    assert b"--claude-root" in completed.stdout
