"""离线冒烟（CI 与本地共用）。`python tools/verify_offline.py [--strict]`

为什么要有这个脚本（而不是把 shell 塞进 workflow）：内联 heredoc 受缩进与行尾影响易碎，
落成 `tools/` 脚本可本地逐条复跑、可被测试引用；CI 步骤只调它一条命令。

覆盖四件事：

1. **退出码契约**（K1）：每条已交付命令 + 每条阶段未就绪命令 + 用法错误 + 依赖缺失。
   ⚠️ 纪律（K15）：某条命令交付时，**同一次提交里**改 `stages.py` 把它的名字挪到已交付集合，
   本脚本的期望值随之从"4"变成真实契约——四处（stages / CLI / README / 本脚本）不同步就会
   出现"断言过期"，那会让 CI 四腿同点全红，或者让命令从未被真跑过。
2. **两条调用通路**：`python -m agent_conflict_radar` 与裸 `radar`（`sys.path` 来源不同，
   只跑前者会漏掉"我们的包没进安装面"这类缺陷）。
3. **零网络导入面审计**：源码里不得出现网络类标准库/第三方库的导入。
4. **合成矩阵的生成器自检**（K10）：`--check` 两层断言 + 提交 sha 复算（这是"矩阵可重建"的门）。

判定只看**退出码**（不看输出文本）：不同平台的输出编码不同（cp1252 / cp936 / utf-8），
把文本写进断言会让冒烟变成"环境差异探测器"而不是"契约探测器"。

**夹具纪律**（`plan/05` §七）：凡是"自动发现本机数据"的参数，冒烟一律显式传临时目录——
`scan` 的两条用例都显式给 `--claude-root` / `--codex-root`，否则缺省探测会真的去读用户
本机日志（本机实测过：漏传一侧即读进 125 个真实会话文件）。
"""

import argparse
import ast
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(REPO_ROOT, "src")

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from agent_conflict_radar import stages  # noqa: E402  (需要先把 src 放上 sys.path)
from agent_conflict_radar.cli import _ensure_utf8_stdio, build_parser  # noqa: E402
from agent_conflict_radar.exit_codes import (  # noqa: E402
    EXIT_CONFLICTS_FOUND,
    EXIT_ENVIRONMENT,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_USAGE,
)


def subparser_flags(command: str) -> set:
    """从 CLI parser 反射某个子命令接受的旗标集合。

    为什么要反射而不是照抄一份：照抄的清单会与 parser 漂移，而且"旗标写在错的命令行上"
    这类张冠李戴的错误照抄清单看不出来。
    """
    import argparse

    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse 没有公开的枚举接口
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            sub = action.choices.get(command)
            if sub is None:
                return set()
            flags = set()
            for sub_action in sub._actions:  # noqa: SLF001
                flags.update(sub_action.option_strings)
            return flags
    return set()


def _repo_flag_if_supported(command: str, repo_dir: str) -> List[str]:
    """只在子命令真的接受 `--repo` 时才追加（否则是"旗标张冠李戴"，会打出假红）。"""
    if "--repo" in subparser_flags(command):
        return ["--repo", repo_dir]
    return []

#: 禁止导入的网络类模块（"纯本地零上传"的导入面证据）。
NETWORK_MODULES = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "urllib2",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "requests",
        "httpx",
        "aiohttp",
        "websocket",
        "websockets",
    }
)


class Case(object):
    """一条冒烟用例。

    `command` 显式声明"这条用例在验哪个子命令"，**不从 argv 里猜**——argv 里可能出现
    `--config` 这类与子命令同名或形状相似的 token（如 `--config x config`），
    用 token 扫描会把"配置错误用例"误当成"验 config 命令"的用例（张冠李戴）。
    """

    def __init__(self, name, argv, expected, cwd=None, path_override=None, note="", command=None):
        self.name = name
        self.argv = list(argv)
        self.expected = expected
        self.cwd = cwd
        self.path_override = path_override
        self.note = note
        self.command = command


def _child_env(path_override: Optional[str] = None) -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    parts = [SRC_ROOT] + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if path_override is not None:
        env["PATH"] = path_override
    return env


def _run(argv: Sequence[str], cwd: str, path_override: Optional[str] = None) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=_child_env(path_override),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
    except OSError as exc:
        return 127, "无法启动：%s" % exc
    # 只作诊断展示；判定用退出码，避免把平台编码差异写进断言。
    return completed.returncode, completed.stdout.decode("utf-8", errors="replace")


def _module_argv(*args: str) -> List[str]:
    return [sys.executable, "-m", "agent_conflict_radar"] + list(args)


