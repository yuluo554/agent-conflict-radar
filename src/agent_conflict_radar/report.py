"""M4 预警报告（`radar report` 的实现主体）：Markdown 人读 + JSON 机读，单一渲染源。

## 输入是 M3 的 `ConflictSet`，**这里零判定**（K13）

渲染层只消费既有结论：不重新解析会话、不重读磁盘 diff、不重跑 `merge-tree`、不重算
`levels` / `symbols` / `severity`。`detect.build_conflict_set()` 在本模块之外被调用一次
（CLI 层），本模块拿到的就是最终产物。

**单一渲染源**的结构性落法：先把 `ConflictSet.as_dict()` 固定成一份 `payload`（它就是
`detect` 落盘的 `conflicts.json` 内容），Markdown 由 `render_markdown(payload, ...)` 这个
**纯函数**渲染。于是：

* `report --format json` 与 `detect` 的 `conflicts.json` **同内容同字节**（同一份 `payload`）；
* Markdown 与 JSON 的一致性不靠人工比对，而靠"两者是同一份 dict 的两个视图"这条结构性质
  （`tests/test_report.py` 对同一 payload 重渲染必须逐字节相同，并做了"改 payload → Markdown 跟着变"
  的可证伪探针）。

## 渲染三律（K13）

1. **零判定**：不 import `detect` / `intent` / `discover` 的任何函数；对记录只做"读字段 + 排版"。
   `tests/test_report.py` 用 AST 门禁扫本文件（含可证伪探针）。
2. **零外链**：`render_markdown` 的**出口**常驻 `serialize.assert_no_external_resources`
   ——每一次真实生成的报告都被拦，而不是只在测试里验一次。
3. **双跑逐字节一致**：不读时钟（`reference_time` 来自 payload）；排序用稳定排序；
   证据条数上限读 `report.max_evidence_items`（不写内联数值）。

## 数值口径（K3 / K5）

本模块里**没有策略数值字面量**：唯一出现的整数是结构性的 `0` / `1`（下标、起点、计数增量）。
参数来源块只写**键名与来源路径**，**不复制数值**——报告里任何阈值都要能被 `radar config`
复核。`[severity]` 的权重同理：报告只显示档名（`same_symbol` 等），不印分数。

## 建议是规则模板，不是模型判断（`plan/04` M4）

| 引擎给出的 `severity_key` | 固定文案 |
|---|---|
| `same_symbol` | 两侧并行改同一符号，需人工裁决 |
| `same_file_diff_symbol` | 仅同文件不同符号，可先后提交 |
| `adjacent_lines` | 改动范围相邻，建议由更早开始的会话先合并 |
| `file_only` | 仅文件级同改（无符号级证据），先确认两侧改动范围再决定合并顺序 |

分派键取自 payload 的 `severity_key` 字段（引擎产物），**不是**本模块的推断。

## 退出码（K1）

`conflicts` 非空 → `1`；为空 → `0`。`undetermined` / `degraded` / `approximate` **不改**退出码，
但在报告里逐条列出——"没底"绝不能读成"没问题"。

## 可选通知

`report.notify=false`（默认）→ 不尝试，报告写明"未尝试"。
`true` → 尝试本机**零依赖**的桌面通知通道（Windows 当前没有这种通道：不引第三方库、不联网）；
不可用时**静默跳过**，报告标 `notify_unavailable` 并写明原因，**不影响主流程与退出码**。
"""

import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import serialize

#: 粒度的**展示**顺序（由粗到细）。刻意不从 `detect` import：本模块要能只对着
#: 序列化后的 payload 工作（"渲染层不认识引擎对象"就是单一渲染源的前提）。
#: 与 `detect.LEVEL_ORDER` 的一致性由 `tests/test_report.py` 的一条漂移守卫钉住。
REPORT_LEVEL_ORDER = ("file", "block", "symbol")

#: 建议模板（按引擎给的 `severity_key` 分派；见模块文档表格）。
SUGGESTIONS = {
    "same_symbol": "两侧并行改同一符号，需人工裁决。",
    "same_file_diff_symbol": "仅同文件不同符号，可先后提交。",
    "adjacent_lines": "改动范围相邻，建议由更早开始的会话先合并。",
    "file_only": "仅文件级同改（无符号级证据），先确认两侧改动范围再决定合并顺序。",
}

