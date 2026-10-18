"""退出码契约（K1）+ 命令表守卫（K15）。

这组断言是**骨架期最有价值的资产**：题面 §M4 把 `0/1/2/3` 四语义写成硬要求，
M5 起命令面 7/7 全部交付，第五个码 `4 = 阶段未就绪` 已整条退役（K1 四步）。
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
    EXIT_CONFLICTS_FOUND,
    EXIT_ENVIRONMENT,
    EXIT_OK,
    EXIT_USAGE,
)


# --------------------------------------------------------------------------------------
# 退出码集合自洽
# --------------------------------------------------------------------------------------


def test_exit_code_set_is_frozen_and_labelled():
    """M5 起只有四语义：`4` 已随 `bench` 交付整条退役。"""
    assert ALL_EXIT_CODES == (0, 1, 2, 3)
    assert len(set(ALL_EXIT_CODES)) == len(ALL_EXIT_CODES)
    for code in ALL_EXIT_CODES:
        assert code in EXIT_CODE_LABELS


def test_exit_not_ready_constant_is_gone_and_stays_gone():
    """K1 退役纪律的**防复活**判据：常量不得回潮。

    为什么要有这一条：删掉一个常量很容易，难的是下一次有人"顺手加回来"。
    这条断言让复活当场变红——而不是等它悄悄长成第二个不被消费的码。
    """
    import agent_conflict_radar.exit_codes as exit_codes

    assert not hasattr(exit_codes, "EXIT_NOT_READY"), (
        "`EXIT_NOT_READY` 已随 M5 退役（K1 四步）。若确有新的第五语义，"
        "必须五处同步（代码 → 测试 → README → K 表 → 决策记录），而不是只加一个常量"
    )
    # `4` 不得以任何形式回到冻结集合里。
    assert 4 not in exit_codes.ALL_EXIT_CODES


def test_errors_module_has_no_stage_not_ready_class():
    """错误类型侧的防复活：`StageNotReady` 已整条退役，也不许留空壳。"""
    from agent_conflict_radar import errors

    assert not hasattr(errors, "StageNotReady")


def test_stage_tables_have_no_not_ready_bucket():
    """`STAGE_NOT_READY` / `milestone_for` 不得回潮：它们代表的"未交付"状态已不存在。"""
    assert not hasattr(stages, "STAGE_NOT_READY"), (
        "命令面 7/7 已全部交付；重新引入「未就绪」表意味着又有一条命令不产出真实结果"
    )
    assert not hasattr(stages, "milestone_for")


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
# K15 退役纪律（反幽灵）
# --------------------------------------------------------------------------------------


def test_delivered_commands_are_not_staged_anymore():
    """已交付命令不得残留"未交付"痕迹。

    M4 起这条判据是"逐条断言已交付命令不在 `STAGE_NOT_READY` 里"；M5 起那张表整条退役，
    判据升级为**"表本身不存在"**（见上面的 `test_stage_tables_have_no_not_ready_bucket`）。
    这里保留"每条命令都真的被注册"这一半，防止有人删表时顺手把命令也删了。
    """
    import argparse

    from agent_conflict_radar.cli import build_parser

    parser = build_parser()
    registered = set()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            registered = set(action.choices)
    assert registered == set(stages.all_commands())
    for command in stages.DELIVERED_COMMANDS:
        assert command in registered, "%r 在已交付表里但 parser 没有注册" % command


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


def test_selftest_detects_command_table_drift(run_cli, monkeypatch):
    """命令表与 parser 注册面不一致 → 自检必须变红。

    本用例在 M2/M3/M4 是"阶段表自相矛盾"，M5 起判据换成"命令表漂移"——
    因为"未交付"这个状态已经不存在，能制造的真实矛盾只剩"注册了却没登记"这一种。
    """
    from agent_conflict_radar import cli

    monkeypatch.setattr(
        cli.stages, "DELIVERED_COMMANDS", tuple(stages.DELIVERED_COMMANDS) + ("ghost-command",)
    )
    code, _out, err = run_cli(["selftest"])
    assert code == 1
    assert "命令表" in err


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


def test_bench_exit_code_is_not_conflict_semantics(tmp_path, repo_root):
    """`bench` 的 1 与 `detect` 的 1 是**两种语义**：前者"基准未达标"，后者"检出冲突"。

    这条守的是 README 的措辞：把评分失败读成仓库有冲突，会让用户去改自己的代码。
    """
    from agent_conflict_radar import cli as cli_module
    from agent_conflict_radar import config as config_module
    from agent_conflict_radar.bench import score

    cfg = config_module.load(str(repo_root / "config" / "radar.toml"))
    result = score.run_bench(bench_dir=str(repo_root / "bench"), only=["negative_no_overlap"], cfg=cfg)
    text = score.render_summary(result)
    assert "不是“检出冲突”" in text or "不是" in text
    # 退出码常量本身仍是 1（K1 的四语义不动），但语义标注必须出现在人读输出里。
    assert EXIT_CONFLICTS_FOUND == 1


def test_main_never_raises_systemexit(run_cli):
    """`main()` 必须**返回**退出码而不能自己 `sys.exit`，否则测试与复用都会被打断。"""
    for argv in ([], ["--help"], ["--version"], ["nope"], ["config"]):
        code, _out, _err = run_cli(argv)
        assert isinstance(code, int)


def test_main_returns_int_for_version_without_patched_streams(monkeypatch):
    """直接调 `main(["--version"])`（不经 capsys fixture）也应返回 0，不抛 SystemExit。"""
    assert main(["--version"]) == EXIT_OK
