"""阶段未就绪表（K15 单点）：哪些命令已交付、哪些还在计划里程碑里。

这一张表是骨架期的**唯一**真相，三个消费者共用：

* `cli.py` —— 未交付的命令直接退出码 4（**不伪造空结果**）；
* `tools/verify_offline.py` —— 断言"冒烟覆盖的命令集合 == 本表命令集合"（并排数一遍）；
* 测试 —— 断言这两个集合互补且不重叠，且没有命令被漏分类。

**每棒交付一条命令时**（K15）：把它的名字从 `STAGE_NOT_READY` 移到 `DELIVERED_COMMANDS`，
同一次提交里退役它在 CI/冒烟里的旧"退出码 4"断言、补一条离线冒烟，并改 README 退出码表。
四处不同步 = 绿矩阵变成装饰（断言过期会让 CI 四腿同点全红，或让命令从未被真跑过）。
"""

#: 已交付：命令存在且行为完整。
#: 每往这里挪一条命令（K15），必须同一次提交里：退役它的 exit 4 断言 + 补离线冒烟 + 改 README。
#:
#: ⚠️ M1 未完成：`scan` 的实现（`discover.py`）已落盘但**尚未接线、尚未有测试**，
#: 所以它**仍留在阶段未就绪表里**——按纪律，没有测试与冒烟的交付不算交付。
#: 接线动作与所需口径见 `plan/HANDOFF-M1.md` §五（M1 进度快照）。
DELIVERED_COMMANDS = (
    "config",
    "selftest",
)

#: 阶段未就绪：命令已注册参数（README 里的用法可以照抄），但实现还没落地。
#: 值 = 计划交付该命令的里程碑（消息里原样带出，便于用户判断进度）。
STAGE_NOT_READY = {
    "scan": "M1",
    "intent": "M2",
    "detect": "M3",
    "report": "M4",
    "bench": "M5",
}

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
    """全部已注册命令（已交付 + 阶段未就绪），按 COMMAND_ORDER 排序。"""
    known = set(DELIVERED_COMMANDS) | set(STAGE_NOT_READY)
    ordered = [name for name in COMMAND_ORDER if name in known]
    missing = sorted(known - set(ordered))
    return tuple(ordered + missing)


def milestone_for(command: str):
    """返回该命令的计划里程碑；已交付的命令返回 `None`。"""
    return STAGE_NOT_READY.get(command)