#: 兜底文案：引擎将来新增档位而本表没跟上时，报告仍要给出可读的建议，
#: 但**不得**编造"这种情况更严重"之类的判断。
SUGGESTION_FALLBACK = "此档位没有预置建议模板：请按两侧改动范围人工裁决。"

#: 报告标题里的固定声明（DoD：必须含"辅助参考"，不得声称能"防止所有覆盖"）。
DISCLAIMER = (
    "判定为**辅助参考**，处置由你决定。本工具只读分析、不合并、不解决冲突、不接管编排；"
    "它的价值是提前量，不是安全边界——它不能让错误的合并变正确。"
)


# --------------------------------------------------------------------------------------
# 通知（可选；零依赖、零网络）
# --------------------------------------------------------------------------------------


def _notification_channel():
    """返回本机可用的零依赖通知通道 `(可执行文件名, argv 构造器)`；没有则 `None`。

    * Windows：**没有**可用的零依赖通道。用 PowerShell 弹 toast 依赖系统脚本策略与用户会话，
      失败方式还不可判定——与其"写了通知但没人验过"，不如如实报 `notify_unavailable`。
    * macOS：`osascript`（系统自带）。
    * 其余 POSIX：`notify-send`（是否安装用 `shutil.which` 现场判定）。
    """
    if sys.platform.startswith("win"):
        return None
    if sys.platform == "darwin":
        return (
            "osascript",
            lambda title, body: [
                "osascript",
                "-e",
                'display notification "%s" with title "%s"' % (_quote_applescript(body), _quote_applescript(title)),
            ],
        )
    return ("notify-send", lambda title, body: ["notify-send", title, body])


