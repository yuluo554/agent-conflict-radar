"""守门变异验证（SKILL「新增/改写的守门要做一次变异验证」）。

把被测行为**故意弄坏** → 对应守门**必须变红**；弄坏后仍绿 = 假门。
"我删掉这段逻辑，测试会红吗？"——本脚本把这句话变成可复跑的命令。

三个防自欺的机制（对应 SKILL 变异脚本三连条）：

1. **替换前断言 marker 存在**——marker 没匹配上（锚点漂了/撞了 docstring）时，
   `str.replace` 会**静默返回原文**，于是"测试仍绿"看起来像"守门是假门"，其实是根本没改到代码；
2. **替换后断言文件已变**——同上，防静默 no-op；
3. **还原后断言字节一致**，且全过程 `try/finally`——防止把仓库留在被弄坏的状态。

用法：
    python tools/verify_mutation.py            # 跑全部变异组
    python tools/verify_mutation.py --only M3  # 单跑（改完守门先单跑省时间）

⚠️ M11/M12 会**临时改冻结产物与配置**（都在 `finally` 里按字节还原）：这是有意的——
"改了阈值/台账而守门不红"正是最该被抓到的形态。
"""

import argparse
import os
import subprocess
import sys
import tempfile
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Mutation(object):
    def __init__(self, ident, path, marker, replacement, must_fail, note):
        self.ident = ident
        self.path = path
        self.marker = marker
        self.replacement = replacement
        self.must_fail = must_fail
        self.note = note


MUTATIONS: List[Mutation] = [
    Mutation(
        "M1",
        "README.md",
        "radar bench --only same_symbol_diff_lines",
        "radar bench --definitely-not-a-flag same_symbol_diff_lines",
        "tests/test_readme_gate.py::test_readme_commands_exist_in_cli",
        "README 写了不存在的旗标 → 指令面对账门必须变红",
    ),
    Mutation(
        "M2",
        "README.md",
        "| `radar detect` | 三级冲突检测（文件 / 区块 / 符号） |",
        "| `radar detectX` | 三级冲突检测（文件 / 区块 / 符号） |",
        "tests/test_readme_gate.py::test_every_cli_subcommand_is_documented",
        "命令总表漏记一条命令 → 反向覆盖门必须变红。marker 必须锚在**命令总表那一行**："
        "顶部状态表也有同名行，改错地方就会'数据从另一章节露出'而门禁照常绿（已实测踩中一次）",
    ),
    Mutation(
        "M3",
        "src/agent_conflict_radar/gitio.py",
        "_WORKTREE_ALLOWED = frozenset({\"list\"})",
        "_WORKTREE_ALLOWED = frozenset({\"list\"})\n_MUTANT_CONSTANT = 42",
        "tests/test_config_literals.py::test_no_policy_numeric_literals_in_source",
        "源码里藏一个策略数值字面量 → 零内联阈值门禁必须变红",
    ),
    Mutation(
        "M4",
        "src/agent_conflict_radar/stages.py",
        'STAGE_NOT_READY = {\n    "intent": "M2",',
        'STAGE_NOT_READY = {\n    "scan": "M1",\n    "intent": "M2",',
        "tests/test_stage_guard.py::test_no_command_is_unclassified",
        "把**已退役**的 scan 又塞回阶段未就绪表（幽灵语义复活）→ 阶段守卫必须变红",
    ),
    Mutation(
        "M5",
        "src/agent_conflict_radar/config.py",
        "            if key not in node:\n"
        "                raise ConfigError(\n"
        '                    "配置缺少 %s.%s（来源：%s）：缺失即报错，绝不回落默认值（K3）。"\n'
        "                    % (section, key, source_path)\n"
        "                )\n"
        "            value = node[key]",
        "            value = node.get(key, 1 if expected is int else (False if expected is bool else \"\"))",
        "tests/test_config_single_source.py::test_missing_key_is_rejected_not_defaulted",
        "缺键时回落一份代码内默认值（第二份真相）→ 数值单点门禁必须变红",
    ),
    Mutation(
        "M6",
        "src/agent_conflict_radar/__init__.py",
        '__version__ = "0.0.1"',
        '__version__ = "9.9.9"',
        "tests/test_readme_gate.py::test_product_name_is_consistent_four_ways",
        "包内版本号与安装元数据不一致 → 名字/版本四向一致门禁必须变红",
    ),
    Mutation(
        "M7",
        "src/agent_conflict_radar/exit_codes.py",
        "EXIT_NOT_READY = 4",
        "EXIT_NOT_READY = 5",
        "tests/test_cli_contract.py::test_exit_code_set_is_frozen_and_labelled",
        "退出码集合被改动 → 退出码契约门禁必须变红",
    ),
    Mutation(
        "M8",
        "pyproject.toml",
        "dependencies = []",
        'dependencies = ["requests"]',
        "tests/test_readme_gate.py::test_pyproject_declares_no_runtime_dependencies",
        "引入第三方运行时依赖 → 零依赖门禁必须变红",
    ),
    Mutation(
        "M9",
        "src/agent_conflict_radar/serialize.py",
        'FROZEN_JSON_KWARGS = {"sort_keys": True, "ensure_ascii": False, "indent": 2}',
        'FROZEN_JSON_KWARGS = {"sort_keys": True, "ensure_ascii": True, "indent": 4}',
        "tests/test_serialize_frozen.py",
        "改掉冻结序列化参数（中文被转义、缩进漂移）→ 冻结契约门禁必须变红",
    ),
    Mutation(
        "M10",
        "src/agent_conflict_radar/cli.py",
        '            reconfigure(encoding="utf-8", errors="strict")',
        "            pass  # 变异：不再重配编码",
        "tests/test_encoding_guard.py::test_cp1252_stream_is_reconfigured_to_utf8",
        "编码守卫失效 → cp1252 复现门禁必须变红",
    ),
    Mutation(
        "M11",
        "bench/scenarios/threshold_exact/truth.json",
        '"gap_lines": 3,',
        '"gap_lines": 4,',
        "tests/test_bench_matrix.py::test_generator_check_passes_on_the_frozen_tree",
        "冻结真值被手改（间距脱离阈值边界）→ 生成器 --check 必须变红："
        "这条直接打「台账禁手改」与「重生成逐字节比对」两层",
    ),
    Mutation(
        "M12",
        "config/radar.toml",
        "adjacent_tolerance = 3",
        "adjacent_tolerance = 9",
        "tests/test_bench_matrix.py::test_generator_check_passes_on_the_frozen_tree",
        "改阈值而真值不动 → --check 的 gap_rule 现场求值必须变红（6a/6b 的期望建立在边界上）",
    ),
    Mutation(
        "M13",
        "src/agent_conflict_radar/discover.py",
        "seq=message_line_no,",
        "seq=1,",
        "tests/test_discover.py::test_claude_first_line_is_not_message_line_and_seq_is_source_line_number",
        "seq 退化成「数组下标/首行」→ 行号可复算这条判据必须变红（Claude 首行不是消息行）",
    ),
    Mutation(
        "M14",
        "tools/verify_offline.py",
        "    covered = {case.command for case in list(cases) + list(console_cases)}",
        "    covered = set(stages.all_commands())  # 变异：退回恒真判据",
        "tests/test_stage_guard.py::test_smoke_tool_coverage_audit_is_self_consistent_and_falsifiable",
        "覆盖自检退回「恒真」（两侧本就是同一并集）→ 可证伪性断言必须变红",
    ),
    Mutation(
        "M15",
        "src/agent_conflict_radar/bench/gen.py",
        '        if key_path.startswith("observed"):',
        "        if False:  # 变异：不再拦 observed_*",
        "tests/test_bench_matrix.py::test_check_actually_detects_a_tampered_truth",
        "真值里的 observed_* 不再被拦 → 那条「往真值里加一个观测字段」的探针必须变红（K9）",
    ),
    Mutation(
        "M16",
        "src/agent_conflict_radar/bench/gen.py",
        "    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)",
        "    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=4)",
        "tests/test_bench_matrix.py::test_generator_serializer_is_an_independent_implementation_with_identical_bytes",
        "生成侧序列化参数与生产侧漂移 → 逐字节一致性断言必须变红（K10）",
    ),
]


