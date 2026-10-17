"""错误体系 → 退出码的单点映射。

每个错误类型自带 `exit_code`，CLI 只做一件事：捕获 `RadarError` 并以 `e.exit_code` 退出。
**新增错误类型必须归入 K1 的语义之一**；不要在下游代码里另写一份"哪种情况给哪个码"的判断。
"""

from .exit_codes import EXIT_ENVIRONMENT, EXIT_NOT_READY, EXIT_USAGE


class RadarError(Exception):
    """所有可预期错误的基类。子类必须覆盖 `exit_code`。"""

    exit_code = EXIT_ENVIRONMENT


class UsageError(RadarError):
    """用法错误：未知子命令、缺必填参数、未知 --format、路径不存在。"""

    exit_code = EXIT_USAGE


class ConfigError(RadarError):
    """配置缺失/不可解析/键不合法。绝不回落默认值——回落即出现第二份真相（K3）。"""

    exit_code = EXIT_ENVIRONMENT


class TomlUnsupportedError(ConfigError):
    """TOML 超集形态：底线解释器 3.8 无 tomllib，自写子集解析器遇到不支持的形态必须显式报错。

    静默跳过会让配置里的数值**凭空消失**（K6）。错误信息必须带行号与形态描述。
    """


class EnvironmentError_(RadarError):
    """依赖或环境缺失：git 不可用、会话源根目录不存在、git 子进程超时。"""

    exit_code = EXIT_ENVIRONMENT


class ReadOnlyViolation(RadarError):
    """试图执行非只读的 git 子命令。只读纪律（K4）由 gitio 的子命令白名单硬拦。"""

    exit_code = EXIT_ENVIRONMENT


class StageNotReady(RadarError):
    """阶段未就绪：命令的计划里程碑尚未落地（骨架期专用）。"""

    exit_code = EXIT_NOT_READY  # 引用 exit_codes 常量，避免出现第二份 "4"

    def __init__(self, command: str, milestone: str) -> None:
        super().__init__(
            "命令 %r 尚未交付：计划在 %s 落地（骨架期显式拦截，不伪造空结果）" % (command, milestone)
        )
        self.command = command
        self.milestone = milestone
