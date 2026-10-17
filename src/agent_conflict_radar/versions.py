"""会话格式指纹与显式版本集合（K7）。

**本文件的字段名全部来自 M1 的本机只读实测**（基准日 2026-10-17，结论已三处同步：
本文件 / `plan/04-模块详设.md` M1 / `plan/07-交付对标与决策记录.md` §六 勘误表）。
`data/README.md` §五 的 R2 / R3 一并闭环。

设计取舍（故意选"贵"的那条）：版本集合是**显式枚举**，形状不认识的输入一律报
`unsupported_format` 并列出缺失键。代价是新 harness 版本要手写进本文件；换来的是
"未知版本一定报错，而不是按最宽松规则静默错解"。

判别纪律：**归属按行的结构形态判别，不按目录名**——目录名是"我们约定的"会漂，
行的键是源工具产出的稳定事实。

---

## 实测结论（M1 探针，只读，未打印任何 prompt 正文或真实路径）

### Claude Code（`~/.claude/projects/**/*.jsonl`，本机 125 个文件）

* 判别键：顶层 `message`（出现在 `type ∈ {assistant, user}` 的行上）。
* ⚠️ **首行通常不是消息行**：实测首行 `type` 分布为 `last-prompt`(58) / `queue-operation`(36) /
  `user`(28) / `started`(3)——所以**不能只看首行**判别归属与会话元信息，
  必须向下找第一条带判别键的行（`allowance`：见 `discover._first_message_line`）。
* 会话标识：`sessionId`（每文件恒 1 个值，122/125 文件满足）。
* 工作目录与分支：**逐行**顶层 `cwd` / `gitBranch`（承载于 `assistant` / `user` / `attachment` / `system` 行）。
* 时间戳：逐行顶层 `timestamp`。
* **subagent 标记**：`isSidechain` 为**布尔**且**按文件**一致（实测 94 个文件全 False、28 个全 True、
  3 个无该键且无消息行）。28 个 sidechain 文件**全部**与某个主文件共享 `sessionId`
  → 派生关系 = "同一 `sessionId` 下，isSidechain=False 的那只为父"。
* 写类工具调用（M2 用）：`message.content[]` 中 `type == "tool_use"` 的项，`name ∈ {Edit, Write}`
  带 `input.file_path`；Edit 带 `old_string`/`new_string`/`replace_all`，Write 带 `content`。
  **实测 `MultiEdit` 出现 0 次** → 按"本机 0 次出现的形态不编造"纪律，M2 遇到它按未知形态处理
  （落 `unknown` + 计注记），不得假装支持。
* 旁证（M2 可用）：`toolUseResult` 带 `filePath` / `structuredPatch` / `originalFile`（但它是
  **工具结果行**、不是调用行，只作旁证）。

### Codex（`~/.codex/sessions/**/*.jsonl`，本机 220 个文件）

* **首行恒为 `session_meta`**（实测 220/220）→ 会话元信息从首行取。
* 判别键：顶层 `payload`。
* `session_meta.payload` 实测键：`session_id`（仅主会话有，**63/220**）、`id`（220/220）、
  `timestamp`、`cwd`（**220/220 全覆盖**）、`originator`、`cli_version`、`thread_source`、
  `model_provider`、`context_window`、`parent_thread_id`（**157**）、`agent_nickname`、
  `agent_path`、`subagent_history_start_ordinal`、`multi_agent_version`、`forked_from_id`（152）、
  `runtime_workspace_roots`（6）。
* 时间戳：逐行顶层 `timestamp`（末行时间戳 50/50 抽样可得）。
* **派生关系**：`payload.parent_thread_id`；实测 157 个含该键的文件**全部**指向本机另一个文件的
  `session_id`。子会话**没有自己的 `session_id`** → 会话标识取 `session_id or id`。
* patch 形态：`response_item.payload.type == "custom_tool_call"` 且 `name == "apply_patch"`，
  `input` 为**字符串**，以 `*** Begin Patch` 开头，内含 `*** Update File:` / `*** Add File:` /
  `*** Delete File:` 行（M2 用）。另有 `function_call`（`arguments` 为字符串）与经 `exec`
  传入的 patch（同一形态的行内文本），M2 按"只认结构位"处理。
"""

from typing import Dict, Optional, Tuple

#: 源标识（对外产物里统一用这两个值）。
SOURCE_CLAUDE = "claude"
SOURCE_CODEX = "codex"

#: 格式版本指纹（显式集合；不在集内即报 unsupported_format）。
CLAUDE_JSONL_V1 = "claude-jsonl-v1"
CODEX_JSONL_V1 = "codex-jsonl-v1"

#: 判别键：顶层出现哪个键就归哪个源（实测：Claude 消息行带 `message`，Codex 每行带 `payload`）。
DISCRIMINATOR_KEYS = {
    SOURCE_CLAUDE: "message",
    SOURCE_CODEX: "payload",
}


