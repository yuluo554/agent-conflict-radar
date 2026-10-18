"""命令行入口：参数解析 → 环境校验 → 分派。

退出码语义（K1）见 `exit_codes.py`。分派顺序是固定契约，冒烟测试按它断言：

    1. 解析参数            → 用法错误给 2
    2. 加载配置            → 缺失/不可解析给 3
    3. 目标路径存在性      → 不存在给 2
    4. git 可用性          → 不可用给 3
    5. 执行命令

顺序是有意的：**能判定的环境问题先判**，这样"配置坏了""git 没装"这类用户需要立刻知道的事
不会被别的错误掩盖。

编码守卫（K8）：入口第一件事就是 `_ensure_utf8_stdio()`。`py -X utf8` 只是本机习惯，
**不是全局免疫力**——用户直接敲 `radar` 时没有这个开关，CI 管道可能是 cp1252。
"""

import argparse
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from . import config as config_module
from . import detect as detect_module
from . import discover
from . import gitio
from . import intent as intent_module
from . import report as report_module
from . import serialize
from . import stages
from .bench import score as bench_module
from .errors import ConfigError, RadarError, UsageError
from .exit_codes import (
    EXIT_CODE_LABELS,
    EXIT_CONFLICTS_FOUND,
    EXIT_ENVIRONMENT,
    EXIT_OK,
    EXIT_USAGE,
)

#: 需要 git 的命令（缺 git 时 exit 3，绝不静默降级成"无冲突"）。
_NEEDS_GIT = stages.NEEDS_GIT

#: 允许的机读输出格式；未知格式**显式拒绝**（不静默喂错格式）。
ALLOWED_FORMATS = ("md", "json", "both")


# --------------------------------------------------------------------------------------
# 编码守卫
# --------------------------------------------------------------------------------------

#: 中文/东亚控制台编码：这些环境下**保持不动**（改成 utf-8 反而会让控制台乱码）。
_CJK_CONSOLE_ENCODINGS = ("cp936", "gbk", "gb18030", "gb2312", "cp950", "big5", "cp932", "cp949")


