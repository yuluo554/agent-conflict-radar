"""命令表守卫（K15）："已交付命令列表"与"冒烟覆盖的命令列表"必须**并排数一遍**。

SKILL 的原文教训：CI 里那条断言，写下来时是"当时里程碑的契约"，后续里程碑会**合法地**改变它。
若不同步退役，轻则"绿矩阵只是装饰"（命令从未被真跑过），重则四腿同点全红。
本文件把三份清单——`cli.build_parser()` 的注册面、`stages` 的交付表、`tools/verify_offline.py`
的冒烟面——钉在一起。

**M5 起没有"未交付"这第三种状态**：`STAGE_NOT_READY` 整条退役，原文件里那三条
"验阶段未就绪契约"的断言（参数化样本数、期望值必须是 4、消息带里程碑）**整段删掉**，
不是留下空循环——空循环永远绿，那是假门。
"""

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import stages
from agent_conflict_radar.cli import build_parser
from agent_conflict_radar.exit_codes import EXIT_OK


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
    assert registered == declared, "parser 注册面与交付表不一致：%s" % sorted(registered ^ declared)


def test_no_command_is_unclassified():
    """每条注册的命令都必须出现在交付表里——**没有第三种默认状态**。"""
    delivered = set(stages.DELIVERED_COMMANDS)
    assert delivered == set(_subparsers()), (
        "有命令既不在交付表里、也没有任何「未交付」状态可落：%s"
        % sorted(set(_subparsers()) - delivered)
    )


def test_command_order_covers_all_commands():
    assert set(stages.COMMAND_ORDER) == set(stages.all_commands())


def test_all_seven_commands_are_delivered():
    """M5 的 DoD（命令面 7/7）：逐条点名，而不是只断言"集合相等"。"""
    expected = {"config", "selftest", "scan", "intent", "detect", "report", "bench"}
    assert set(stages.DELIVERED_COMMANDS) == expected
    assert len(stages.DELIVERED_COMMANDS) == len(expected), "交付表里有重复项"


@pytest.fixture(scope="module")
def smoke(repo_root, tmp_path_factory):
    """冒烟脚本 + 它构造好的用例表（**模块级共用一份**）。

    `build_cases` 会**物化真 git 仓库**当夹具，所以：① 缺 git 时显式跳过并说明；
    ② 不能在每个用例里各建一次（慢，且两次物化会互相删目录）。
    """
    if shutil.which("git") is None:
        pytest.skip("冒烟的合成夹具要物化 git 仓库：本机没有 git（缺依赖不是通过）")
    tool = _load_smoke_tool(Path(repo_root))
    work = str(tmp_path_factory.mktemp("radar-stage-"))
    return tool, tool.build_cases(work), tool.console_script_cases(work)


def test_smoke_tool_covers_every_delivered_command(smoke):
    """已交付命令要逐条真跑——漏掉一条，"它真的能跑"就没人证。"""
    _tool, cases, console = smoke
    covered = {case.command for case in list(cases) + list(console)}
    missing = sorted(set(stages.DELIVERED_COMMANDS) - covered)
    assert missing == [], "已交付命令在冒烟里没有用例：%s" % missing


def test_smoke_tool_coverage_audit_is_self_consistent_and_falsifiable(smoke):
    """覆盖自检必须返回空，**且**在真的漏掉一条时变红。

    首版这条审计写成了 `DELIVERED | STAGE_NOT_READY == all_commands()`——两侧本就是同一个
    并集，恒真，等于没审。这里补上"抽掉一条用例 → 必须报出来"，把空转的可能堵死。
    """
    tool, cases, console = smoke
    assert tool.audit_command_coverage(cases, console) == []
    # 两条通路都要抽掉：只抽一条时另一条仍覆盖着 scan，审计**不该**报（那才是正确行为）。
    broken = [case for case in cases if case.command != "scan"]
    broken_console = [case for case in console if case.command != "scan"]
    assert len(broken) < len(cases) and len(broken_console) < len(console), "夹具里没有 scan 用例"
    assert any("scan" in item for item in tool.audit_command_coverage(broken, broken_console))


def test_delivered_commands_have_real_contract_expectations(smoke):
    """已交付命令的冒烟期望值必须是**真实契约**（0/1/2/3），不能还停在 exit 4。"""
    _tool, cases, _console = smoke
    for case in cases:
        if case.command in stages.DELIVERED_COMMANDS and case.name.startswith("module:"):
            assert case.expected in (0, 1), (
                "已交付命令 %r 的冒烟期望值应为真实契约（0/1），实为 %s（用例 %r）"
                % (case.command, case.expected, case.name)
            )


def test_smoke_tool_has_no_stage_not_ready_cases(smoke):
    """"阶段未就绪"用例整段退役——残留一条就是"幽灵断言"（永远不会再被满足）。"""
    tool, cases, console = smoke
    leftovers = [case.name for case in list(cases) + list(console) if "阶段未就绪" in case.name]
    assert leftovers == [], "冒烟里仍有阶段未就绪用例：%s" % leftovers
    assert not hasattr(tool, "_staged_argv"), "冒烟脚本仍保留未就绪夹具/参数构造"


def test_console_script_cases_cover_all_commands(smoke):
    """裸 console script 通路也必须逐条覆盖（`python -m` 与裸命令是两条通路）。"""
    _tool, _cases, console = smoke
    covered = {case.command for case in console}
    missing = sorted(set(stages.all_commands()) - covered)
    assert missing == [], "console script 通路未覆盖：%s" % missing
