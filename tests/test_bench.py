"""`radar bench` 的 M5 DoD 对账（评分 / 覆盖度 / 可证伪探活 / 确定性 / 退出码）。

分工：

* `tests/test_bench_matrix.py`：矩阵**生产侧**（生成器 / 真值形态 / 两层 `--check`）；
* 本文件：矩阵**消费侧**——`radar bench` 真的物化 → 跑 scan/intent/detect → 与真值集合对账。

四条纪律：

1. **真值只读**（K9）：评分把实际检出写进 `last_run.json`，**绝不**回写真值；真值里出现
   `observed_*` 仍是红。
2. **集合精确匹配**（K20）：多报 / 漏报都计失败；`--only` 过滤后为空是**用法错误**。
3. **可证伪探活打在消费处**（M5 DoD 硬要求）：把真值里的期望改一位，评分**必须**报未达标；
   探针必须走 `run_bench()` 本身，而不是在测试里另写一份比对。
4. **确定性**（K2/K17）：同一矩阵双跑，`last_run.json` **逐字节一致**；产物里不含本机路径。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import config as config_module
from agent_conflict_radar import serialize, stages
from agent_conflict_radar.bench import gen, score
from agent_conflict_radar.exit_codes import (
    EXIT_CONFLICTS_FOUND,
    EXIT_ENVIRONMENT,
    EXIT_OK,
    EXIT_USAGE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
BENCH_DIR = REPO_ROOT / "bench"


def _git_available():
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="评分要物化真 git 仓库（缺依赖不是通过）")


@pytest.fixture(scope="module")
def cfg():
    return config_module.load(str(REPO_ROOT / "config" / "radar.toml"))


@pytest.fixture(scope="module")
def full_run(cfg):
    """整矩阵跑一次（15 条场景约 20s）；后面多条断言共用同一份结果。"""
    return score.run_bench(bench_dir=str(BENCH_DIR), cfg=cfg)


def _copy_bench(tmp_path) -> Path:
    """把冻结矩阵复制到临时目录（**只改副本**，绝不动仓库里的真值）。"""
    target = tmp_path / "bench"
    shutil.copytree(str(BENCH_DIR), str(target))
    return target


def _rewrite_truth(path: Path, mutate):
    truth = json.loads(path.read_text(encoding="utf-8"))
    mutate(truth)
    path.write_text(serialize.dumps_json(truth), encoding="utf-8")


def _checks(result):
    return dict((check["name"], check) for scenario in result.scenarios for check in scenario["checks"])


def _run_cli(argv, cwd=None, config_path=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    full = [sys.executable, "-m", "agent_conflict_radar"] + list(argv)
    completed = subprocess.run(
        full,
        cwd=str(cwd or REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------
# DoD 主判据：全场景通过
# --------------------------------------------------------------------------------------


def test_every_scenario_passes_on_the_frozen_matrix(full_run):
    """全矩阵逐场景通过：冲突 7 条 + 意图 8 条，一条不漏、一条不多。"""
    payload = full_run.as_dict()
    assert payload["summary"]["scenarios"] == len(gen.scenario_ids()) + len(gen.intent_scenario_ids())
    assert payload["summary"]["failed"] == 0, [
        (item["id"], item.get("error"), [c["name"] for c in item["checks"] if c["verdict"] != "pass"])
        for item in payload["scenarios"]
        if item["verdict"] != "pass"
    ]
    assert full_run.all_passed(), payload["summary"]


def test_every_scenario_is_named_with_expected_actual_and_verdict(full_run):
    """DoD 要求逐场景打印 `期望 / 实际 / 判定`——三样都要在**每条**场景记录里。"""
    for item in full_run.as_dict()["scenarios"]:
        assert item["expected"], "%s 缺期望" % item["id"]
        assert item["actual"], "%s 缺实际" % item["id"]
        assert item["verdict"] in ("pass", "fail")
        assert item["checks"], "%s 没有任何对账项" % item["id"]


def test_human_readable_summary_shows_all_three_columns(full_run):
    text = score.render_summary(full_run)
    for item in full_run.as_dict()["scenarios"]:
        assert item["id"] in text
    assert text.count("期望：") >= len(full_run.scenarios)
    assert text.count("实际：") >= len(full_run.scenarios)
    assert text.count("判定：") >= len(full_run.scenarios)
    assert "结论：PASS（退出码 0）" in text


# --------------------------------------------------------------------------------------
# 覆盖度门槛（消费侧再验一遍）
# --------------------------------------------------------------------------------------


def test_coverage_gate_is_enforced_on_the_consumption_side(full_run):
    checks = dict((check["name"], check) for check in full_run.global_checks)
    for kind in ("conflict", "intent"):
        assert checks["coverage.%s.min_count_by_type" % kind]["verdict"] == "pass"
        assert checks["coverage.%s.missing_types" % kind]["verdict"] == "pass"
        assert checks["coverage.%s.count_by_type" % kind]["verdict"] == "pass"
    assert checks["coverage.conflict.threshold_pair"]["verdict"] == "pass"
    assert checks["manifest.conflict.truth_sha256"]["verdict"] == "pass"


def test_coverage_counts_the_whole_matrix_even_under_only(cfg):
    """`--only` 只影响"跑哪些场景"，不影响覆盖度（否则单跑一条会报"缺类"）。"""
    result = score.run_bench(bench_dir=str(BENCH_DIR), only=["negative_no_overlap"], cfg=cfg)
    assert len(result.scenarios) == 1
    checks = dict((check["name"], check) for check in result.global_checks)
    assert checks["coverage.conflict.min_count_by_type"]["verdict"] == "pass"
    assert result.all_passed()


# --------------------------------------------------------------------------------------
# 可证伪探活（M5 DoD 硬要求：探活打在**消费处**）
# --------------------------------------------------------------------------------------


def test_bench_fails_when_a_truth_expectation_is_changed(tmp_path, cfg):
    """把真值里的期望改一位 → `run_bench()` **必须**报未达标。

    这条是"评分函数真的在比对"的唯一硬证据：如果评分只是遍历真值打印 PASS，
    改期望值它照样绿。探针直接打**消费处**（`run_bench`），不在测试里另写一份比对。
    """
    bench = _copy_bench(tmp_path)

    def mutate(truth):
        truth["symbols_expected"] = ["g"]  # 原值 ["f"]

    _rewrite_truth(bench / "scenarios" / "same_symbol_diff_lines" / "truth.json", mutate)
    result = score.run_bench(bench_dir=str(bench), cfg=cfg)
    failed = [item for item in result.scenarios if item["verdict"] != "pass"]
    assert [item["id"] for item in failed] == ["same_symbol_diff_lines"], (
        "改掉一条真值的符号期望后，评分必须点名那一条失败；实际失败：%s"
        % [item["id"] for item in result.scenarios if item["verdict"] != "pass"]
    )
    checks = dict((check["name"], check) for check in failed[0]["checks"])
    assert checks["detect.symbols"]["verdict"] == "fail"
    assert checks["detect.symbols"]["missing"] == ["g"], "期望里的 g 是漏报"
    assert checks["detect.symbols"]["extra"] == ["f"], "实际检出的 f 是多报"
    assert not result.all_passed()


def test_bench_fails_when_truth_has_an_extra_expected_object(tmp_path, cfg):
    """多报方向也要能被抓到：真值多要一条不该报的对象 → 评分必须红。"""
    bench = _copy_bench(tmp_path)

    def mutate(truth):
        truth["objects_expected"].append({"path": "src/alpha.py", "symbol": "g"})

    _rewrite_truth(bench / "scenarios" / "same_file_diff_symbol" / "truth.json", mutate)
    result = score.run_bench(bench_dir=str(bench), cfg=cfg)
    failed = [item for item in result.scenarios if item["verdict"] != "pass"]
    assert [item["id"] for item in failed] == ["same_file_diff_symbol"]
    checks = dict((check["name"], check) for check in failed[0]["checks"])
    assert checks["detect.objects"]["verdict"] == "fail"
    assert checks["detect.objects"]["missing"] == [["src/alpha.py", "g"]]


def test_bench_fails_when_a_forbidden_object_is_reported(tmp_path, cfg):
    """反向样例：真值里禁止的对象被检出 → 评分必须红（防"适用域写错永远不红"）。"""
    bench = _copy_bench(tmp_path)

    def mutate(truth):
        # 把该场景的期望改成"必须报 g"，于是实际不报 = 漏报；同时把 g 放进 forbidden。
        truth["objects_forbidden"].append({"path": "src/alpha.py", "symbol": "f"})

    _rewrite_truth(bench / "scenarios" / "same_symbol_diff_lines" / "truth.json", mutate)
    result = score.run_bench(bench_dir=str(bench), cfg=cfg)
    failed = [item for item in result.scenarios if item["verdict"] != "pass"]
    assert [item["id"] for item in failed] == ["same_symbol_diff_lines"]
    checks = dict((check["name"], check) for check in failed[0]["checks"])
    assert checks["detect.forbidden_objects"]["verdict"] == "fail"


def test_bench_fails_when_intent_count_expectation_drifts(tmp_path, cfg):
    """意图侧同一探活：改 `counts_expected` 的一位 → 评分必须红。"""
    bench = _copy_bench(tmp_path)

    def mutate(truth):
        truth["counts_expected"]["write_ops"] = 99

    _rewrite_truth(bench / "intents" / "intent_edit_exact" / "truth.json", mutate)
    result = score.run_bench(bench_dir=str(bench), cfg=cfg)
    failed = [item for item in result.scenarios if item["verdict"] != "pass"]
    assert [item["id"] for item in failed] == ["intent_edit_exact"]
    checks = dict((check["name"], check) for check in failed[0]["checks"])
    assert checks["intent.counts.write_ops"]["verdict"] == "fail"


def test_manifest_sha_mismatch_is_caught_by_the_consumer(tmp_path, cfg):
    """真值被改而台账 sha 不动 → 覆盖度复核必须报出来（K9：真值禁手改）。"""
    bench = _copy_bench(tmp_path)

    def mutate(truth):
        truth["notes"] = "手改一行"

    _rewrite_truth(bench / "scenarios" / "negative_no_overlap" / "truth.json", mutate)
    result = score.run_bench(bench_dir=str(bench), cfg=cfg)
    checks = dict((check["name"], check) for check in result.global_checks)
    assert checks["manifest.conflict.truth_sha256"]["verdict"] == "fail"
    assert checks["manifest.conflict.truth_sha256"]["extra"] == ["negative_no_overlap"]


# --------------------------------------------------------------------------------------
# 退出码语义（K1：0/1/2/3 各有实物）
# --------------------------------------------------------------------------------------


def test_full_matrix_exits_zero(tmp_path):
    code, out, err = _run_cli(["bench", "--out-dir", str(tmp_path / "out")])
    assert code == EXIT_OK, err
    assert "结论：PASS" in out.decode("utf-8", errors="replace")
    assert (tmp_path / "out" / "last_run.json").is_file()


def test_failing_matrix_exits_one_and_says_it_is_not_conflicts(tmp_path, cfg):
    """任一场景失败 → 1。**措辞**必须点明 1 是"基准未达标"，不是"检出冲突"。"""
    bench = _copy_bench(tmp_path)

    def mutate(truth):
        truth["levels_expected"] = ["file", "block"]

    _rewrite_truth(bench / "scenarios" / "same_file_diff_symbol" / "truth.json", mutate)
    result = score.run_bench(bench_dir=str(bench), cfg=cfg)
    text = score.render_summary(result)
    assert not result.all_passed()
    assert "结论：FAIL" in text
    assert "不是" in text and "检出冲突" in text


def test_unknown_only_id_is_a_usage_error(tmp_path):
    code, out, err = _run_cli(["bench", "--only", "definitely-not-a-scenario"])
    assert code == EXIT_USAGE
    assert "用法错误" in err
    assert out == b"", "用法错误不得向 stdout 吐出任何会被读成结果的产物"


def test_empty_only_after_filtering_is_a_usage_error():
    """`--only ","` 过滤后为空 → 用法错误，不是"零条通过"（exit 0）。

    CLI 侧 `--only ","` 会被 `split(",")` 成 `["", ""]`；这里直接按同一形态调 API。
    """
    with pytest.raises(Exception) as excinfo:
        score.run_bench(bench_dir=str(BENCH_DIR), only=["", " "])
    assert "过滤后为空" in str(excinfo.value)


def test_only_comma_on_the_cli_is_a_usage_error():
    code, out, err = _run_cli(["bench", "--only", ","])
    assert code == EXIT_USAGE
    assert "过滤后为空" in err
    assert out == b""


def test_missing_bench_dir_is_an_environment_error(tmp_path):
    code, _out, err = _run_cli(["bench", "--bench-dir", str(tmp_path / "no-such-bench")])
    assert code == EXIT_ENVIRONMENT
    assert "矩阵目录" in err


def test_missing_git_is_an_environment_error(tmp_path):
    """`bench` 在 `_NEEDS_GIT` 里：PATH 置空目录 → exit 3。"""
    import tempfile

    empty_path = tempfile.mkdtemp(prefix="radar-bench-nopath-")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    env["PATH"] = empty_path
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "bench", "--only", "negative_no_overlap"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == EXIT_ENVIRONMENT
    assert b"git" in completed.stderr


# --------------------------------------------------------------------------------------
# `last_run.json`：K2 冻结契约 + K17 机器无关 + 确定性
# --------------------------------------------------------------------------------------


def test_last_run_obeys_the_frozen_serialization_contract(tmp_path, full_run):
    path = score.write_last_run(str(tmp_path), full_run)
    raw = Path(path).read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw.decode("utf-8") == serialize.dumps_json(json.loads(raw.decode("utf-8")))


def test_last_run_is_byte_identical_across_two_runs(tmp_path, cfg):
    """双跑逐字节一致：参考时刻是固定常量，评分不读系统时钟。"""
    first = score.run_bench(bench_dir=str(BENCH_DIR), only=["same_symbol_diff_lines"], cfg=cfg)
    second = score.run_bench(bench_dir=str(BENCH_DIR), only=["same_symbol_diff_lines"], cfg=cfg)
    path_a = Path(score.write_last_run(str(tmp_path / "a"), first)).read_bytes()
    path_b = Path(score.write_last_run(str(tmp_path / "b"), second)).read_bytes()
    assert path_a == path_b


def test_last_run_has_no_machine_paths_or_timestamps(tmp_path, full_run):
    """K17：`bench/` 下的产物必须机器无关——否则干净 clone 上就是"另一份产物"。"""
    text = Path(score.write_last_run(str(tmp_path), full_run)).read_text(encoding="utf-8")
    for marker in gen.machine_path_markers():
        assert marker not in text, "last_run.json 含本机路径片段 %r" % marker
    assert str(REPO_ROOT).replace("\\", "/") not in text
    assert str(REPO_ROOT) not in text


def test_last_run_records_no_observed_fields_back_into_truth(full_run):
    """K9：评分结果只写 `last_run.json`；真值文件在评分前后**逐字节相同**。"""
    before = dict(
        (path, path.read_bytes())
        for path in sorted(BENCH_DIR.rglob("truth.json"))
    )
    score.run_bench(bench_dir=str(BENCH_DIR), only=["negative_no_overlap"])
    after = dict(
        (path, path.read_bytes())
        for path in sorted(BENCH_DIR.rglob("truth.json"))
    )
    assert before == after, "评分动了真值文件（K9：实际检出绝不回写真值）"


def test_score_module_has_no_policy_numeric_literals():
    """K3/K5：评分模块里的数值只允许结构性 0/1（阈值一律从 config 读）。

    复用 `test_config_literals.py` 里的**同一个扫描器**（不另写一份比对逻辑），
    但按文件路径加载——测试模块之间不互相 import 成包（README 门的 import 面判据会拦）。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "radar_test_config_literals", str(Path(__file__).with_name("test_config_literals.py"))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    path = SRC_ROOT / "agent_conflict_radar" / "bench" / "score.py"
    assert module.scan_numeric_literals(path, "bench/score.py") == []


