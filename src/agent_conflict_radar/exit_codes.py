"""退出码语义（K1，全项目唯一允许出现退出码字面量的模块）。

本题面锁定的**四语义**（`plan/01` §M4）：

    0  无冲突
    1  有冲突
    2  用法错误（未知子命令 / 缺必填参数 / 未知 --format / 路径不存在）
    3  依赖或环境缺失（git 不可用 / 配置缺失或不可解析 / 会话源不存在）

**骨架期的第五个（4 = 阶段未就绪）已于 M5 整条退役**：M5 交付 `bench` 后命令面 7/7 全部落地，
"阶段未就绪"不再对应任何真实状态。退役按 K1 四步走完（删常量 → 改 CLI/stages/测试 +
`not hasattr` 防复活 → 改 README → 改决策记录）。复活它的代价必须是"当场变红"，
而不是"悄悄多一个没人消费的码"。
"""

EXIT_OK = 0
EXIT_CONFLICTS_FOUND = 1
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3

#: 冻结的退出码集合。测试断言它与 README 的退出码表、与 cli.py 的分派一致。
ALL_EXIT_CODES = (
    EXIT_OK,
    EXIT_CONFLICTS_FOUND,
    EXIT_USAGE,
    EXIT_ENVIRONMENT,
)

#: 语义标签。`radar selftest` 与 README 对账门都从这里渲染，避免文案各写一份。
EXIT_CODE_LABELS = {
    EXIT_OK: "无冲突",
    EXIT_CONFLICTS_FOUND: "有冲突",
    EXIT_USAGE: "用法错误",
    EXIT_ENVIRONMENT: "依赖或环境缺失",
}
