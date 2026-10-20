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
        'DELIVERED_COMMANDS = (\n    "config",',
        'STAGE_NOT_READY = {"bench": "M5"}  # 变异：复活未就绪表\nDELIVERED_COMMANDS = (\n    "config",',
        "tests/test_cli_contract.py::test_stage_tables_have_no_not_ready_bucket",
        "把**已退役**的「未就绪」表重新塞回 stages（exit 4 幽灵语义复活）→ `not hasattr` 防复活断言必须变红。"
        "锚点从 M1–M4 的 `STAGE_NOT_READY` 条目改成了 `DELIVERED_COMMANDS` 的首行："
        "M5 交付 `bench` 后那张表已经整条删掉，旧锚点无处可落（变异脚本的「锚点未命中」当场报出）",
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
        '__version__ = "',
        '__version__ = "9.9.9"  # "',
        "tests/test_readme_gate.py::test_product_name_is_consistent_four_ways",
        "包内版本号与安装元数据不一致 → 名字/版本四向一致门禁必须变红。"
        "锚点**刻意不含版本号**（`__version__ = \"` + 把剩余部分注释掉）："
        "首版锚点写成 `__version__ = \"0.0.1\"`，v0.0.2 发版后当场锚点未命中——"
        "含版本号的锚点每次发版都会失效，而失效时脚本会按三重断言报错（不是静默 no-op）",
    ),
    Mutation(
        "M7",
        "src/agent_conflict_radar/exit_codes.py",
        "EXIT_ENVIRONMENT = 3",
        "EXIT_ENVIRONMENT = 5",
        "tests/test_cli_contract.py::test_exit_code_set_is_frozen_and_labelled",
        "退出码集合被改动 → 退出码契约门禁必须变红。"
        "M5 起 `EXIT_NOT_READY` 已删，锚点随之落到 `EXIT_ENVIRONMENT`；"
        "另有一组 M34 专打「4 不得复活」",
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
        '        if key_path.startswith("observed"):\n'
        '            failures.append("场景 %s 的真值出现 observed_* 字段（%s）：K9 禁止把观测写进真值" % (ident, key_path))\n'
        "            continue",
        '        if False:  # 变异：不再拦 observed_*\n'
        '            failures.append("场景 %s 的真值出现 observed_* 字段（%s）：K9 禁止把观测写进真值" % (ident, key_path))\n'
        "            continue",
        "tests/test_bench_matrix.py::test_check_actually_detects_a_tampered_truth",
        "真值里的 observed_* 不再被拦 → 那条「往真值里加一个观测字段」的探针必须变红（K9）。"
        "锚点必须带上下文：M2 新增的 `_check_intent_payload` 有同形的一行，只锚 `if key_path.startswith` "
        "会改到意图侧、目标守门照常绿（本棒实测踩中过一次，靠变异脚本的「未检出」当场抓到）",
    ),
    Mutation(
        "M16",
        "src/agent_conflict_radar/bench/gen.py",
        "    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)",
        "    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=4)",
        "tests/test_bench_matrix.py::test_generator_serializer_is_an_independent_implementation_with_identical_bytes",
        "生成侧序列化参数与生产侧漂移 → 逐字节一致性断言必须变红（K10）",
    ),
    Mutation(
        "M17",
        "src/agent_conflict_radar/intent.py",
        "    if len(hits) > 1:\n"
        "        # 多处命中：显式降级 + **在产物里点名命中次数**（不许挑第一个当真值）。\n"
        '        return _Located([], PRECISION_COARSE, reasons + ["%s#%d" % (REASON_ANCHOR_AMBIGUOUS, len(hits))])\n'
        "    start = hits[0] + 1",
        "    start = hits[0] + 1  # 变异：多处命中时直接挑第一个",
        "tests/test_intent_parse.py::test_locate_ambiguous_anchor_is_coarse_and_names_the_count",
        "锚点多处命中时挑第一个（把「不确定」伪装成「精确」）→ 歧义降级断言必须变红",
    ),
    Mutation(
        "M18",
        "src/agent_conflict_radar/intent.py",
        "    if op.replace_all:\n        return _Located([], PRECISION_COARSE, [REASON_REPLACE_ALL])",
        "    if op.replace_all:\n        return _Located([(1, 1)], PRECISION_EXACT, [])  # 变异：编一个看起来精确的区间",
        "tests/test_intent_parse.py::test_locate_replace_all_never_claims_a_range",
        "`replace_all` 编出一个精确区间 → 「不伪造精确行区间」断言必须变红",
    ),
    Mutation(
        "M19",
        "src/agent_conflict_radar/intent.py",
        "        if op.reason in (REASON_MULTI_EDIT, REASON_MISSING_FILE_PATH):\n"
        "            return _Located([], PRECISION_UNKNOWN, [op.reason])",
        "        if op.reason in (REASON_MULTI_EDIT, REASON_MISSING_FILE_PATH):\n"
        "            return _Located([], PRECISION_COARSE, [op.reason])  # 变异：unknown 降级成 coarse",
        "tests/test_intent_parse.py::test_locate_multi_edit_reason_maps_to_unknown",
        "`MultiEdit` 从 unknown 降级成 coarse（假装「文件是知道的」）→ 三分法断言必须变红",
    ),
    Mutation(
        "M20",
        "src/agent_conflict_radar/intent.py",
        "        if disk_ranges:\n            ranges, source = disk_ranges, RANGES_FROM_DISK",
        "        if False:  # 变异：不再以磁盘为准\n            ranges, source = disk_ranges, RANGES_FROM_DISK",
        "tests/test_intent.py::test_disk_diff_wins_and_disagreement_is_named",
        "磁盘与会话不一致时不再以磁盘为准 → 「磁盘是事实」断言必须变红",
    ),
    Mutation(
        "M21",
        "src/agent_conflict_radar/intent.py",
        '    return str(path).lower().endswith(".py")',
        "    return True  # 变异：所有文件都当 Python（假装有符号级能力）",
        "tests/test_intent.py::test_non_python_files_are_approximate_and_carry_no_symbol_field",
        "非 Python 文件被当成 Python（R4 未闭环却宣称符号级）→ approximate 断言必须变红",
    ),
    Mutation(
        "M22",
        "bench/intents/intent_ambiguous_anchor_coarse/truth.json",
        '"anchor_ambiguous#2"',
        '"anchor_ambiguous#1"',
        "tests/test_intent.py::test_scenario_parses_to_the_frozen_truth",
        "意图真值被手改（命中次数脱离几何）→ 逐场景对账 + 生成器 --check 必须变红："
        "这条同时打「真值禁手补」与「重生成逐字节」两层",
    ),
    Mutation(
        "M23",
        "src/agent_conflict_radar/detect.py",
        "    shared = [name for name in touching_left if name in touching_right]\n"
        "    if shared:\n"
        "        return SYMBOL_HIT_SAME, tuple(_minimal_symbols(shared, spans))",
        "    shared = [name for name in touching_left if name in touching_right]\n"
        "    if False:  # 变异：同一符号永不命中（符号级能力形同虚设）\n"
        "        return SYMBOL_HIT_SAME, tuple(_minimal_symbols(shared, spans))",
        "tests/test_detect.py::test_scenario_detects_to_the_frozen_truth",
        "符号级「同一符号」判据被打掉 → 冻结矩阵的逐场景精确匹配必须变红"
        "（场景 2 / 3 / 6a 的 levels/symbols 期望值当场对不上）",
    ),
    Mutation(
        "M24",
        "src/agent_conflict_radar/detect.py",
        "    return bool(left.derived_from) and left.derived_from == right.derived_from",
        "    return False  # 变异：不再按 derived_from 去重",
        "tests/test_detect.py::test_subagent_siblings_are_deduplicated_by_derived_from",
        "subagent 去重被关掉（把「自己和自己」报成跨 agent 冲突）→ 场景 4 的对账必须变红",
    ),
    Mutation(
        "M25",
        "src/agent_conflict_radar/detect.py",
        "    if result.returncode == _MERGE_TREE_ENVIRONMENT:\n        return False, True, [",
        "    if False:  # 变异：exit 128 当成「无冲突」\n        return False, True, [",
        "tests/test_detect_parse.py::test_unrelated_histories_exit_128_is_degraded_not_no_conflict",
        "无共同祖先（exit 128）不再降级 → 「不得读成无冲突」这条断言必须变红。"
        "⚠️ 本组首版**未检出**：只打掉 exit 128 分支时，下游那条「未预期的退出码」兜底分支照样降级，"
        "目标守门仍绿——变异脚本当场报了出来。处置不是给兜底开例外，而是把断言收紧到"
        "点名的具体原因（`exit 128` + `无共同祖先`），让两条通路可区分。",
    ),
    Mutation(
        "M26",
        "src/agent_conflict_radar/detect.py",
        "        return not self.approximate",
        "        return True  # 变异：取不到符号能力也照报符号字段（R4 未闭环却宣称符号级）",
        "tests/test_detect_parse.py::test_non_python_conflict_is_approximate_and_carries_no_symbol_key",
        "非 Python / 无基线的记录也吐符号字段 → 「产物里不出现符号级字段」必须变红（R4）",
    ),
    Mutation(
        "M27",
        "src/agent_conflict_radar/gitio.py",
        'MUTATING_FLAGS = frozenset({"-w", "--write", "--hard", "--force", "--prune", "--amend"})',
        'MUTATING_FLAGS = frozenset({"-w", "--hard", "--force", "--prune", "--amend"})  # 变异：放行 --write',
        "tests/test_detect_parse.py::test_mutating_git_subcommands_are_refused_before_a_process_starts",
        "只读白名单被打开（`--write` 不再拦）→ 只读纪律断言必须变红（K4）",
    ),
    Mutation(
        "M28",
        "src/agent_conflict_radar/detect.py",
        "    if range_gap(left, right) <= tolerance:",
        "    if range_gap(left, right) < tolerance:  # 变异：相邻容差差一（6a 该命中却不命中）",
        "tests/test_detect_parse.py::test_pair_symbol_hit_distinguishes_same_adjacent_and_far",
        "相邻容差的 `<=` 语义改成 `<` → 6a（间距 == 容差）的命中判据必须变红",
    ),
    Mutation(
        "M29",
        "src/agent_conflict_radar/detect.py",
        "    for item in conflicts:\n"
        "        by_max_level[item.level] += 1\n"
        "        for level in item.levels:\n"
        "            by_level_membership[level] += 1",
        "    for item in conflicts:\n"
        "        for level in item.levels:\n"
        "            by_max_level[level] += 1\n"
        "            by_level_membership[level] += 1",
        "tests/test_detect.py::test_membership_count_exceeds_entry_count_when_one_record_hits_two_levels",
        "`by_max_level`（划分）被改成记成员数 → K12 的两栏口径必须变红",
    ),
    Mutation(
        "M30",
        "src/agent_conflict_radar/report.py",
        "    serialize.assert_no_external_resources(text, where=\"report.md\")",
        "    pass  # 变异：渲染出口不再做零外链断言",
        "tests/test_report.py::test_external_resources_are_rejected_at_the_render_exit",
        "渲染出口的零外链断言被拿掉（只在测试里验一次）→ 「带 URL 的 payload 必须当场抛错」"
        "这条守门必须变红（K13 的第二律）",
    ),
    Mutation(
        "M31",
        "src/agent_conflict_radar/report.py",
        "        if \"symbols\" in record:",
        "        if True:  # 变异：假定所有记录都有符号字段",
        "tests/test_report.py::test_approximate_record_without_symbols_key_is_rendered",
        "渲染层对 `approximate=true` 的记录直接下标取 `symbols` → 「没有这个键也能渲染」必须变红"
        "（M4 起点快照点名的已知形态）",
    ),
    Mutation(
        "M32",
        "src/agent_conflict_radar/report.py",
        "    return SUGGESTIONS.get(record.get(\"severity_key\", \"\"), SUGGESTION_FALLBACK)",
        "    return SUGGESTIONS[\"same_symbol\"]  # 变异：建议不再按档位分派",
        "tests/test_report.py::test_suggestions_are_rule_templates_keyed_by_engine_severity",
        "建议模板不按 `severity_key` 分派（所有档位同一句）→ 规则模板判据必须变红",
    ),
    Mutation(
        "M33",
        "src/agent_conflict_radar/report.py",
        "    for index, record in enumerate(sorted_for_display(conflicts), start=1):",
        "    for index, record in enumerate(conflicts, start=1):  # 变异：不再按严重度排序",
        "tests/test_report.py::test_display_order_is_severity_desc_then_level_and_path",
        "报告不再按 severity 降序（直接用引擎的数组序）→ 展示序判据必须变红",
    ),
    Mutation(
        "M34",
        "src/agent_conflict_radar/exit_codes.py",
        "ALL_EXIT_CODES = (\n    EXIT_OK,\n    EXIT_CONFLICTS_FOUND,\n    EXIT_USAGE,\n    EXIT_ENVIRONMENT,\n)",
        "EXIT_NOT_READY = 4  # 变异：复活退出码 4\n"
        "ALL_EXIT_CODES = (\n    EXIT_OK,\n    EXIT_CONFLICTS_FOUND,\n    EXIT_USAGE,\n"
        "    EXIT_ENVIRONMENT,\n    EXIT_NOT_READY,\n)",
        "tests/test_cli_contract.py::test_exit_not_ready_constant_is_gone_and_stays_gone",
        "把退役的 `EXIT_NOT_READY = 4` 加回来（幽灵语义复活）→ `not hasattr` 防复活断言必须变红。"
        "这是 K1 四步里第②步点名要求的那条守门",
    ),
    Mutation(
        "M35",
        "src/agent_conflict_radar/bench/score.py",
        "    missing = expected_norm - actual_norm\n    extra = actual_norm - expected_norm",
        "    missing = set()  # 变异：只认多报，漏报永远不报\n"
        "    extra = actual_norm - expected_norm",
        "tests/test_bench.py::test_bench_fails_when_a_truth_expectation_is_changed",
        "评分函数把 `missing` 恒置空（漏报永远抓不到）→ 「改一位期望值必须报未达标」这条"
        "**打在消费处的探活**必须变红。这是 M5 DoD 硬要求的变异组：只断言正常时 PASS 的基准，"
        "可能根本没在比对",
    ),
    Mutation(
        "M36",
        "src/agent_conflict_radar/bench/score.py",
        '    expected_exit = 1 if truth.get("levels_expected") else 0',
        '    expected_exit = 0  # 变异：退出码期望恒为 0（不再按真值推）',
        "tests/test_bench.py::test_every_scenario_passes_on_the_frozen_matrix",
        "评分把 detect 退出码的期望恒置 0（不再由真值推出）→ 全矩阵 PASS 断言必须变红，"
        "证明退出码那一项不是装饰",
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