# --------------------------------------------------------------------------------------
# 命令面（K15：bench 已交付，且不再有"未就绪"）
# --------------------------------------------------------------------------------------


def test_bench_is_delivered_and_not_staged():
    assert "bench" in stages.DELIVERED_COMMANDS
    assert not hasattr(stages, "STAGE_NOT_READY")


def test_bench_help_is_normal_help_not_a_gate():
    code, out, _err = _run_cli(["bench", "--help"])
    assert code == EXIT_OK
    text = out.decode("utf-8", errors="replace")
    assert "--bench-dir" in text and "--only" in text
    assert "尚未交付" not in text


def test_bench_writes_last_run_into_the_matrix_dir_by_default(tmp_path, cfg):
    """默认落**矩阵目录**的 `last_run.json`；CWD 里一个文件都不落（零污染）。

    用矩阵**副本**跑：默认写盘会真的落进矩阵目录，直接跑仓库里那份会让每次测试都改工作区
    （测试污染仓库）。副本同时证明"默认位置跟随 `--bench-dir`"，不是写死仓库根。
    """
    bench = _copy_bench(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    code, _out, err = _run_cli(
        ["bench", "--bench-dir", str(bench), "--only", "negative_no_overlap"], cwd=cwd
    )
    assert code == EXIT_OK, err
    assert os.listdir(str(cwd)) == []
    assert (bench / "last_run.json").is_file(), "默认产物应落在矩阵目录"

    payload = json.loads((bench / "last_run.json").read_text(encoding="utf-8"))
    assert payload["summary"]["all_passed"] is True
    assert payload["only"] == ["negative_no_overlap"]
