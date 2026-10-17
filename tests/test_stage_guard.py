"""阶段守卫（K15）："已交付命令列表"与"冒烟覆盖的命令列表"必须**并排数一遍**。

SKILL 的原文教训：CI 里那条断言，写下来时是"当时里程碑的契约"，后续里程碑会**合法地**改变它。
若不同步退役，轻则"绿矩阵只是装饰"（命令从未被真跑过），重则四腿同点全红。
本文件把三份清单——`cli.build_parser()` 的注册面、`stages` 的两张表、`tools/verify_offline.py`
的冒烟面——钉在一起。
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import stages
from agent_conflict_radar.cli import build_parser
from agent_conflict_radar.exit_codes import EXIT_NOT_READY, EXIT_OK


def _subparsers():
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return action.choices
    raise AssertionError("CLI 里找不到子命令注册表：parser 结构变了，本门禁需要同步")


def _load_smoke_tool(repo_root: Path):
    """按文件路径加载 `tools/verify_offline.py`（它不是包的一部分，不能 import 名字）。"""
    path = Path(repo_root) / "tools" / "verify_offline.py"
    spec = importlib.util.spec_from_file_location("radar_verify_offline", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["radar_verify_offline"] = module
    spec.loader.exec_module(module)
    return module


def test_registered_commands_match_stage_tables():
    registered = set(_subparsers())
    declared = set(stages.all_commands())
    assert registered == declared, "parser 注册面与 stages 表不一致：%s" % sorted(registered ^ declared)


def test_no_command_is_unclassified():
    """每个命令要么已交付、要么在阶段未就绪表里——**没有第三种默认状态**。"""
    delivered = set(stages.DELIVERED_COMMANDS)
    staged = set(stages.STAGE_NOT_READY)
    assert delivered & staged == set(), "同一命令不能既已交付又未就绪：%s" % sorted(delivered & staged)
    assert delivered | staged == set(_subparsers())


def test_stage_milestones_are_named():
    for command, milestone in stages.STAGE_NOT_READY.items():
        assert milestone, "%r 未标注计划里程碑" % command
        assert milestone.upper().startswith("M"), "%r 的里程碑写法不规范：%r" % (command, milestone)


def test_command_order_covers_all_commands():
    assert set(stages.COMMAND_ORDER) == set(stages.all_commands())


@pytest.mark.parametrize("command", sorted(stages.STAGE_NOT_READY))
def test_smoke_tool_covers_every_staged_command(repo_root, command):
    """冒烟脚本必须真跑到每条阶段未就绪命令（不只是"表里有"）。"""
    tool = _load_smoke_tool(Path(repo_root))
    import tempfile

    cases = tool.build_cases(tempfile.mkdtemp(prefix="radar-stage-"))
    covered = {case.command for case in cases}
    assert command in covered, "冒烟未覆盖命令 %r；已覆盖：%s" % (command, sorted(covered))


def test_smoke_tool_coverage_audit_is_self_consistent(repo_root):
    """冒烟脚本自带的覆盖自检必须返回空（它就是"并排数一遍"的那条命令）。"""
    tool = _load_smoke_tool(Path(repo_root))
    import tempfile

    assert tool.audit_command_coverage(tempfile.mkdtemp(prefix="radar-stage-")) == []


def test_smoke_tool_expected_codes_track_stage_table(repo_root):
    """冒烟里对阶段未就绪命令的期望值必须是 `EXIT_NOT_READY`。

    这条是"断言过期"的守门：某条命令交付时，若只改了 `stages` 而没改冒烟期望值，
    这里会先红——而不是等 CI 四腿同点全红。
    """
    tool = _load_smoke_tool(Path(repo_root))
    import tempfile

    cases = tool.build_cases(tempfile.mkdtemp(prefix="radar-stage-"))
    # 只挑"验阶段未就绪契约"的用例：用法错误用例（如 `report --format pdf` → 2）属另一条判据，
    # 把它们一起断言进来就是"断言张冠李戴"（会同时断言了所有判据）。
    staged_case_codes = {}
    for case in cases:
        if case.command in stages.STAGE_NOT_READY and case.name.endswith("(阶段未就绪)"):
            staged_case_codes.setdefault(case.command, set()).add(case.expected)
    assert staged_case_codes, "冒烟里没有覆盖任何阶段未就绪命令"
    for command, codes in staged_case_codes.items():
        assert codes <= {EXIT_NOT_READY}, (
            "命令 %r 仍在阶段未就绪表里，但冒烟的期望值已改成 %s——"
            "要么把它移出 STAGE_NOT_READY 并补真实契约冒烟，要么改回 exit 4（K15）" % (command, sorted(codes))
        )


def test_delivered_commands_have_zero_expectation(repo_root):
    tool = _load_smoke_tool(Path(repo_root))
    import tempfile

    cases = tool.build_cases(tempfile.mkdtemp(prefix="radar-stage-"))
    for case in cases:
        if case.command in stages.DELIVERED_COMMANDS and case.name.startswith("module:") and "阶段未就绪" not in case.name:
            assert case.expected in (EXIT_OK, 1), (
                "已交付命令 %r 的冒烟期望值应为真实契约（0/1），实为 %s（用例 %r）"
                % (case.command, case.expected, case.name)
            )


def test_console_script_cases_cover_all_commands(repo_root):
    """裸 console script 通路也必须逐条覆盖（`python -m` 与裸命令是两条通路）。"""
    tool = _load_smoke_tool(Path(repo_root))
    import tempfile

    cases = tool.console_script_cases(tempfile.mkdtemp(prefix="radar-stage-"))
    covered = {case.command for case in cases}
    missing = sorted(set(stages.all_commands()) - covered)
    assert missing == [], "console script 通路未覆盖：%s" % missing