def _ensure_utf8_stdio() -> None:
    """按 `stream.encoding` 探针决定是否把 stdout/stderr 重配为 utf-8。

    判别逻辑：
    * 已是 utf-8 → 不动；
    * 中日韩控制台编码（cp936 等）→ **保持不动**（控制台按本地码页渲染，重配会乱码）；
    * 其余（cp1252 / ascii / 等）→ 重配为 utf-8 严格模式（否则中文输出必抛 UnicodeEncodeError）。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("_", "-")
        if encoding.startswith("utf-8") or encoding.startswith("utf8"):
            continue
        if encoding in _CJK_CONSOLE_ENCODINGS:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (ValueError, OSError):
            # 重配失败不阻断主流程：报告入口只在"我们自己的输出"这一层兜底。
            continue


# --------------------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """把 argparse 的 `sys.exit(2)` 改成抛异常，使 `main()` 能以**返回码**形式可测。"""

    def error(self, message):  # type: ignore[override]
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    """构造完整 parser。README 指令面对账门会反射这个对象（K14）。"""
    parser = _Parser(
        prog="radar",
        description=(
            "多 agent 并行开发冲突雷达：在写入发生前按 worktree/会话/文件/函数符号四级粒度"
            "预判并行冲突。纯本地、只读、零上传。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "退出码：0 无冲突 / 1 有冲突 / 2 用法错误 / 3 依赖或环境缺失\n"
            "数值口径唯一权威：config/radar.toml（用 `radar config` 查看生效值）"
        ),
    )
    parser.add_argument("--version", action="version", version="agent-conflict-radar %s" % __version__)
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="配置文件路径（默认：仓库根下 config/radar.toml；也可用环境变量 RADAR_CONFIG）",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<命令>")

    def add_repo_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--repo", metavar="PATH", default=None, help="目标仓库路径（默认：当前目录）")
        sub.add_argument("--claude-root", metavar="PATH", default=None, help="Claude Code 会话根目录")
        sub.add_argument("--codex-root", metavar="PATH", default=None, help="Codex 会话根目录")
        sub.add_argument("--out-dir", metavar="PATH", default=None, help="产物输出目录（默认：当前目录）")
        sub.add_argument(
            "--now",
            metavar="ISO8601",
            default=None,
            help="活跃判定的参考时刻（缺省取观测到的最大会话时间戳）。确定性测试与基准必须显式传",
        )

    scan = subparsers.add_parser("scan", help="M1：工作区与会话发现")
    add_repo_options(scan)
    scan.add_argument("--window", metavar="DAYS", type=int, default=None, help="会话扫描窗口（天，覆盖配置）")

    intent = subparsers.add_parser("intent", help="M2：变更意图提取")
    add_repo_options(intent)

    detect = subparsers.add_parser("detect", help="M3：三级冲突检测（文件/区块/符号）")
    add_repo_options(detect)

    report = subparsers.add_parser("report", help="M4：预警报告（Markdown + JSON）")
    add_repo_options(report)
    report.add_argument(
        "--format",
        choices=ALLOWED_FORMATS,
        default="both",
        help="产物格式：md / json / both（未知值显式拒绝，不静默喂错）",
    )

    bench = subparsers.add_parser("bench", help="M5：合成冲突矩阵 + 真值对账")
    bench.add_argument("--bench-dir", metavar="PATH", default=None, help="合成矩阵目录（默认：仓库根下 bench/）")
    bench.add_argument("--out-dir", metavar="PATH", default=None, help="对账结果输出目录（落 last_run.json）")
    bench.add_argument("--only", metavar="ID[,ID...]", default=None, help="只跑指定场景（逗号分隔）")

    subparsers.add_parser("config", help="打印生效配置（可核验「数值从哪来」）")
    subparsers.add_parser("selftest", help="自检：配置/退出码契约/序列化契约/包可用性")

    return parser


# --------------------------------------------------------------------------------------
# 分派
# --------------------------------------------------------------------------------------


def _fail(message: str, code: int) -> int:
    sys.stderr.write("%s\n" % message)
    return code


def _load_config(args) -> config_module.Config:
    return config_module.load(getattr(args, "config", None))


def _resolve_repo(args) -> str:
    raw = getattr(args, "repo", None) or os.getcwd()
    from .paths import normalize_path

    path = normalize_path(raw)
    if not path.is_dir():
        raise UsageError("--repo 指向的路径不是目录或不存在：%s" % path)
    return str(path)


def _dispatch(args) -> int:
    command = args.command
    if command is None:
        raise UsageError("缺少子命令。可用命令：%s" % ", ".join(stages.all_commands()))

    # 2) 配置（任何命令都要读，配置坏了就没有第二份真相可回落）
    cfg = _load_config(args)

    # 3) 目标路径存在性 → 2；4) git 可用性 → 3
    if command in _NEEDS_GIT:
        repo = _resolve_repo(args)
        gitio.ensure_git_available()
        setattr(args, "repo_resolved", repo)

    # 5) 执行
    if command == "config":
        return _cmd_config(cfg)
    if command == "selftest":
        return _cmd_selftest(cfg)
    if command == "scan":
        return _cmd_scan(cfg, args)
    if command == "intent":
        return _cmd_intent(cfg, args)
    if command == "detect":
        return _cmd_detect(cfg, args)
    if command == "report":
        return _cmd_report(cfg, args)
    if command == "bench":
        return _cmd_bench(cfg, args)
    raise UsageError("未知命令：%r" % command)  # pragma: no cover - 由 parser 兜住


def _cmd_scan(cfg, args) -> int:
    """`radar scan`：worktree + 双 harness 会话归集 → `WorkspaceTable`。

    退出码语义（与 README 一致）：**成功恒为 0**；`undetermined` 只提示不改码——
    未被识别的会话形态是"我们没看懂"，不是"有冲突"，把它映射成非 0 会让调用方
    分不清"检出冲突"与"解析受限"。真正的环境问题（非 git 仓库 / 会话源不存在）走 exit 3。
    """
    window_days = getattr(args, "window", None)
    if window_days is not None:
        # 覆盖只作用于本次调用的内存视图：配置文件仍是唯一权威（K3），不写盘、不改原对象。
        cfg = cfg.with_override("window", "scan_days", window_days)
    table = discover.build_workspace_table(
        args.repo_resolved,
        getattr(args, "claude_root", None),
        getattr(args, "codex_root", None),
        cfg,
        now=getattr(args, "now", None),
    )
    text = serialize.dumps_json(table.as_dict())
    out_dir = getattr(args, "out_dir", None)
    if out_dir:
        target_dir = _resolve_out_dir(out_dir)
        serialize.write_atomic(target_dir / "scan.json", text)
    sys.stdout.write(text)
    return EXIT_OK


def _cmd_intent(cfg, args) -> int:
    """`radar intent`：会话写操作 + 未提交 diff → `IntentSet`。

    退出码语义（与 README 一致）：**成功恒为 0**。`undetermined` 与 `unknown` 落点只提示不改码——
    "我们没定位到区间"不是"有冲突"；真正的环境问题（非 git 仓库 / 会话源不存在 / git 超时）走 exit 3。
    """
    result = intent_module.build_intent_set(
        args.repo_resolved,
        getattr(args, "claude_root", None),
        getattr(args, "codex_root", None),
        cfg,
        now=getattr(args, "now", None),
    )
    text = serialize.dumps_json(result.as_dict())
    out_dir = getattr(args, "out_dir", None)
    if out_dir:
        target_dir = _resolve_out_dir(out_dir)
        serialize.write_atomic(target_dir / "intent.json", text)
    sys.stdout.write(text)
    return EXIT_OK


def _cmd_detect(cfg, args) -> int:
    """`radar detect`：M1 发现 + M2 意图 → 三级冲突记录 → `conflicts.json`。

    退出码语义（与 README 一致，**这是第一条真的会用 1 的命令**）：
    **有冲突 → 1，无冲突 → 0**。`undetermined` / `degraded` / `approximate` **不改变**这个判定
    ——它们是"这条判不准"的显式标注，不是"有冲突"；但报告与产物里必须逐条列出来
    （"没底"绝不能读成"没问题"）。真正的环境问题（非 git 仓库 / 会话源不存在 / git 超时）走 exit 3。
    """
    result = detect_module.build_conflict_set(
        args.repo_resolved,
        getattr(args, "claude_root", None),
        getattr(args, "codex_root", None),
        cfg,
        now=getattr(args, "now", None),
    )
    text = serialize.dumps_json(result.as_dict())
    out_dir = getattr(args, "out_dir", None)
    if out_dir:
        target_dir = _resolve_out_dir(out_dir)
        serialize.write_atomic(target_dir / "conflicts.json", text)
    sys.stdout.write(text)
    return EXIT_CONFLICTS_FOUND if result.conflicts else EXIT_OK


def _cmd_report(cfg, args) -> int:
    """`radar report`：M3 的 `ConflictSet` → `report.md`（人读）+ `conflicts.json`（机读）。

    退出码语义（与 `detect` 同一条口径）：**有冲突 → 1，无冲突 → 0**。`undetermined` /
    `degraded` / `approximate` **不改**退出码，但报告里逐条列出（"没底"绝不读成"没问题"）。

    **单一渲染源**：`report_module.build_report` 产出的 `payload` 就是 `conflicts.json` 的内容
    （与 `detect` 的落盘产物**同内容同字节**），Markdown 是它的纯函数——不存在"两份各自生成、
    再人工比对"的形态。`--format` 只决定**打印/落盘哪一份**，不改变两份产物的内容。
    """
    result = detect_module.build_conflict_set(
        args.repo_resolved,
        getattr(args, "claude_root", None),
        getattr(args, "codex_root", None),
        cfg,
        now=getattr(args, "now", None),
    )
    surface = report_module.build_report(result, cfg, repo=args.repo_resolved)
    fmt = getattr(args, "format", "both")
    json_text = surface.json_text()
    out_dir = getattr(args, "out_dir", None)
    if out_dir:
        target_dir = _resolve_out_dir(out_dir)
        if fmt in ("json", "both"):
            serialize.write_atomic(target_dir / "conflicts.json", json_text)
        if fmt in ("md", "both"):
            serialize.write_atomic(target_dir / "report.md", surface.markdown)
    if fmt == "json":
        sys.stdout.write(json_text)
    else:
        sys.stdout.write(surface.markdown)
    return EXIT_CONFLICTS_FOUND if result.conflicts else EXIT_OK


def _cmd_bench(cfg, args) -> int:
    """`radar bench`：把冻结矩阵逐场景物化 → scan/intent/detect → 与真值集合精确匹配。

    退出码语义（与 README 一致）：**全部场景通过 → 0；任一场景失败 → 1**。
    这里的 `1` 不是"检出冲突"，而是"基准未达标"——两种 1 的语义在输出文本里写明，
    避免把"评分失败"读成"仓库有冲突"。用法错误（`--only` 未知 id / 过滤后为空）→ 2；
    矩阵目录缺失 / 场景物化时 git 不可用 → 3。

    `--out-dir` 给了就落 `last_run.json`（经 `serialize.write_atomic`，K2）；不给时落
    **矩阵目录**（`<bench-dir>/last_run.json`，`plan/05` §二 的布局）——这是唯一一条默认写盘的命令：
    "最近一次评分结果"本身就是交付物（DoD 点名的实物），不落盘就无法被复核。
    """
    bench_dir = getattr(args, "bench_dir", None)
    only_raw = getattr(args, "only", None)
    only = None if only_raw is None else only_raw.split(",")
    out_dir = getattr(args, "out_dir", None)
    target_dir = _resolve_out_dir(out_dir) if out_dir else None
    result = bench_module.run_bench(
        bench_dir=bench_dir,
        out_dir=None,  # 由这里统一落盘，复用 CLI 的 --out-dir 解析（不存在就建，存在但不是目录 → 2）
        only=only,
        cfg=cfg,
    )
    text = bench_module.render_summary(result)
    if target_dir is not None:
        bench_module.write_last_run(str(target_dir), result)
    else:
        # 默认落**本轮解析出的**矩阵目录（`--bench-dir` 或仓库根 bench/），不另算一遍路径规则。
        bench_module.write_last_run(result.bench_dir, result)
    sys.stdout.write(text)
    return EXIT_OK if result.all_passed() else EXIT_CONFLICTS_FOUND


def _resolve_out_dir(raw: str):
    """把 `--out-dir` 解析成可写目录：不存在就建；存在但不是目录 → 用法错误（exit 2）。"""
    from .paths import normalize_path

    target = normalize_path(raw)
    if target.is_dir():
        return target
    if target.exists():
        raise UsageError("--out-dir 指向的不是目录：%s" % target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _cmd_config(cfg) -> int:
    payload = {
        "source_path": str(cfg.source_path),
        "schema_version": cfg.get("schema", "version"),
        "values": cfg.as_dict(),
        "note": (
            "本输出即生效配置。config/radar.toml 是全项目唯一的数值定义处（K3）；"
            "代码里零内联默认值，缺失或未知键一律报错而不回落。"
        ),
    }
    sys.stdout.write(serialize.dumps_json(payload))
    return EXIT_OK


def _registered_commands() -> List[str]:
    """反射 parser 的子命令注册面（自检用；`build_parser` 只建一次，不留全局状态）。"""
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse 没有公开的枚举接口
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return sorted(action.choices)
    return []


def _selftest_checks(cfg) -> List[str]:
    """返回失败项描述列表；空列表 = 自检通过（可证伪：把配置指向坏文件即返回非空）。"""
    failures = []

    # 检查 1：配置可读且键齐（配置坏 → 上游已抛错；此处再核一遍取值可达）
    try:
        window = cfg.get("window", "active_minutes")
        if not isinstance(window, int) or window <= 0:
            failures.append("配置项 window.active_minutes 不是正整数：%r" % (window,))
    except RadarError as exc:
        failures.append("配置不可用：%s" % exc)

    # 检查 2：退出码契约自洽
    from .exit_codes import ALL_EXIT_CODES

    if len(set(ALL_EXIT_CODES)) != len(ALL_EXIT_CODES):
        failures.append("退出码常量存在重复值：%r" % (ALL_EXIT_CODES,))
    for code in ALL_EXIT_CODES:
        if code not in EXIT_CODE_LABELS:
            failures.append("退出码 %r 没有语义标签" % (code,))

    # 检查 3：序列化契约（跑一次真序列化并与期望字节比对）
    probe = {"b": 1, "a": "中文"}
    expected = '{\n  "a": "中文",\n  "b": 1\n}\n'
    if serialize.dumps_json(probe) != expected:
        failures.append("序列化契约不满足（K2）：期望 %r" % expected)

    # 检查 4：命令表自洽（parser 注册面 == 已交付表；M5 起没有"未交付"这第三种状态）
    try:
        registered = set(_registered_commands())
        declared = set(stages.DELIVERED_COMMANDS)
        if registered != declared:
            failures.append(
                "命令表与 parser 注册面不一致：parser 多出 %s / 已交付表多出 %s"
                % (sorted(registered - declared), sorted(declared - registered))
            )
    except RadarError as exc:
        failures.append("命令表不可校验：%s" % exc)

    # 检查 5：包版本可得
    if not __version__:
        failures.append("包版本号为空")

    return failures


def _cmd_selftest(cfg) -> int:
    failures = _selftest_checks(cfg)
    if failures:
        sys.stderr.write("自检未通过（%d 项）：\n" % len(failures))
        for item in failures:
            sys.stderr.write("  - %s\n" % item)
        return 1
    sys.stdout.write(
        "自检通过：配置 / 退出码契约 / 序列化契约 / 阶段表 / 包版本 五项正常。\n"
    )
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """入口。返回退出码（不自行 `sys.exit`，便于测试与复用）。"""
    _ensure_utf8_stdio()
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except UsageError as exc:
        sys.stderr.write("用法错误：%s\n" % exc)
        sys.stderr.write(parser.format_usage())
        return EXIT_USAGE
    except SystemExit as exc:  # --help / --version
        code = exc.code
        return int(code) if isinstance(code, int) else EXIT_OK

    try:
        return _dispatch(args)
    except UsageError as exc:
        return _fail("用法错误：%s" % exc, EXIT_USAGE)
    except ConfigError as exc:
        return _fail("配置错误：%s" % exc, EXIT_ENVIRONMENT)
    except RadarError as exc:
        return _fail("%s" % exc, exc.exit_code)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