#: 夹具缓存：`build_cases` 与 `console_script_cases` 共用同一份（否则会重复物化并互相删目录）。
_SCAN_FIXTURES: dict = {}
_INTENT_FIXTURES: dict = {}
_DETECT_FIXTURES: dict = {}


def _scan_fixture(scratch: str) -> Tuple[str, str, str]:
    """造一份 `scan` 的合成夹具：真 git 仓库 + 两个会话根（含合成日志）。

    用生成器物化（`agent_conflict_radar.bench.gen`）而不是手写夹具：手写的会与
    冻结矩阵各自演化，冒烟就成了"验一个不存在的场景"。这条同时把"生成器产出能被生产侧
    解析"这条链路在 CI 里真跑一遍。
    """
    import agent_conflict_radar.bench.gen as bench_gen

    if scratch in _SCAN_FIXTURES:
        return _SCAN_FIXTURES[scratch]
    scenario = bench_gen.scenario_by_id("negative_no_overlap")
    dest = os.path.join(scratch, "scan-fixture")
    bench_gen.materialize_scenario(scenario, dest)
    _SCAN_FIXTURES[scratch] = (
        os.path.join(dest, "repo"),
        os.path.join(dest, "sessions", "claude"),
        os.path.join(dest, "sessions", "codex"),
    )
    return _SCAN_FIXTURES[scratch]


def _intent_fixture(scratch: str) -> Tuple[str, str, str]:
    """造一份 `intent` 的合成夹具（M2）：真 git 仓库（含 staged/unstaged 未提交改动）+ 会话根。

    选 `intent_disk_wins`：它同时有"会话侧区间"与"磁盘侧区间"，并且两条改动一条进索引、
    一条只进工作区——冒烟因此顺带验到 `git diff` 与 `git diff --cached` **两条通路**。
    """
    import agent_conflict_radar.bench.gen as bench_gen

    if scratch in _INTENT_FIXTURES:
        return _INTENT_FIXTURES[scratch]
    scenario = bench_gen.intent_scenario_by_id("intent_disk_wins")
    dest = os.path.join(scratch, "intent-fixture")
    bench_gen.materialize_intent_scenario(scenario, dest)
    claude = os.path.join(dest, "sessions", "claude")
    codex = os.path.join(dest, "sessions", "codex")
    if not os.path.isdir(codex):
        # 场景里没有该源时传一个**空目录**（缺省探测会落到真实用户日志上，见 plan/05 §七）。
        codex = os.path.join(scratch, "intent-empty-codex")
        os.makedirs(codex, exist_ok=True)
    _INTENT_FIXTURES[scratch] = (os.path.join(dest, "repo"), claude, codex)
    return _INTENT_FIXTURES[scratch]


def _detect_fixture(scratch: str) -> Tuple[str, str, str]:
    """造一份 `detect` 的合成夹具（M3）：真 git 仓库（两条已提交分支）+ 会话根。

    选 `whole_file_overwrite`：它是矩阵里**唯一**让 `git merge-tree` 真的报冲突（exit 1）的场景，
    三粒度齐全（file / block / symbol），因此冒烟顺带验到"区块级真的跑了"与"退出码 1 真的会用"。
    """
    import agent_conflict_radar.bench.gen as bench_gen

    if scratch in _DETECT_FIXTURES:
        return _DETECT_FIXTURES[scratch]
    scenario = bench_gen.scenario_by_id("whole_file_overwrite")
    dest = os.path.join(scratch, "detect-fixture")
    bench_gen.materialize_scenario(scenario, dest)
    claude = os.path.join(dest, "sessions", "claude")
    codex = os.path.join(dest, "sessions", "codex")
    if not os.path.isdir(codex):
        # 场景里没有该源时传一个**空目录**（缺省探测会落到真实用户日志上，见 plan/05 §七）。
        codex = os.path.join(scratch, "detect-empty-codex")
        os.makedirs(codex, exist_ok=True)
    _DETECT_FIXTURES[scratch] = (os.path.join(dest, "repo"), claude, codex)
    return _DETECT_FIXTURES[scratch]


def _scan_argv(fixture, *prefix):
    repo, claude_root, codex_root = fixture
    return list(prefix) + [
        "scan", "--repo", repo,
        "--claude-root", claude_root,
        "--codex-root", codex_root,
        "--now", "2026-01-01T00:10:00Z",
    ]


def _intent_argv(fixture, *prefix):
    repo, claude_root, codex_root = fixture
    return list(prefix) + [
        "intent", "--repo", repo,
        "--claude-root", claude_root,
        "--codex-root", codex_root,
        "--now", "2026-01-01T00:10:00Z",
    ]


