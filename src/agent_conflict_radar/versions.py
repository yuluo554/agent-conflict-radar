"""会话格式指纹与显式版本集合（K7）。

设计取舍（故意选"贵"的那条）：版本集合是**显式枚举**，不认识的版本一律报
`unsupported_format` 并列出缺失键。代价是新 harness 版本要手写进本文件；
换来的是"未知版本一定报错，而不是按最宽松规则静默错解"。

⚠️ **M0 骨架期状态**：下面的字段名来自题面与 data/README 的描述，属**猜测**，
必须被 M1 的实测勘误（见 plan/07 §六 G-1…G-3、data/README §五 R1–R3）。
在勘误闭环前，未命中的形态只允许落 `unknown` / `unsupported_format`，**不得进入冲突判定**。

判别纪律（沿用 SKILL"按文件形态判别归属"条）：**归属按首行文件形态判别，不按目录名**——
目录名是"我们约定的"会漂，文件形态是源工具产出的稳定事实。
"""

from typing import Dict, Optional, Tuple

#: 源标识（对外产物里统一用这两个值）。
SOURCE_CLAUDE = "claude"
SOURCE_CODEX = "codex"

#: 首行形态判别键：命中哪个键就归哪个源。
#: 这两个键来自"源工具自己的产出结构"（对话消息 vs 载荷），不是路径约定。
DISCRIMINATOR_KEYS = {
    SOURCE_CLAUDE: "message",
    SOURCE_CODEX: "payload",
}


class SessionSpec(object):
    """一个会话格式版本需要哪些键、以及版本指纹怎么认。"""

    def __init__(self, source, version, required_keys, optional_keys, discriminator_key):
        self.source = source
        self.version = version
        self.required_keys = tuple(required_keys)
        self.optional_keys = tuple(optional_keys)
        self.discriminator_key = discriminator_key


#: 显式版本集合。键 = (源, 版本指纹)，值 = 该版本的字段要求。
#: 版本指纹是 M0 的**临时标识**，M1 实测后按实际字段形态改名并补齐（保留原名 + 追加勘误注）。
SPECS: Dict[Tuple[str, str], SessionSpec] = {
    (SOURCE_CLAUDE, "claude-jsonl-m0-provisional"): SessionSpec(
        source=SOURCE_CLAUDE,
        version="claude-jsonl-m0-provisional",
        # 这些键名是 M0 的待核对猜测（不是"已知事实"）；勘误动作登记在 plan/07 §六 G-1。
        required_keys=("cwd", "gitBranch", "timestamp"),
        optional_keys=("sessionId", "parentUuid", "uuid", "type"),
        discriminator_key="message",
    ),
    (SOURCE_CODEX, "codex-jsonl-m0-provisional"): SessionSpec(
        source=SOURCE_CODEX,
        version="codex-jsonl-m0-provisional",
        required_keys=("payload", "timestamp"),
        optional_keys=("session_meta", "id", "type"),
        discriminator_key="payload",
    ),
}

#: 已识别版本指纹的显式集合（对外可见，便于测试与文档引用）。
KNOWN_VERSIONS = tuple(sorted(version for (_source, version) in SPECS))


def spec_for(source: str, version: str) -> Optional[SessionSpec]:
    """按显式集合取版本规范；不在集合内返回 `None`（调用方必须报 unsupported_format）。"""
    return SPECS.get((source, version))


def detect_source(first_line: dict) -> Optional[str]:
    """按首行 JSON 的形态判别归属；两者都不含时返回 `None`（调用方显式报错，不猜默认源）。"""
    for source, key in sorted(DISCRIMINATOR_KEYS.items()):
        if key in first_line:
            return source
    return None


def missing_keys(first_line: dict, spec: SessionSpec) -> Tuple[str, ...]:
    """返回该行缺失的必需键（用于 `unsupported_format` 的点名报错，不静默补编）。"""
    return tuple(key for key in spec.required_keys if key not in first_line)
