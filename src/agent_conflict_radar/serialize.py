"""唯一写盘点 + 冻结序列化契约（K2）+ 报告零外链断言（K13）。

为什么必须单点：多个子命令各写各的 `open()+json.dump()` 时，迟早出现"两个产物一个带 BOM、
一个不带""一个 sort_keys 一个不排"的漂移。判别口诀是
**「换个命令，写盘形态会变吗？」**——会变就是漏了单点。

冻结契约（**动了会打挂基准**，K2）：
    json.dumps(sort_keys=True, ensure_ascii=False, indent=2) + LF + 结尾换行 + 原子写

* `ensure_ascii=False` 是中文项目的必选项：默认 `True` 会把中文转成 `\\uXXXX`，diff 不可读。
* LF 与结尾换行固定：否则 Windows 上 CRLF/无尾换行会让"逐字节一致"守门在跨平台时红。
* 原子写（临时文件 → `os.replace`）：中断不会留下半个产物。
"""

import json
import os
from pathlib import Path
from typing import Any, List, Optional

#: 冻结的序列化参数（K2）。任何调用方都不得自行传参覆盖。
FROZEN_JSON_KWARGS = {"sort_keys": True, "ensure_ascii": False, "indent": 2}

#: 文本产物的行尾（固定 LF，不随平台变）。
LINE_ENDING = "\n"

#: 报告里出现外部资源引用的形态（K13 零外链）。报告必须断网可打开。
_EXTERNAL_PATTERNS = (
    "http://",
    "https://",
    "//cdn",
    "<img",
    "src=",
    "@import",
)


def normalize_newlines(text: str) -> str:
    """把任意行尾统一成 LF，并保证结尾正好一个换行。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + LINE_ENDING


def dumps_json(payload: Any) -> str:
    """按冻结契约序列化（含结尾换行）。返回的字符串即最终落盘字节（utf-8 编码后）。"""
    return normalize_newlines(json.dumps(payload, **FROZEN_JSON_KWARGS))


def write_atomic(path: Path, text: str) -> Path:
    """把文本按冻结契约原子写入 `path`（不创建父目录——父目录由调用方先校验后创建）。"""
    target = Path(path)
    payload = normalize_newlines(text).encode("utf-8")
    tmp = target.with_name(target.name + ".tmp")
    with open(str(tmp), "wb") as handle:
        handle.write(payload)
    os.replace(str(tmp), str(target))
    return target


def write_json_atomic(path: Path, payload: Any) -> Path:
    """序列化 + 原子写的组合，供所有机读产物使用。"""
    return write_atomic(path, dumps_json(payload))


def find_external_resources(text: str) -> List[str]:
    """返回文本里出现的外部资源形态（去重、有序）。空列表 = 零外链。"""
    found = []
    lowered = text.lower()
    for pattern in _EXTERNAL_PATTERNS:
        if pattern in lowered and pattern not in found:
            found.append(pattern)
    return found


def assert_no_external_resources(text: str, where: str = "报告") -> None:
    """渲染出口的常驻硬断言（K13）。

    为什么不只在测试里验一次：报告是**每次运行都新生成**的产物，只有把断言放在渲染出口，
    才覆盖每一个真实生成的报告；放在测试里只覆盖测试构造的那一份。
    """
    found = find_external_resources(text)
    if found:
        raise ValueError(
            "%s 含外部资源引用 %s：报告必须断网可打开（K13 零外链）。"
            "若确需展示 URL 文本，请改为不构成引用的书写形式。" % (where, found)
        )
