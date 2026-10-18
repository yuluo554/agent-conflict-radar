"""命令交付表（K15 单点）：哪些命令已交付、命令的展示顺序与依赖要求。

这一张表是**唯一**真相，三个消费者共用：

* `cli.py` —— 分派与帮助文本（顺序取自 `COMMAND_ORDER`）；
* `tools/verify_offline.py` —— 断言"冒烟覆盖的命令集合 == 本表命令集合"（并排数一遍）；
* 测试 —— 断言"每条已交付命令在冒烟里有用例"，且**没有第三种默认状态**。

**M5 起命令面 7/7 全部交付**：`4 = 阶段未就绪` 已整条退役（K1 四步），
因此本模块只剩一张表——"未交付"不再是一种状态，也没有任何命令能落进它。
如果有人想重新加回"未就绪"拦截，必须同时改 CLI / 测试 / README / 决策记录（K1），
否则会被"已交付命令不得残留"与"每条命令都有真实契约冒烟"两条断言当场抓出。
"""

#: 已交付：命令存在且行为完整。
#: 每新增一条命令（K15），必须同一次提交里：补离线冒烟（模块 + console 两条通路）+ 改 README。
DELIVERED_COMMANDS = (
    "config",
    "selftest",
    # M1：`scan` 于 2026-10-17 交付（`discover.py` 实现 + 测试 + 离线冒烟）。
    "scan",
    # M2：`intent` 于 2026-10-18 交付（`intent.py` 实现 + 测试 + 离线冒烟）。
    "intent",
    # M3：`detect` 于 2026-10-18 交付（`detect.py` 三级检测 + 测试 + 离线冒烟）。
    # 这是**第一条真的会用退出码 1 的命令**：检出冲突 → 1，无冲突 → 0。
    "detect",
    # M4：`report` 于 2026-10-18 交付（`report.py` 单一渲染源 + 测试 + 离线冒烟）。
    # 退出码口径与 `detect` 相同：有冲突 → 1、无冲突 → 0；`undetermined` 只列不改码。
    "report",
    # M5：`bench` 于 2026-10-18 交付（`bench/score.py` 评分 + 测试 + 离线冒烟）。
    # 退出码口径：全部场景通过 → 0；任一失败 → 1；用法错误 → 2；依赖缺失 → 3。
    # 同一次提交里退役了 `EXIT_NOT_READY`（K1 四步）与它的全部断言。
    "bench",
)

#: CLI 里命令的展示顺序（帮助文本与 README 命令总表共用同一顺序）。
COMMAND_ORDER = (
    "scan",
    "intent",
    "detect",
    "report",
    "bench",
    "config",
    "selftest",
)

#: 需要 git 可用的命令（缺 git 一律 exit 3，不静默降级成"无冲突"）。
NEEDS_GIT = frozenset({"scan", "intent", "detect", "report", "bench"})


def all_commands():
    """全部已注册命令，按 `COMMAND_ORDER` 排序。"""
    ordered = [name for name in COMMAND_ORDER if name in DELIVERED_COMMANDS]
    missing = sorted(set(DELIVERED_COMMANDS) - set(ordered))
    return tuple(ordered + missing)