def _run_pytest(targets: List[str]) -> Tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"] + list(targets),
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.returncode, completed.stdout.decode("utf-8", errors="replace")


def apply_mutation(mutation: Mutation) -> str:
    """应用变异，返回原始文本（供还原）。**三重断言**：marker 存在 / 文件已变 / 还原一致。"""
    full = os.path.join(REPO_ROOT, mutation.path)
    with open(full, "r", encoding="utf-8", newline="") as handle:
        original = handle.read()
    assert mutation.marker in original, (
        "%s：锚点未命中 %s（marker 漂了或撞了 docstring）——不命中就什么都不做，"
        "会让'测试仍绿'看起来像'门是假门'。" % (mutation.ident, mutation.path)
    )
    mutated = original.replace(mutation.marker, mutation.replacement, 1)
    assert mutated != original, "%s：替换后文件未变化（静默 no-op）" % mutation.ident
    with open(full, "w", encoding="utf-8", newline="") as handle:
        handle.write(mutated)
    return original


def restore(path: str, original: str) -> None:
    full = os.path.join(REPO_ROOT, path)
    with open(full, "w", encoding="utf-8", newline="") as handle:
        handle.write(original)
    with open(full, "r", encoding="utf-8", newline="") as handle:
        assert handle.read() == original, "还原后字节不一致：%s" % path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="守门变异验证")
    parser.add_argument("--only", default=None, help="只跑指定变异组（逗号分隔，如 M3,M5）")
    args = parser.parse_args(list(argv) if argv is not None else None)
    selected = None if args.only is None else {item.strip() for item in args.only.split(",")}

    print("== 基线：全部变异组的目标守门必须先全绿 ==")
    code, output = _run_pytest(sorted({m.must_fail for m in MUTATIONS}))
    if code != 0:
        print(output)
        print("结论：FAIL —— 基线不绿，变异验证无意义")
        return 1
    print("   基线绿：%d 条目标守门全部通过" % len({m.must_fail for m in MUTATIONS}))

    results = []
    failures = []
    for mutation in MUTATIONS:
        if selected is not None and mutation.ident not in selected:
            continue
        original = None
        try:
            original = apply_mutation(mutation)
            code, output = _run_pytest([mutation.must_fail])
            detected = code != 0
        finally:
            if original is not None:
                restore(mutation.path, original)
        status = "PASS" if detected else "FAIL"
        results.append((mutation.ident, status))
        print(
            "   [%s] %-4s %-42s 目标守门 %s"
            % (status, mutation.ident, mutation.note, "变红" if detected else "仍绿（假门！）")
        )
        if not detected:
            failures.append(mutation.ident)

    print("== 汇总 ==")
    print("   变异组 %d 个，其中未检出（假门）%d 个" % (len(results), len(failures)))
    if failures:
        print("   失败组：%s" % ", ".join(failures))
        print("结论：FAIL")
        return 1
    print("结论：PASS —— 每个变异都被对应的守门抓到，且仓库已按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