class SessionSpec(object):
    """一个会话格式版本：判别键、必需键、以及怎么取会话标识/工作目录/派生关系。"""

    def __init__(
        self,
        source,
        version,
        discriminator_key,
        message_required_keys,
        meta_type=None,
        meta_required_keys=(),
        session_id_keys=("sessionId",),
        thread_id_keys=(),
        parent_keys=(),
        subagent_flag_key=None,
        cwd_key="cwd",
        timestamp_key="timestamp",
        branch_key=None,
    ):
        self.source = source
        self.version = version
        self.discriminator_key = discriminator_key
        #: 消息行（承载 cwd / 分支 / 时间戳 的那类行）必须带的键。
        self.message_required_keys = tuple(message_required_keys)
        #: 若有"元信息行"（Codex 的 session_meta），它的 type 值与必须带的 payload 键。
        self.meta_type = meta_type
        self.meta_required_keys = tuple(meta_required_keys)
        #: 会话标识候选键（按顺序取第一个存在者）。Codex 子会话没有 session_id，要靠 id。
        self.session_id_keys = tuple(session_id_keys)
        self.thread_id_keys = tuple(thread_id_keys)
        #: 派生关系键（指向父会话的标识）。
        self.parent_keys = tuple(parent_keys)
        #: subagent 布尔标记键（Claude 的 isSidechain）。按文件一致。
        self.subagent_flag_key = subagent_flag_key
        self.cwd_key = cwd_key
        self.timestamp_key = timestamp_key
        #: 分支键（Claude 的 gitBranch；Codex 无）。
        self.branch_key = branch_key


#: 显式版本集合。键 = (源, 版本指纹)。
SPECS: Dict[Tuple[str, str], SessionSpec] = {
    (SOURCE_CLAUDE, CLAUDE_JSONL_V1): SessionSpec(
        source=SOURCE_CLAUDE,
        version=CLAUDE_JSONL_V1,
        discriminator_key="message",
        # 实测：带 message 的行同时带 cwd / sessionId / timestamp。
        message_required_keys=("message", "cwd", "sessionId", "timestamp"),
        session_id_keys=("sessionId",),
        parent_keys=(),
        subagent_flag_key="isSidechain",
        cwd_key="cwd",
        timestamp_key="timestamp",
        branch_key="gitBranch",
    ),
    (SOURCE_CODEX, CODEX_JSONL_V1): SessionSpec(
        source=SOURCE_CODEX,
        version=CODEX_JSONL_V1,
        discriminator_key="payload",
        # 实测：每行都带 payload 与 timestamp；会话元信息在首行 session_meta.payload。
        message_required_keys=("payload", "timestamp"),
        meta_type="session_meta",
        meta_required_keys=("id", "timestamp", "cwd"),
        session_id_keys=("session_id", "id"),
        thread_id_keys=("id",),
        parent_keys=("parent_thread_id", "forked_from_id"),
        subagent_flag_key=None,
        cwd_key="cwd",
        timestamp_key="timestamp",
        branch_key=None,
    ),
}

#: 已识别版本指纹的显式集合（对外可见，便于测试与文档引用）。
KNOWN_VERSIONS = tuple(sorted(version for (_source, version) in SPECS))


def spec_for(source: str, version: str) -> Optional[SessionSpec]:
    """按显式集合取版本规范；不在集合内返回 `None`（调用方必须报 unsupported_format）。"""
    return SPECS.get((source, version))


def spec_for_source(source: str) -> SessionSpec:
    """取某源当前唯一的版本规范。（每源目前只有一个指纹；新增指纹要走决策记录。）"""
    candidates = [spec for (src, _v), spec in SPECS.items() if src == source]
    if len(candidates) != 1:
        raise KeyError(
            "源 %r 的版本指纹不是恰好一个（%d 个）：新增版本必须同步 discover 的判别与决策记录"
            % (source, len(candidates))
        )
    return candidates[0]


def detect_source(record: dict) -> Optional[str]:
    """按一条记录的顶层键判别归属；都不含判别键时返回 `None`（调用方显式报错，不猜默认源）。"""
    for source in sorted(DISCRIMINATOR_KEYS):
        if DISCRIMINATOR_KEYS[source] in record:
            return source
    return None


def missing_keys(record: dict, spec: SessionSpec) -> Tuple[str, ...]:
    """返回该记录缺失的必需键（用于 `unsupported_format` 的点名报错，不静默补编）。"""
    return tuple(key for key in spec.message_required_keys if key not in record)


def missing_meta_keys(payload: dict, spec: SessionSpec) -> Tuple[str, ...]:
    """Codex 元信息行的 payload 缺失键。"""
    return tuple(key for key in spec.meta_required_keys if key not in payload)
