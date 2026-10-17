"""退出码契约（K1）+ 阶段守卫（K15）。

这组断言是**骨架期最有价值的资产**：题面 §M4 把 `0/1/2/3` 四语义写成硬要求，
而"未交付命令必须显式拦截（不伪造空结果）"是本题判定类工具的正确性底线。
"""

import shutil
import subprocess
import sys

import pytest

from agent_conflict_radar import stages
from agent_conflict_radar.cli import main
from agent_conflict_radar.exit_codes import (
    ALL_EXIT_CODES,
    EXIT_CODE_LABELS,
    EXIT_ENVIRONMENT,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_USAGE,
)


# --------------------------------------------------------------------------------------
# 退出码集合自洽
# --------------------------------------------------------------------------------------


def test_exit_code_set_is_frozen_and_labelled():
    assert ALL_EXIT_CODES == (0, 1, 2, 3, 4)
    assert len(set(ALL_EXIT_CODES)) == len(ALL_EXIT_CODES)
    for code in ALL_EXIT_CODES:
        assert code in EXIT_CODE_LABELS


# --------------------------------------------------------------------------------------
# 0：已交付命令
# --------------------------------------------------------------------------------------


def test_version_returns_zero(run_cli):
    code, out, _err = run_cli(["--version"])
    assert code == EXIT_OK
    assert "agent-conflict-radar" in out


def test_help_returns_zero(run_cli):
    code, out, _err = run_cli(["--help"])
    assert code == EXIT_OK
    assert "退出码" in out


def test_config_command_prints_effective_config(run_cli):
    code, out, _err = run_cli(["config"])
    assert code == EXIT_OK
    payload = __import__("json").loads(out)
    assert payload["schema_version"] == 1
    assert payload["values"]["window"]["active_minutes"] > 0
    assert str(payload["source_path"]).endswith("radar.toml")


def test_selftest_returns_zero(run_cli):
    code, out, _err = run_cli(["selftest"])
    assert code == EXIT_OK
    assert "自检通过" in out


# --------------------------------------------------------------------------------------
# 2：用法错误
# --------------------------------------------------------------------------------------


def test_missing_subcommand_is_usage_error(run_cli):
    code, _out, err = run_cli([])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_unknown_subcommand_is_usage_error(run_cli):
    code, _out, err = run_cli(["definitely-not-a-command"])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_unknown_flag_is_usage_error(run_cli, tmp_path):
    code, _out, err = run_cli(["scan", "--repo", str(tmp_path), "--nope"])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_unknown_report_format_is_rejected(run_cli):
    """未知产物格式必须**显式拒绝**，不能静默喂一个默认格式（SKILL 产物 format 条）。"""
    code, _out, err = run_cli(["report", "--format", "pdf"])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_nonexistent_repo_path_is_usage_error(run_cli, tmp_path):
    code, _out, err = run_cli(["scan", "--repo", str(tmp_path / "no-such-dir")])
    assert code == EXIT_USAGE
    assert "用法错误" in err


# --------------------------------------------------------------------------------------
# 3：依赖或环境缺失
# --------------------------------------------------------------------------------------


def test_missing_git_is_environment_error(run_cli, tmp_path, monkeypatch):
    from agent_conflict_radar import gitio

    monkeypatch.setattr(gitio.shutil, "which", lambda _name: None)
    code, _out, err = run_cli(["scan", "--repo", str(tmp_path)])
    assert code == EXIT_ENVIRONMENT
    assert "git" in err


def test_missing_config_file_is_environment_error(run_cli, tmp_path):
    code, _out, err = run_cli(["--config", str(tmp_path / "nope.toml"), "config"])
    assert code == EXIT_ENVIRONMENT
    assert "配置" in err


def test_broken_config_is_environment_error(run_cli, make_config):
    path = make_config(drop_keys=["window.active_minutes"])
    code, _out, err = run_cli(["--config", str(path), "config"])
    assert code == EXIT_ENVIRONMENT
    assert "配置" in err


# --------------------------------------------------------------------------------------
# 4：阶段未就绪（骨架期专用）
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", sorted(stages.STAGE_NOT_READY))
def test_staged_commands_return_not_ready(run_cli, command, tmp_path):
    argv = [command]
    if "--repo" in _flags_of(command):
        argv += ["--repo", str(tmp_path)]
    code, out, err = run_cli(argv)
    assert code == EXIT_NOT_READY, "命令 %r 应显式拦截（exit 4）" % command
    assert "尚未交付" in err
    assert "不会返回空结果" in err, "拦截消息必须写清'不伪造空结果'，否则读者会以为只是没输出"
    assert out == "", "阶段未就绪不得向 stdout 吐出任何（会被当成结果的）产物"
    assert stages.STAGE_NOT_READY[command] in err, "消息里应带出计划里程碑"