def _detect_argv(fixture, *prefix):
    repo, claude_root, codex_root = fixture
    return list(prefix) + [
        "detect", "--repo", repo,
        "--claude-root", claude_root,
        "--codex-root", codex_root,
        "--now", "2026-01-01T00:10:00Z",
    ]


def build_cases(repo_dir: str) -> List[Case]:
    cases = []

    # ---- 已交付命令（模块通路）----
    cases.append(Case("module:--version", _module_argv("--version"), EXIT_OK, cwd=repo_dir, command="--version"))
    cases.append(
        Case(
            "module:config",
            _module_argv("--config", os.path.join(REPO_ROOT, "config", "radar.toml"), "config"),
            EXIT_OK,
            cwd=repo_dir,
            command="config",
            note="显式 --config，校验全局选项写在子命令之前的形态",
        )
    )
    cases.append(Case("module:selftest", _module_argv("selftest"), EXIT_OK, cwd=repo_dir, command="selftest"))

    # ---- 已交付：scan（M1；合成夹具，显式传两侧 root + --now）----
    fixture = _scan_fixture(repo_dir)
    cases.append(
        Case(
            "module:scan(合成夹具)",
            _scan_argv(fixture, *_module_argv()),
            EXIT_OK,
            cwd=repo_dir,
            command="scan",
            note="成功恒为 0（undetermined 只提示不改码）；夹具用生成器物化，两条通路同一份",
        )
    )
    cases.append(
        Case(
            "env:scan 会话源缺失",
            _module_argv("scan", "--repo", fixture[0], "--claude-root", os.path.join(repo_dir, "no-such-root"),
                         "--codex-root", fixture[2], "--now", "2026-01-01T00:10:00Z"),
            EXIT_ENVIRONMENT,
            cwd=repo_dir,
            command="scan",
            note="显式指定的会话根不存在 → exit 3，不得退化成 exit 0 空结果",
        )
    )

    # ---- 已交付：intent（M2；合成夹具含 staged/unstaged 未提交改动）----
    intent_fixture = _intent_fixture(repo_dir)
    cases.append(
        Case(
            "module:intent(合成夹具)",
            _intent_argv(intent_fixture, *_module_argv()),
            EXIT_OK,
            cwd=repo_dir,
            command="intent",
            note="成功恒为 0（coarse/unknown 落点只提示不改码）；夹具含一条 staged + 一条 unstaged 改动",
        )
    )
    cases.append(
        Case(
            "env:intent 会话源缺失",
            _module_argv("intent", "--repo", intent_fixture[0],
                         "--claude-root", os.path.join(repo_dir, "no-such-root"),
                         "--codex-root", intent_fixture[2], "--now", "2026-01-01T00:10:00Z"),
            EXIT_ENVIRONMENT,
            cwd=repo_dir,
            command="intent",
            note="显式指定的会话根不存在 → exit 3，不得退化成 exit 0 空结果",
        )
    )

    # ---- 已交付：detect（M3；合成夹具**真的有冲突**，区块级真跑 merge-tree）----
    detect_fixture = _detect_fixture(repo_dir)
    cases.append(
        Case(
            "module:detect(合成夹具)",
            _detect_argv(detect_fixture, *_module_argv()),
            EXIT_CONFLICTS_FOUND,
            cwd=repo_dir,
            command="detect",
            note="有冲突 → exit 1（第一条真的会用 1 的命令）；夹具选 whole_file_overwrite（三粒度齐全）",
        )
    )
    cases.append(
        Case(
            "env:detect 会话源缺失",
            _module_argv("detect", "--repo", detect_fixture[0],
                         "--claude-root", os.path.join(repo_dir, "no-such-root"),
                         "--codex-root", detect_fixture[2], "--now", "2026-01-01T00:10:00Z"),
            EXIT_ENVIRONMENT,
            cwd=repo_dir,
            command="detect",
            note="显式指定的会话根不存在 → exit 3，不得退化成 exit 0 空结果",
        )
    )

    # ---- 阶段未就绪命令（当前契约：exit 4）----
    for command in sorted(stages.STAGE_NOT_READY):
        argv = _module_argv(command) + _repo_flag_if_supported(command, repo_dir)
        cases.append(
            Case(
                "module:%s(阶段未就绪)" % command,
                argv,
                EXIT_NOT_READY,
                cwd=repo_dir,
                command=command,
                note="交付该命令时本期望值必须同步改为真实契约（K15）",
            )
        )

    # ---- 用法错误（2）----
    cases.append(
        Case("usage:未知子命令", _module_argv("definitely-not-a-command"), EXIT_USAGE, cwd=repo_dir, command="--none--")
    )
    for command in ("scan", "intent", "detect", "report"):
        cases.append(
            Case(
                "usage:%s 未知旗标" % command,
                _module_argv(command, "--nope"),
                EXIT_USAGE,
                cwd=repo_dir,
                command=command,
            )
        )
    cases.append(
        Case("usage:未知产物格式", _module_argv("report", "--format", "pdf"), EXIT_USAGE, cwd=repo_dir, command="report")
    )
    cases.append(
        Case(
            "usage:repo 路径不存在",
            _module_argv("scan", "--repo", os.path.join(repo_dir, "no-such-dir")),
            EXIT_USAGE,
            cwd=repo_dir,
            command="scan",
        )
    )

    # ---- 依赖缺失（3）：PATH 指向空目录 → 找不到 git ----
    empty_path = tempfile.mkdtemp(prefix="radar-nopath-")
    cases.append(
        Case(
            "env:git 不可用",
            _module_argv("scan", "--repo", repo_dir),
            EXIT_ENVIRONMENT,
            cwd=repo_dir,
            path_override=empty_path,
            command="scan",
            note="PATH 置空目录；缺 git 必须 exit 3，不得静默当'无冲突'",
        )
    )

    # ---- 坏配置（3）----
    bad_config = os.path.join(tempfile.mkdtemp(prefix="radar-badcfg-"), "radar.toml")
    with open(bad_config, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("[window]\nactive_minutes = 30\n")
    cases.append(
        Case(
            "env:配置缺键",
            _module_argv("--config", bad_config, "config"),
            EXIT_ENVIRONMENT,
            cwd=repo_dir,
            command="config",
            note="缺键必须报错（不回落默认值，K3）",
        )
    )
    return cases


def console_script_cases(repo_dir: str) -> List[Case]:
    """裸 console script 通路（`radar …`）。只在已安装时有意义。"""
    fixture = _scan_fixture(repo_dir)
    intent_fixture = _intent_fixture(repo_dir)
    detect_fixture = _detect_fixture(repo_dir)
    cases = [
        Case("console:--version", ["radar", "--version"], EXIT_OK, cwd=repo_dir, command="--version"),
        Case("console:config", ["radar", "config"], EXIT_OK, cwd=repo_dir, command="config"),
        Case("console:selftest", ["radar", "selftest"], EXIT_OK, cwd=repo_dir, command="selftest"),
        Case("console:scan(合成夹具)", _scan_argv(fixture, "radar"), EXIT_OK, cwd=repo_dir, command="scan"),
        Case(
            "console:intent(合成夹具)",
            _intent_argv(intent_fixture, "radar"),
            EXIT_OK,
            cwd=repo_dir,
            command="intent",
        ),
        Case(
            "console:detect(合成夹具)",
            _detect_argv(detect_fixture, "radar"),
            EXIT_CONFLICTS_FOUND,
            cwd=repo_dir,
            command="detect",
        ),
    ]
    for command in sorted(stages.STAGE_NOT_READY):
        argv = ["radar", command] + _repo_flag_if_supported(command, repo_dir)
        cases.append(
            Case("console:%s(阶段未就绪)" % command, argv, EXIT_NOT_READY, cwd=repo_dir, command=command)
        )
    return cases


def audit_zero_network() -> List[str]:
    """导入面审计：源码里不得出现网络类模块。"""
    failures = []
    scanned = 0
    package_root = os.path.join(SRC_ROOT, "agent_conflict_radar")
    for dirpath, _dirnames, filenames in os.walk(package_root):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            scanned += 1
            full = os.path.join(dirpath, filename)
            with open(full, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=full)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    top = name.split(".")[0]
                    if top in NETWORK_MODULES:
                        failures.append(
                            "%s 导入了网络模块 %r（与「纯本地零上传」声明冲突）"
                            % (os.path.relpath(full, REPO_ROOT), name)
                        )
    if scanned == 0:
        failures.append("导入面审计没有扫描到任何文件（扫描面为空的审计等于没审）")
    return failures


def audit_command_coverage(cases: Sequence[Case], console_cases: Sequence[Case]) -> List[str]:
    """命令覆盖自检：每条命令都必须有**真跑它的用例**（并排数一遍）。

    ⚠️ 这条审计的判据不能写成 `DELIVERED | STAGE_NOT_READY == all_commands()`——那两侧
    本就是同一个并集，恒等式恒真，等于没审（首版就是这样，属"假门"）。真判据是
    "用例表里有没有 `command == <某命令>` 的条目"，它会在**漏掉用例**时真红。
    """
    covered = {case.command for case in list(cases) + list(console_cases)}
    failures = []
    missing = sorted(set(stages.all_commands()) - covered)
    if missing:
        failures.append("冒烟没有任何用例真跑这些命令：%s" % missing)
    for command in sorted(covered - set(stages.all_commands()) - {"--version", "--none--", "--gen-check--"}):
        failures.append("冒烟里有用例声明了 stages 里不存在的命令：%r" % command)
    return failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="agent-conflict-radar 离线冒烟")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="console script（裸 radar）缺失即视为失败（CI 用；本地未安装时可省略）",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    temp_repo = tempfile.mkdtemp(prefix="radar-smoke-repo-")
    failures = []
    results = []

    try:
        cases = build_cases(temp_repo)
        console_cases = console_script_cases(temp_repo)
    except RuntimeError as exc:
        print("== 夹具构造失败 ==")
        print("   [FAIL] %s" % exc)
        print("结论：FAIL")
        return 1

    print("== 命令覆盖自检（并排数一遍）==")
    coverage_failures = audit_command_coverage(cases, console_cases)
    print("   已交付：%s" % ", ".join(stages.DELIVERED_COMMANDS))
    print("   阶段未就绪：%s" % ", ".join("%s(%s)" % (k, v) for k, v in sorted(stages.STAGE_NOT_READY.items())))
    for item in coverage_failures:
        print("   [FAIL] %s" % item)
    failures.extend(coverage_failures)

    print("== 零网络导入面审计 ==")
    network_failures = audit_zero_network()
    if network_failures:
        for item in network_failures:
            print("   [FAIL] %s" % item)
        failures.extend(network_failures)
    else:
        print("   [PASS] 源码未导入任何网络模块")

    print("== 模块通路冒烟（python -m agent_conflict_radar）==")
    for case in cases:
        code, output = _run(case.argv, case.cwd, case.path_override)
        ok = code == case.expected
        results.append((case.name, code, case.expected, ok))
        print("   [%s] %-34s rc=%s expected=%s%s" % ("PASS" if ok else "FAIL", case.name, code, case.expected, ("  # " + case.note) if case.note else ""))
        if not ok:
            print("        输出片段：%s" % output.strip().replace("\n", " | ")[:300])
            failures.append("模块通路 %s：rc=%s expected=%s" % (case.name, code, case.expected))

    print("== 合成矩阵生成器自检（K10：冻结产物形态 + 重生成逐字节 + 提交 sha 复算）==")
    gen_case = Case(
        "matrix:生成器 --check",
        [sys.executable, "-m", "agent_conflict_radar.bench.gen", "--check"],
        EXIT_OK,
        cwd=REPO_ROOT,
        command="--gen-check--",
        note="不进 stages 命令表（它不是 radar 子命令），但同样在 CI 里真跑",
    )
    code, output = _run(gen_case.argv, gen_case.cwd)
    ok = code == gen_case.expected
    results.append((gen_case.name, code, gen_case.expected, ok))
    print("   [%s] %-34s rc=%s expected=%s" % ("PASS" if ok else "FAIL", gen_case.name, code, gen_case.expected))
    if not ok:
        print("        输出片段：%s" % output.strip().replace("\n", " | ")[:500])
        failures.append("生成器自检失败：rc=%s expected=%s" % (code, gen_case.expected))

    print("== console script 通路冒烟（裸 radar）==")
    radar_available = shutil.which("radar") is not None
    if radar_available:
        for case in console_cases:
            code, output = _run(case.argv, case.cwd, case.path_override)
            ok = code == case.expected
            results.append((case.name, code, case.expected, ok))
            print("   [%s] %-34s rc=%s expected=%s" % ("PASS" if ok else "FAIL", case.name, code, case.expected))
            if not ok:
                print("        输出片段：%s" % output.strip().replace("\n", " | ")[:300])
                failures.append("console 通路 %s：rc=%s expected=%s" % (case.name, code, case.expected))
    else:
        verdict = "FAIL" if args.strict else "SKIP"
        print("   [%s] 未找到 console script `radar`（未安装）；--strict 下视为失败" % verdict)
        if args.strict:
            failures.append("console script 缺失：请先 `python -m pip install -e \".[dev]\"`")

    print("== 汇总 ==")
    print("   用例 %d 条，失败 %d 项" % (len(results), len(failures)))
    for item in failures:
        print("   - %s" % item)
    if failures:
        print("结论：FAIL")
        return 1
    print("结论：PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
