"""`radar scan` 的端到端契约（M1 DoD：归集正确 / 确定性 / K15 退役）。

与 `tests/test_discover.py` 的分工：那边测**字段口径**（不依赖 CLI），这边测**命令契约**——
退出码、`--out-dir` 落盘、双跑逐字节（真子进程，拿的是字节而不是文本）、零中间产物。

纪律（`plan/05` §七）：本文件所有用例都从**合成矩阵物化**出来的临时仓库与临时会话根取值，
显式传 `--claude-root` / `--codex-root`：缺省值会落到真实用户日志，既碰隐私也让断言不稳定。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import stages
from agent_conflict_radar.bench import gen
from agent_conflict_radar.exit_codes import EXIT_ENVIRONMENT, EXIT_OK, EXIT_USAGE

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"

#: 物化出来的场景里，会话时间戳的固定基准 + 偏移（K11）；`--now` 显式传它保证双跑一致。
NOW = "2026-01-01T00:10:00Z"


@pytest.fixture(scope="session")
def _git_or_skip():
    if subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0:
        pytest.skip("找不到 git：物化合成仓库需要 git（缺依赖不是通过）")


def _materialize(scenario_id, dest):
    scenario = gen.scenario_by_id(scenario_id)
    gen.materialize_scenario(scenario, str(dest))
    return dest


def _root_flags(dest, scratch):
    """给**两个源**都传显式根；场景里没有该源时传一个空目录。

    这条不是洁癖：只传一侧的根时，另一侧会走"常见位置探测"落到**真实用户日志**上
    （本机实测过：一次 `scan` 顺手读进了 125 个真实会话文件）。测试必须把探测面钉死，
    否则断言忽大忽小、而且真的碰了用户隐私。
    """
    flags = []
    for name in ("claude", "codex"):
        path = Path(dest) / "sessions" / name
        if not path.is_dir():
            path = Path(scratch) / ("empty-%s" % name)
            path.mkdir(parents=True, exist_ok=True)
        flags += ["--%s-root" % name, str(path)]
    return flags


def _run_scan(dest, extra=(), cwd=None, scratch=None):
    """真子进程跑 `python -m agent_conflict_radar scan`，返回 (退出码, stdout 字节, stderr 文本)。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    scratch = scratch or (Path(dest).parent / "_scratch")
    scratch.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "agent_conflict_radar", "scan", "--repo", str(Path(dest) / "repo")]
    argv += _root_flags(dest, scratch)
    argv += ["--now", NOW] + list(extra)
    completed = subprocess.run(
        argv, cwd=str(cwd or REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------
# 归集正确：逐字段对账（对合成矩阵物化出的真实仓库/会话）
# --------------------------------------------------------------------------------------


def test_scan_reports_worktree_sessions_and_cells_field_by_field(tmp_path, _git_or_skip):
    dest = _materialize("negative_no_overlap", tmp_path / "neg")
    code, out, err = _run_scan(dest)
    assert code == EXIT_OK, err
    payload = json.loads(out.decode("utf-8"))
    assert payload["reference_time"] == NOW
    assert len(payload["worktrees"]) == 1 and payload["worktrees"][0]["is_main"] is True
    sessions = {item["session_id"]: item for item in payload["sessions"]}
    assert set(sessions) == {"sess-radar-0010", "sess-radar-0011"}
    claude, codex = sessions["sess-radar-0010"], sessions["sess-radar-0011"]
    assert claude["source"] == "claude" and claude["git_branch"] == "feat/agent-a"
    assert claude["seq"] == 2, "Claude 首行不是消息行 → seq 必须是消息行行号"
    assert codex["source"] == "codex" and codex["git_branch"] is None
    assert codex["seq"] == 1, "Codex 的元信息在首行 session_meta"
    assert all(item["in_worktree"] for item in payload["active_cells"])
    assert payload["undetermined"] == [] and payload["counts"]["cells_outside_worktree"] == 0


def test_scan_links_subagent_to_parent_session_key(tmp_path, _git_or_skip):
    """场景 4：两个 subagent 的 `derived_from` 必须指向同一父会话的 `session_key`。"""
    dest = _materialize("subagent_derived", tmp_path / "sub")
    code, out, err = _run_scan(dest)
    assert code == EXIT_OK, err
    payload = json.loads(out.decode("utf-8"))
    sessions = {item["session_id"]: item for item in payload["sessions"]}
    assert set(sessions) == {"sess-radar-0007", "sess-radar-0008", "sess-radar-0009"}
    parent_key = sessions["sess-radar-0007"]["session_key"]
    for child in ("sess-radar-0008", "sess-radar-0009"):
        assert sessions[child]["is_subagent"] is True
        assert sessions[child]["derived_from"] == parent_key
    assert sessions["sess-radar-0007"]["is_subagent"] is False
    assert payload["counts"]["subagent_sessions"] == 2


# --------------------------------------------------------------------------------------
# 确定性：真子进程双跑逐字节 + 落盘产物与 stdout 同字节
# --------------------------------------------------------------------------------------


def test_scan_is_byte_identical_across_two_real_processes(tmp_path, _git_or_skip):
    dest = _materialize("same_file_diff_symbol", tmp_path / "det")
    first = _run_scan(dest)
    second = _run_scan(dest)
    assert first[0] == second[0] == EXIT_OK
    assert first[1] == second[1], "同输入双跑 stdout 不逐字节一致（端到端锁一次）"


def test_scan_out_dir_writes_scan_json_with_identical_bytes(tmp_path, _git_or_skip):
    dest = _materialize("threshold_exact", tmp_path / "out")
    out_dir = tmp_path / "products"
    code, out, err = _run_scan(dest, extra=["--out-dir", str(out_dir)])
    assert code == EXIT_OK, err
    written = (out_dir / "scan.json").read_bytes()
    # stdout 是文本流，在 Windows 上会把换行翻成 CRLF，所以比对前先把它归一成 LF；
    # "**落盘**字节恒为 LF" 由下面两条独立断言负责（不能拿 stdout 当基准去验行尾）。
    normalized_stdout = out.replace(b"\r\n", b"\n")
    assert written.replace(b"\r\n", b"\n") == normalized_stdout, (
        "落盘产物必须与 stdout 同内容（同一份序列化契约，K2）"
    )
    assert b"\r\n" not in written, "落盘产物必须是 LF 行尾（冻结契约）"
    assert written.endswith(b"}\n"), "冻结契约要求结尾正好一个换行"


def test_scan_out_dir_pointing_at_a_file_is_usage_error(tmp_path, _git_or_skip):
    dest = _materialize("threshold_exact", tmp_path / "out2")
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("occupied\n", encoding="utf-8")
    code, _out, err = _run_scan(dest, extra=["--out-dir", str(blocker)])
    assert code == EXIT_USAGE
    assert "不是目录" in err


# --------------------------------------------------------------------------------------
# 降级纪律：源缺失 / 非 git 仓库 / undetermined 不改退出码 / 零中间产物
# --------------------------------------------------------------------------------------


def test_scan_missing_explicit_root_is_exit_3(tmp_path, _git_or_skip):
    dest = _materialize("threshold_exact", tmp_path / "miss")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "scan", "--repo", str(Path(dest) / "repo"),
         "--claude-root", str(tmp_path / "no-such-root"), "--now", NOW],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == EXIT_ENVIRONMENT
    assert b"no-such-root" in completed.stderr
    assert completed.stdout == b"", "源缺失时不得吐出任何会被当成结果的产物"


def test_scan_on_non_git_repo_is_exit_3(tmp_path, _git_or_skip):
    plain = tmp_path / "plain"
    plain.mkdir()
    root = tmp_path / "conf" / "claude"
    root.mkdir(parents=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "scan", "--repo", str(plain),
         "--claude-root", str(root), "--now", NOW],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == EXIT_ENVIRONMENT
    assert b"git" in completed.stderr
    assert completed.stdout == b""


def test_scan_success_stays_zero_even_when_something_is_undetermined(tmp_path, _git_or_skip):
    """`undetermined` 是"我们没看懂"，不是"有冲突"——只提示不改码（README 的退出码表如此声明）。"""
    dest = _materialize("threshold_exact", tmp_path / "undet")
    broken = Path(dest) / "sessions" / "claude" / "sess-radar-9999.jsonl"
    with open(str(broken), "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"type":"started","timestamp":"2026-01-01T00:00:00Z"}\n')
    code, out, err = _run_scan(dest)
    assert code == EXIT_OK, err
    payload = json.loads(out.decode("utf-8"))
    assert [item["code"] for item in payload["undetermined"]] == ["no_message_line"]
    assert payload["undetermined"][0]["file"] == "sess-radar-9999.jsonl"


def test_scan_creates_no_intermediate_files_without_out_dir(tmp_path, _git_or_skip):
    """零写盘纪律：不给 `--out-dir` 时**一个文件都不落**（连临时文件都不许有）。"""
    dest = _materialize("threshold_exact", tmp_path / "clean")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    before = sorted(os.listdir(str(sandbox)))
    code, _out, err = _run_scan(dest, cwd=sandbox)
    assert code == EXIT_OK, err
    assert sorted(os.listdir(str(sandbox))) == before == [], "scan 在 CWD 落了中间产物"


# --------------------------------------------------------------------------------------
# `--window` 覆盖：只作用于本次调用的内存视图
# --------------------------------------------------------------------------------------


def test_scan_window_flag_narrows_the_active_cells(tmp_path, _git_or_skip):
    """会话结束于 00:05，`--now 00:10` 下：默认窗口含它，`--window 0` 把它切掉。

    这条同时证明"CLI 的 --window 真的接到了 discover 上"——只有断言值不同才算测到，
    断言一个"改了也没变"的输出等于没测。
    """
    dest = _materialize("threshold_exact", tmp_path / "win")
    code, wide, err = _run_scan(dest)
    assert code == EXIT_OK, err
    code, narrow, err = _run_scan(dest, extra=["--window", "0"])
    assert code == EXIT_OK, err
    assert json.loads(wide.decode("utf-8"))["counts"]["active_cells"] == 2
    assert json.loads(narrow.decode("utf-8"))["counts"]["active_cells"] == 0


def test_scan_window_overrides_only_the_call_view(config_path):
    """覆盖不得写回配置文件（K3：配置文件仍是唯一权威）。"""
    from agent_conflict_radar import config as config_module

    before = Path(config_path).read_bytes()
    cfg = config_module.load(str(config_path))
    narrowed = cfg.with_override("window", "scan_days", 1)
    assert narrowed.get("window", "scan_days") == 1
    assert cfg.get("window", "scan_days") != 1, "原对象被就地改了：覆盖必须返回新视图"
    assert Path(config_path).read_bytes() == before, "覆盖动了配置文件（写盘）"


# --------------------------------------------------------------------------------------
# K15：`scan` 的阶段未就绪断言已退役（同一次提交内四处同步）
# --------------------------------------------------------------------------------------


def test_scan_is_not_staged_anymore():
    """K1 退役纪律：已交付的命令不得残留在阶段未就绪表里（幽灵语义）。"""
    assert "scan" in stages.DELIVERED_COMMANDS
    assert "scan" not in stages.STAGE_NOT_READY