def _flags_of(command):
    import argparse

    from agent_conflict_radar.cli import build_parser

    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            sub = action.choices.get(command)
            if sub is None:
                return set()
            flags = set()
            for sub_action in sub._actions:  # noqa: SLF001
                flags.update(sub_action.option_strings)
            return flags
    return set()


def test_delivered_commands_are_not_staged_anymore():
    """K1 退役纪律：**每一条**已交付命令都不得残留在阶段未就绪表里（幽灵语义）。

    判据写成"对 DELIVERED_COMMANDS 逐条断言"，而不是挑几个命令名硬编码：
    下一棒把 `intent` 挪过来时，这条断言自动覆盖它，不需要有人记得回来加一行。
    """
    for command in stages.DELIVERED_COMMANDS:
        assert command not in stages.STAGE_NOT_READY, "%r 已交付却仍留在阶段未就绪表里" % command


# --------------------------------------------------------------------------------------
# 自检的可证伪性（SKILL「selftest 可证伪」条）
# --------------------------------------------------------------------------------------


def test_selftest_is_falsifiable_by_bad_parameter(run_cli, make_config):
    """把配置里的数值改成非法值 → `selftest` 必须返回 1。

    判别 = "我删掉自检逻辑，测试会红吗？"——这条用**真的把被测行为弄坏**的方式验证，
    而不是"把测试改名"这种无效对照。
    """

    def mutate(text):
        return text.replace("active_minutes = 30", "active_minutes = 0")

    path = make_config(mutate=mutate)
    code, _out, err = run_cli(["--config", str(path), "selftest"])
    assert code == 1
    assert "自检未通过" in err
    assert "active_minutes" in err


def test_selftest_detects_broken_serialize_contract(run_cli, monkeypatch):
    """把序列化契约弄坏 → 自检必须变红（证明检查 3 不是空转）。"""
    from agent_conflict_radar import cli

    monkeypatch.setattr(cli.serialize, "dumps_json", lambda payload: "{}\n")
    code, _out, err = run_cli(["selftest"])
    assert code == 1
    assert "序列化契约" in err


def test_selftest_detects_stage_table_overlap(run_cli, monkeypatch):
    """阶段表自相矛盾（同一命令既已交付又未就绪）→ 自检必须变红。"""
    from agent_conflict_radar import cli

    # 从**当前仍在** STAGE_NOT_READY 里的命令挑一个来制造重叠——不要硬编码命令名：
    # 每棒交付一条命令都会让硬编码的名字失效（M2 交付 `intent` 时本用例当场变红，正是这个原因）。
    still_staged = sorted(stages.STAGE_NOT_READY)
    assert still_staged, "阶段未就绪表已空：本用例没有可用样本（里程碑全交付后应整条退役）"
    monkeypatch.setattr(
        cli.stages, "DELIVERED_COMMANDS", tuple(stages.DELIVERED_COMMANDS) + (still_staged[0],)
    )
    code, _out, err = run_cli(["selftest"])
    assert code == 1
    assert "阶段表" in err


# --------------------------------------------------------------------------------------
# 真命令通路（子进程）：证明"用户敲得动"
# --------------------------------------------------------------------------------------


def test_module_entrypoint_in_subprocess(repo_root):
    """`python -m agent_conflict_radar --version` 真跑一次（入口必须是绝对导入的薄模块）。"""
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "--version"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert completed.returncode == EXIT_OK
    assert b"agent-conflict-radar" in completed.stdout


@pytest.mark.skipif(shutil.which("radar") is None, reason="console script 未安装（README 快速开始可装）")
def test_console_script_runs_scan_for_real(repo_root, tmp_path):
    """裸 console script 通路真跑一次 `scan`。

    这里原本断言的是"未交付 → exit 4"；`scan` 于 M1 交付后，**同一批断言必须同步退役**
    （K15 第②步）。新的判据是"命令真的执行到了环境校验"：给一个**不是 git 仓库**的目录，
    必须 exit 3 且不吐产物——比"exit 4"更强（它证明命令已经接线、且不伪造空结果）。
    """
    completed = subprocess.run(
        ["radar", "scan", "--repo", str(tmp_path)],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert completed.returncode == EXIT_ENVIRONMENT
    assert "git" in completed.stdout.decode("utf-8", errors="replace")


def test_main_never_raises_systemexit(run_cli):
    """`main()` 必须**返回**退出码而不能自己 `sys.exit`，否则测试与复用都会被打断。"""
    for argv in ([], ["--help"], ["--version"], ["nope"], ["config"]):
        code, _out, _err = run_cli(argv)
        assert isinstance(code, int)


def test_main_returns_int_for_version_without_patched_streams(monkeypatch):
    """直接调 `main(["--version"])`（不经 capsys fixture）也应返回 0，不抛 SystemExit。"""
    assert main(["--version"]) == EXIT_OK
