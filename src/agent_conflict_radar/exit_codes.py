"""退出码语义（K1，全项目唯一允许出现退出码字面量的模块）。

本题面锁定的四语义（plan/01 §M4）：

    0  无冲突
    1  有冲突
    2  用法错误（未知子命令 / 缺必填参数 / 未知 --format / 路径不存在）
    3  依赖或环境缺失（git 不可用 / 配置缺失或不可解析 / 会话源不存在）

骨架期另有第五个：

    4  阶段未就绪（该命令的计划里程碑尚未落地）

**为什么要有 4**：骨架期未实现的命令必须**显式拦截**——返回空 JSON 或"0 条冲突"都是
伪造空结果（把"没检查过"读成"没问题"，与判定类工具的正确性纪律相悖）。

**退役流程（K1 四步，缺一步即幽灵语义复活）**：
    ① 删本模块里的常量；
    ② 改 cli.py 与 stages.py，并改测试（含 `not hasattr(exit_codes, "EXIT_NOT_READY")` 防复活）；
    ③ 改 README 的退出码表；
    ④ 改 plan/07 决策记录与 K1 条目。
"""

EXIT_OK = 0
EXIT_CONFLICTS_FOUND = 1
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3
EXIT_NOT_READY = 4

#: 冻结的退出码集合。测试断言它与 README 的退出码表、与 cli.py 的分派一致。
ALL_EXIT_CODES = (
    EXIT_OK,
    EXIT_CONFLICTS_FOUND,
    EXIT_USAGE,
    EXIT_ENVIRONMENT,
    EXIT_NOT_READY,
)

#: 语义标签。`radar selftest` 与 README 对账门都从这里渲染，避免文案各写一份。
EXIT_CODE_LABELS = {
    EXIT_OK: "无冲突",
    EXIT_CONFLICTS_FOUND: "有冲突",
    EXIT_USAGE: "用法错误",
    EXIT_ENVIRONMENT: "依赖或环境缺失",
    EXIT_NOT_READY: "阶段未就绪（骨架期专用，随模块落地逐项退役）",
}
