"""路径解析：仓库根发现 + expanduser 哨兵（K16）。

两条本机实测纪律（SKILL「本机环境陷阱」+「expanduser 哨兵」条）：

1. **Windows 上路径有两套写法**：Git Bash 里 `~` 展开成 `/c/Users/...`，而 Windows Python 不认——
   所以 shell 展开的结果**不能**直接喂给 Python，一律在 Python 侧用 `expanduser` + `pathlib`。
2. **`expanduser("~")` 解不出主目录时会把 `~` 原样返回**（不抛异常、`except` 防不住），
   天真实现就会在当前目录下建一个名为 `~` 的文件夹。本模块**按哨兵比对**：
   检测到"展开后仍是 `~` 起头"，就显式报错——不写盘、不回落 CWD。
"""

import os
from pathlib import Path
from typing import Optional

from .errors import ConfigError, EnvironmentError_

#: pyproject.toml 是仓库根的标记文件（src 布局下它一定在包目录之上）。
_REPO_MARKERS = ("pyproject.toml",)


def expand_home(raw: str) -> str:
    """展开 `~`，但**按哨兵比对**：解不出主目录就显式报错，绝不回落 CWD。

    返回展开后的路径字符串；非 `~` 起头的输入原样返回。
    """
    if not raw.startswith("~"):
        return raw
    expanded = os.path.expanduser(raw)
    if expanded == raw or expanded.startswith("~"):
        raise EnvironmentError_(
            "无法解析主目录（expanduser 原样返回哨兵 %r）：请改传绝对路径或设置对应环境变量。"
            "本工具不会在当前位置创建名为 '~' 的目录，也不会回落当前目录。" % raw
        )
    return expanded


def normalize_path(raw: str) -> Path:
    """展开 `~` 并做词法归一（`..` / 重复分隔符），**不解析符号链接**、不要求路径存在。

    不 resolve 符号链接是有意的：worktree 的路径可能本身就是符号链接，
    resolve 会把它改写成另一个路径，导致"工作区 ↔ 会话 cwd"匹配失败。
    """
    expanded = expand_home(raw)
    return Path(os.path.normpath(expanded))


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """从 `start`（默认本模块所在目录）向上找含 pyproject.toml 的目录。

    返回 `None` 表示没找到——调用方必须显式处理（通常是报错并提示用参数指定），
    **不得**回落 CWD（回落会让"找不到数据"看起来像"数据在别处"）。
    """
    current = Path(start) if start is not None else Path(__file__).resolve().parent
    for candidate in (current,) + tuple(current.parents):
        for marker in _REPO_MARKERS:
            if (candidate / marker).is_file():
                return candidate
    return None


def require_repo_root(start: Optional[Path] = None) -> Path:
    """`find_repo_root` 的报错版：找不到就抛 `ConfigError`（exit 3）。"""
    root = find_repo_root(start)
    if root is None:
        raise ConfigError(
            "找不到仓库根（向上未发现 pyproject.toml）：请用 --config 显式指定配置文件。"
        )
    return root