def _quote_applescript(text: str) -> str:
    """AppleScript 字符串转义（只处理双引号与反斜杠，避免命令被内容截断）。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify_status(cfg, title: str, body: str, channel_resolver=None) -> Dict[str, Any]:
    """按配置尝试桌面通知，返回可渲染的状态（**永不抛异常**）。

    返回 `{"attempted", "available", "detail"}`：`attempted` 只看配置，`available` 表示
    这次通知真的送达了。不可用一律 `available=False` + 人工可读的 `detail`——
    报告据此写 `notify_unavailable`，主流程与退出码不受影响。
    """
    if not cfg.get("report", "notify"):
        return {"attempted": False, "available": False, "detail": "report.notify=false：未尝试桌面通知"}
    resolver = channel_resolver if channel_resolver is not None else _notification_channel
    channel = resolver()
    if channel is None:
        return {
            "attempted": True,
            "available": False,
            "detail": "本机没有零依赖的桌面通知通道（不引第三方库、不联网）",
        }
    executable, build = channel
    if shutil.which(executable) is None:
        return {"attempted": True, "available": False, "detail": "通知命令 %r 不在 PATH 上" % executable}
    try:
        # 超时沿用 `git.timeout_seconds`：K3 要求数值只来自配置，不为通知再增设一个内联数值。
        subprocess.run(
            build(title, body),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=cfg.get("git", "timeout_seconds"),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"attempted": True, "available": False, "detail": "通知命令执行失败：%s" % exc}
    return {"attempted": True, "available": True, "detail": "已通过 %r 发送桌面通知" % executable}


# --------------------------------------------------------------------------------------
# 排版小工具（只读字段，不做判断）
# --------------------------------------------------------------------------------------


def _cell(text: Any) -> str:
    """表格单元格：把竖线与换行压平（否则一个 `|` 就能把表格切坏）。"""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _ordered_levels(levels: Sequence[str]) -> List[str]:
    """按展示顺序排粒度；出现本模块不认识的粒度时追加在末尾（**不丢字段**）。"""
    known = [level for level in REPORT_LEVEL_ORDER if level in levels]
    extras = sorted(level for level in levels if level not in REPORT_LEVEL_ORDER)
    return known + extras


def _levels_text(levels: Sequence[str]) -> str:
    return " / ".join("`%s`" % level for level in _ordered_levels(levels))


def _suggestion(record: Dict[str, Any]) -> str:
    return SUGGESTIONS.get(record.get("severity_key", ""), SUGGESTION_FALLBACK)


def _notify_line(status: Dict[str, Any]) -> str:
    if not status.get("attempted"):
        return "未尝试（`report.notify=false`）"
    if not status.get("available"):
        return "不可用（`notify_unavailable`：%s）" % status.get("detail", "")
    return "已发送（%s）" % status.get("detail", "")


def _ranges_text(ranges: Sequence[Sequence[int]]) -> str:
    return " ↔ ".join("[%d, %d]" % (item[0], item[1]) for item in ranges) if ranges else "（无可比区间）"


def sorted_for_display(conflicts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """人读报告的展示序：`severity` 降序，同分按 `(level 序, path, symbols)`（稳定排序）。

    **只作用于 Markdown 视图**：`conflicts.json` 原样等于 `detect` 的产物（同内容同字节），
    不在这里重排——两份产物同源的前提是"JSON 不被渲染层改写"。
    `severity` 数值由引擎按 `[severity]` 权重给出；本函数只比较，不复制权重。
    """
    def _key(record):
        levels = list(record.get("levels") or [])
        level = record.get("level") or ""
        rank = REPORT_LEVEL_ORDER.index(level) if level in REPORT_LEVEL_ORDER else len(REPORT_LEVEL_ORDER)
        return (
            -int(record.get("severity") or 0),
            rank,
            record.get("workspace_a") or "",
            record.get("workspace_b") or "",
            record.get("path") or "",
            tuple(record.get("symbols") or ()),
            tuple(tuple(item) for item in (record.get("line_ranges") or [])),
            tuple(levels),
        )

    return sorted(conflicts, key=_key)


# --------------------------------------------------------------------------------------
# 渲染：Markdown（payload 的纯函数）
# --------------------------------------------------------------------------------------


def render_markdown(
    payload: Dict[str, Any],
    source_path: str,
    repo: Optional[str] = None,
    notify: Optional[Dict[str, Any]] = None,
    max_evidence_items: Optional[int] = None,
) -> str:
    """把 `payload`（= `ConflictSet.as_dict()`）渲染成 Markdown 报告。

    **纯函数**：只读 `payload` 与显式传入的渲染参数，不读时钟、不读磁盘、不调用引擎。
    出口常驻零外链断言（K13）。
    """
    conflicts = list(payload.get("conflicts") or [])
    undetermined = list(payload.get("undetermined") or [])
    notes = list(payload.get("notes") or [])
    counts = dict(payload.get("counts") or {})
    reference_time = payload.get("reference_time") or ""
    notify = notify or {"attempted": False, "available": False, "detail": "report.notify=false：未尝试桌面通知"}

    lines: List[str] = []
    add = lines.append

    add("# 并行冲突预警报告")
    add("")
    add("> %s" % DISCLAIMER)
    add("")
    add("## 生成信息")
    add("")
    add("- 参考时刻（`reference_time`）：`%s`" % (reference_time or "（未提供）"))
    add("- 扫描范围（`--repo`）：%s" % ("`%s`" % repo if repo else "（未记录）"))
    add("- 产物：Markdown（人读）+ `conflicts.json`（机读，冻结序列化契约 K2）")
    add("- 桌面通知：%s" % _notify_line(notify))
    add("")

    # ---- 参数来源块（K3：只写键名与来源，不复制数值）----
    add("## 参数来源")
    add("")
    add("数值只有一个来源：`config/radar.toml`。本报告**不复制**任何数值——"
        "要核对生效值请跑 `radar config`（输出含 `source_path`）。")
    add("")
    add("- 生效配置（`source_path`）：`%s`" % source_path)
    add("- 扫描窗口：`window.scan_days`")
    add("- 活跃窗：`window.active_minutes`")
    add("- 相邻容差：`symbol.adjacent_tolerance`")
    add("- 重叠最小行数：`symbol.min_overlap_lines`（**遗留键**：登记键名以保持键空间完整；"
        "当前判定规则不使用它——见 docs/技术报告.md §九）")
    add("- 严重度档位：`[severity]`（`same_symbol` / `same_file_diff_symbol` / `adjacent_lines` / `file_only`）")
    add("- 区块级试合并开关：`git.merge_tree_enabled`")
    add("- 单条证据条数上限：`report.max_evidence_items`")
    add("")

    # ---- 结论摘要 ----
    entry_count = counts.get("conflicts", len(conflicts))
    add("## 结论摘要")
    add("")
    add("- 冲突条目数：%s" % entry_count)
    add("- 涉及文件数：%s" % counts.get("paths_in_conflict", "（未提供）"))
    add("- 未判定条目数：%s（`undetermined`，**不计入**冲突条目数）" % counts.get("undetermined", len(undetermined)))
    add("- 降级 / 近似：`degraded` %s 条 / `approximate` %s 条"
        % (counts.get("degraded", "（未提供）"), counts.get("approximate", "（未提供）")))
    add("- 试合并实际执行次数：%s（同一分支对只跑一次）" % counts.get("merge_tree_runs", "（未提供）"))
    if "derived_sibling_pairs_skipped" in counts:
        add("- 因 `derived_from` 相同而按默认口径不产出的组合：%s（去重留痕）"
            % counts["derived_sibling_pairs_skipped"])
    add("")
    add("粒度计数两栏（口径不同，**分开看**，K12）：")
    add("")
    add("| 口径 | " + " | ".join(REPORT_LEVEL_ORDER) + " |")
    add("|---|" + "---|" * len(REPORT_LEVEL_ORDER))
    by_max = dict(counts.get("by_max_level") or {})
    by_member = dict(counts.get("by_level_membership") or {})
    add("| 条目数（按**最高**粒度的集合划分，合计 = 冲突条目数） | "
        + " | ".join(str(by_max.get(level, "（未提供）")) for level in REPORT_LEVEL_ORDER) + " |")
    add("| 成员数（各粒度在命中集合里出现的次数，可大于条目数） | "
        + " | ".join(str(by_member.get(level, "（未提供）")) for level in REPORT_LEVEL_ORDER) + " |")
    add("")
    add("> `levels` 是命中的粒度**集合**；`level` 只是其中最高的一档，用于排序与严重度展示，"
        "**不是**「唯一粒度」。")
    add("")

    # ---- 冲突列表 ----
    add("## 冲突明细")
    add("")
    if not conflicts:
        add("**无冲突条目。**")
        if undetermined:
            add("")
            add("> 注意：仍有 %d 条未判定条目（见下节）——「没检出」与「没判准」是两件事。"
                % len(undetermined))
        add("")
    for index, record in enumerate(sorted_for_display(conflicts), start=1):
        add("### %d. `%s`（最高粒度 `%s`）" % (index, record.get("path", ""), record.get("level", "")))
        add("")
        levels = list(record.get("levels") or [])
        add("- 命中粒度集合：%s" % (_levels_text(levels) if levels else "（未提供）"))
        workspace_a = record.get("workspace_a", "")
        workspace_b = record.get("workspace_b", "")
        if workspace_a == workspace_b:
            add("- 工作区：`%s`（同一工作区内的两个会话）" % workspace_a)
        else:
            add("- 工作区：`%s` ↔ `%s`" % (workspace_a, workspace_b))
        sessions = list(record.get("sessions") or [])
        session_ids = list(record.get("session_ids") or [])
        if sessions:
            add("- 涉及会话：%s" % " / ".join("`%s`" % item for item in sessions))
        if session_ids:
            add("- 会话 id：%s" % " / ".join("`%s`" % item for item in session_ids))
        witness_a = list(record.get("sessions_a") or [])
        witness_b = list(record.get("sessions_b") or [])
        if witness_a and witness_b:
            add("- 见证对（区间与符号结论的来源）：%s ↔ %s"
                % (" / ".join("`%s`" % item for item in witness_a),
                   " / ".join("`%s`" % item for item in witness_b)))
        add("- 最后写入时间：`%s`" % (record.get("last_write_ts") or "（未提供）"))
        if "symbols" in record:
            symbols = list(record.get("symbols") or [])
            add("- 命中符号：%s" % (" / ".join("`%s`" % name for name in symbols) if symbols else "（空集合）"))
            spans = list(record.get("symbol_spans") or [])
            if spans:
                add("- 符号区间：%s" % " / ".join("`%s`@%s-%s" % (item[0], item[1], item[2]) for item in spans))
        else:
            add("- 命中符号：（本条 `approximate=true`，**不提供**符号级字段——那是「我们没做」，"
                "不是「没有符号命中」）")
        add("- 见证区间：%s" % _ranges_text(list(record.get("line_ranges") or [])))
        add("- 严重度档：`%s`（权重见 `[severity]`）" % record.get("severity_key", ""))
        add("- 建议：%s" % _suggestion(record))
        if record.get("degraded"):
            reasons = list(record.get("degrade_reasons") or [])
            add("- 区块级未能判定（`degraded`）：粒度降为文件级%s"
                % ("；" + "；".join(reasons) if reasons else "（原因见「未判定」小节）"))
        if record.get("approximate"):
            add("- 未做符号级（`approximate`）：非 Python 文件 / 取不到基线 / 跨工作区")
        evidence = list(record.get("evidence") or [])
        if evidence:
            shown = evidence if max_evidence_items is None else evidence[:max_evidence_items]
            add("- 证据（最多 `report.max_evidence_items` 条，完整列表见 `conflicts.json`）：")
            if shown:
                for item in shown:
                    add("  - `%s`" % item)
            hidden = len(evidence) - len(shown)
            if hidden:
                add("  - …另有 %d 条（见 `conflicts.json`）" % hidden)
        else:
            add("- 证据：（无）")
        add("")

    # ---- 未判定（独立小节）----
    add("## 未判定（`undetermined`）")
    add("")
    add("> 这一节是「**我们没判准**」，不是「没有冲突」。这些条目**不计入**冲突条目数，"
        "也**不改变**退出码；但绝不能省略不写。")
    add("")
    if undetermined:
        add("| 文件 | 来源 | 原因码 | 说明 |")
        add("|---|---|---|---|")
        for item in undetermined:
            add("| %s | %s | %s | %s |" % (
                _cell(item.get("file", "")),
                _cell(item.get("source", "")),
                _cell(item.get("code", "")),
                _cell(item.get("detail", "")),
            ))
        add("")
    else:
        add("引擎没有给出 `undetermined` 条目。")
        add("")
    approximate_records = [item for item in conflicts if item.get("approximate")]
    degraded_records = [item for item in conflicts if item.get("degraded")]
    if approximate_records:
        add("带 `approximate` 标注的冲突条目（不做符号级，**不是**「没有符号命中」）：")
        add("")
        for item in approximate_records:
            add("- `%s`（最高粒度 `%s`）" % (item.get("path", ""), item.get("level", "")))
        add("")
    if degraded_records:
        add("带 `degraded` 标注的冲突条目（区块级未判定，粒度降为文件级）：")
        add("")
        for item in degraded_records:
            add("- `%s`" % item.get("path", ""))
        add("")
    if not undetermined and not approximate_records and not degraded_records:
        add("没有需要单独披露的降级/近似条目。")
        add("")

    # ---- 引擎说明（含只读边界披露）----
    add("## 引擎说明")
    add("")
    if notes:
        for note in notes:
            add("- %s" % note)
    else:
        add("- （引擎未附加说明）")
    add("")
    add("## 处置边界")
    add("")
    add("- 本工具**不执行** merge / rebase，**不写** git 索引，**不修改**工作区，**不合并**任何分支。")
    add("- 判定为辅助参考：最终处置（先后合并顺序、人工裁决）由你决定。")
    add("- 涉及阈值与窗口的数值一律以 `config/radar.toml` 为准；本报告不复制数值。")
    add("")

    text = serialize.normalize_newlines("\n".join(lines))
    # 常驻渲染出口断言：真实生成的每一份报告都过这道门（K13 零外链）。
    serialize.assert_no_external_resources(text, where="report.md")
    return text


# --------------------------------------------------------------------------------------
# 组装（单一渲染源）
# --------------------------------------------------------------------------------------


class ReportSurface(object):
    """一份报告的**唯一中间面**：JSON payload + 由它渲染出的 Markdown。

    `payload` 就是 `ConflictSet.as_dict()`，也就是 `conflicts.json` 的内容；
    `markdown` 是 `payload` 的纯函数结果。两者同源，不需要"人工比对两份产物"。
    """

    __slots__ = ("payload", "markdown", "notify")

    def __init__(self, payload, markdown, notify):
        self.payload = payload
        self.markdown = markdown
        self.notify = dict(notify)

    def json_text(self) -> str:
        """按冻结契约（K2）序列化——与 `detect` 落盘的 `conflicts.json` 逐字节同源。"""
        return serialize.dumps_json(self.payload)


def build_report(conflict_set, cfg, repo=None, notify=None) -> ReportSurface:
    """把 M3 的 `ConflictSet` 变成一份报告面（**不重算任何判定**）。

    `notify` 可显式传入（测试用）；缺省按 `report.notify` 尝试一次桌面通知。
    """
    payload = conflict_set.as_dict()
    if notify is None:
        notify = notify_status(
            cfg,
            title="并行冲突雷达：%d 条冲突" % len(payload.get("conflicts") or []),
            body="有冲突条目，详见 report.md" if payload.get("conflicts") else "未检出冲突条目",
        )
    markdown = render_markdown(
        payload,
        source_path=str(cfg.source_path),
        repo=repo,
        notify=notify,
        max_evidence_items=cfg.get("report", "max_evidence_items"),
    )
    return ReportSurface(payload=payload, markdown=markdown, notify=notify)
