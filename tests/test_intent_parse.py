"""`intent.py` 的纯函数级对账（不碰 git、不碰磁盘）。

三条判据在这里被钉死，因为它们最容易在"顺手优化"里被改坏：

1. **锚点定位返回全部命中**（而不是第一个）——挑第一个就等于把"不确定"伪装成"精确"；
2. **patch 解析只认结构位**（指令行 + hunk），上下文行不是锚点；
3. **路径归一不猜**：工具给的绝对路径不在会话 `cwd` 之下时，原样返回并标记"不在 cwd 之下"。
"""

import json

import pytest

from agent_conflict_radar import intent

# --------------------------------------------------------------------------------------
# 锚点定位 / 有效改动区间
# --------------------------------------------------------------------------------------


def test_find_anchor_hits_returns_every_hit_not_just_the_first():
    """多处命中必须**全部**返回：调用方据此降级；返回第一个就是编真值。"""
    base = ["def f():", "    x = 1", "", "def g():", "    x = 1"]
    hits = intent.find_anchor_hits(base, ["    x = 1"])
    assert hits == [1, 4], "命中位置必须全部返回（0-based）"
    assert intent.find_anchor_hits(base, ["    x = 2"]) == []
    assert intent.find_anchor_hits(base, []) == [], "空锚点不算命中（否则任何位置都'命中'）"


def test_effective_change_range_uses_new_file_coordinates():
    base = ["a", "b", "c", "d"]
    assert intent.effective_change_range(base, ["a", "B", "c", "d"]) == (2, 2)
    assert intent.effective_change_range(base, ["a", "b", "c", "d"]) is None, "逐行相同 → 没有改动"
    assert intent.effective_change_range(base, ["A", "b", "c", "D"]) == (1, 4)


def test_effective_change_range_handles_pure_insertion_and_deletion():
    base = ["a", "b"]
    assert intent.effective_change_range(base, ["a", "x", "b"]) == (2, 2)
    assert intent.effective_change_range(base, ["a"]) == (2, 1), "纯删除：空区间（end < start 由调用方判断）"


def test_sort_ranges_dedupes_and_sorts_without_merging():
    assert intent.sort_ranges([(9, 9), (2, 2), (9, 9)]) == [(2, 2), (9, 9)]
    # 不合并：合并会丢掉"这是两段改动"这个事实，逐条对账就无从下手。
    assert intent.sort_ranges([(2, 4), (5, 7)]) == [(2, 4), (5, 7)]


def test_looks_python_is_conservative():
    assert intent.looks_python("src/alpha.py") is True
    assert intent.looks_python("src/ALPHA.PY") is True
    assert intent.looks_python("docs/notes.md") is False
    assert intent.looks_python("src/Makefile") is False
    assert intent.looks_python("") is False


# --------------------------------------------------------------------------------------
# 路径归一：不猜
# --------------------------------------------------------------------------------------


def test_to_workspace_relative_keeps_paths_outside_cwd_verbatim():
    rel, inside = intent.to_workspace_relative("C:/repo/src/a.py", "C:/repo")
    assert (rel, inside) == ("src/a.py", True)
    rel, inside = intent.to_workspace_relative("C:/repo/sub/src/a.py", "C:/repo")
    assert (rel, inside) == ("sub/src/a.py", True)
    rel, inside = intent.to_workspace_relative("C:/other/src/a.py", "C:/repo")
    assert inside is False, "不在 cwd 之下必须显式标记（不猜它属于哪个仓库）"
    assert rel == "C:/other/src/a.py"


def test_clean_relative_rejects_escapes():
    assert intent._is_clean_relative("src/a.py") is True
    assert intent._is_clean_relative("../a.py") is False
    assert intent._is_clean_relative("C:/abs/a.py") is False
    assert intent._is_clean_relative("src\\a.py") is False
    assert intent._is_clean_relative("") is False


# --------------------------------------------------------------------------------------
# patch 解析（R2 形态）
# --------------------------------------------------------------------------------------


def test_parse_patch_instructions_reads_update_add_delete():
    text = (
        "*** Begin Patch\n"
        "*** Update File: src/alpha.py\n"
        "@@\n"
        "-    a = 1\n"
        "+    a = 2\n"
        "*** Add File: src/new.py\n"
        "+def f():\n"
        "+    return 1\n"
        "*** Delete File: src/old.py\n"
        "*** End Patch\n"
    )
    parsed = intent.parse_patch_instructions(text)
    assert [item[0] for item in parsed] == ["update", "add", "delete"]
    assert [item[1] for item in parsed] == ["src/alpha.py", "src/new.py", "src/old.py"]
    update_hunks = parsed[0][2]
    assert update_hunks == [(("    a = 1",), ("    a = 2",))], "hunk 的旧/新行必须分开收"
    add_hunks = parsed[1][2]
    assert add_hunks == [((), ("def f():", "    return 1"))]
    assert parsed[2][2] == [], "Delete File 没有 hunk"


def test_parse_patch_instructions_does_not_treat_context_lines_as_anchors():
    """上下文行（前缀一个空格）不是改动，**不得**混进锚点。"""
    text = (
        "*** Begin Patch\n"
        "*** Update File: src/alpha.py\n"
        "@@\n"
        " def f():\n"
        "-    a = 1\n"
        "+    a = 2\n"
        "*** End Patch\n"
    )
    parsed = intent.parse_patch_instructions(text)
    assert parsed[0][2] == [(("    a = 1",), ("    a = 2",))]


def test_parse_patch_instructions_splits_multiple_hunks():
    text = (
        "*** Begin Patch\n"
        "*** Update File: src/alpha.py\n"
        "@@\n"
        "-a\n"
        "+A\n"
        "@@\n"
        "-b\n"
        "+B\n"
        "*** End Patch\n"
    )
    parsed = intent.parse_patch_instructions(text)
    assert parsed[0][2] == [(("a",), ("A",)), (("b",), ("B",))]


def test_parse_patch_instructions_returns_empty_for_non_patch_text():
    assert intent.parse_patch_instructions("ls -la\n") == []
    assert intent.parse_patch_instructions("") == []
    assert intent.parse_patch_instructions(None) == []


def test_has_patch_marker_recognizes_both_forms():
    assert intent.has_patch_marker("*** Begin Patch\n") is True
    assert intent.has_patch_marker("*** Update File: a.py\n") is True
    assert intent.has_patch_marker("ls -la\n") is False
    assert intent.has_patch_marker(None) is False


# --------------------------------------------------------------------------------------
# 会话侧抽取：Claude / Codex 的正例与反例
# --------------------------------------------------------------------------------------


def _tokens(**overrides):
    base = {
        "session": "claude:s.jsonl",
        "session_id": "sess-radar-9000",
        "source": "claude",
        "file": "s.jsonl",
        "seq": 2,
        "ts": "2026-01-01T00:01:00Z",
        "cwd": "C:/repo",
        "workspace": "C:/repo",
        "in_worktree": True,
    }
    base.update(overrides)
    return base


def _claude_record(name, tool_input):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": tool_input}]},
    }


def test_claude_edit_and_write_are_extracted():
    edit = intent.claude_write_ops(
        _claude_record("Edit", {"file_path": "C:/repo/src/a.py", "old_string": "x", "new_string": "y"}),
        _tokens(),
    )
    assert len(edit) == 1 and edit[0].kind == intent.OP_EDIT
    assert edit[0].rel_path() == "src/a.py"

    write = intent.claude_write_ops(
        _claude_record("Write", {"file_path": "C:/repo/src/a.py", "content": "x\ny\n"}), _tokens()
    )
    assert len(write) == 1 and write[0].kind == intent.OP_WRITE
    assert write[0].content_lines == ("x", "y")


def test_claude_non_write_tools_produce_nothing():
    """反例：`Read` / `Bash` 不是写操作 → 一条都不产出（不猜、不计 unknown）。"""
    for name in ("Read", "Bash", "Grep", "Glob", "TodoWrite"):
        ops = intent.claude_write_ops(_claude_record(name, {"file_path": "C:/repo/src/a.py"}), _tokens())
        assert ops == [], "%r 不该被认成写操作" % name


def test_claude_missing_file_path_is_unknown_reason():
    ops = intent.claude_write_ops(
        _claude_record("Edit", {"old_string": "x", "new_string": "y"}), _tokens()
    )
    assert len(ops) == 1
    assert ops[0].reason == intent.REASON_MISSING_FILE_PATH


def test_claude_multi_edit_is_a_known_placeholder_not_a_guess():
    """本机 0 次出现 → known-name 占位、落 unknown 原因码，**不解析 edits[]**（连字段形态都不编）。"""
    ops = intent.claude_write_ops(
        _claude_record("MultiEdit", {"file_path": "C:/repo/src/a.py", "edits": [{"old_string": "x"}]}),
        _tokens(),
    )
    assert len(ops) == 1
    assert ops[0].kind == intent.OP_OPAQUE
    assert ops[0].reason == intent.REASON_MULTI_EDIT


def _codex_record(name, text, payload_type="custom_tool_call"):
    if payload_type == "custom_tool_call":
        payload = {"type": "custom_tool_call", "name": name, "input": text}
    else:
        payload = {"type": "function_call", "name": name, "arguments": json.dumps({"input": text})}
    return {"type": "response_item", "payload": payload}


def test_codex_apply_patch_custom_tool_call_is_extracted():
    ops = intent.codex_write_ops(
        _codex_record("apply_patch", "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** End Patch\n"),
        _tokens(source="codex", session="codex:s.jsonl"),
    )
    assert len(ops) == 1 and ops[0].kind == intent.OP_PATCH_UPDATE
    assert ops[0].rel_path() == "src/a.py"
    assert ops[0].old_lines == ("x",) and ops[0].new_lines == ("y",)


def test_codex_exec_variant_is_recognized_when_it_carries_a_patch():
    """R2 的第二形态：patch 经 `exec` 下发（标记同形）→ 必须认。"""
    text = "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** End Patch\nEOF\n"
    ops = intent.codex_write_ops(_codex_record("exec", text), _tokens(source="codex"))
    assert len(ops) == 1 and ops[0].kind == intent.OP_PATCH_UPDATE


def test_codex_exec_without_patch_marker_is_not_a_write_op():
    """反例：普通 shell 命令不是写操作（把它记成 unknown 会污染计数）。"""
    assert intent.codex_write_ops(_codex_record("exec", "ls -la\n"), _tokens(source="codex")) == []
    assert intent.codex_write_ops(_codex_record("exec", "git status\n"), _tokens(source="codex")) == []


def test_codex_unknown_tool_without_patch_marker_is_ignored():
    assert intent.codex_write_ops(_codex_record("shell", "echo hi\n"), _tokens(source="codex")) == []


def test_codex_patch_without_file_instruction_is_unknown_not_dropped():
    """是 patch 工具但没有任何指令行 → unknown + 计注记（**不静默丢弃**）。"""
    ops = intent.codex_write_ops(_codex_record("apply_patch", "*** Begin Patch\n*** End Patch\n"), _tokens())
    assert len(ops) == 1
    assert ops[0].reason == intent.REASON_PATCH_WITHOUT_INSTRUCTION


def test_codex_function_call_arguments_json_is_parsed():
    ops = intent.codex_write_ops(
        _codex_record(
            "apply_patch",
            "*** Begin Patch\n*** Add File: src/n.py\n+def f():\n+    return 1\n*** End Patch\n",
            payload_type="function_call",
        ),
        _tokens(source="codex"),
    )
    assert len(ops) == 1 and ops[0].kind == intent.OP_PATCH_ADD
    assert ops[0].content_lines == ("def f():", "    return 1")


def test_codex_non_response_item_rows_are_ignored():
    record = {"type": "event_msg", "payload": {"type": "token_count"}}
    assert intent.codex_write_ops(record, _tokens(source="codex")) == []


# --------------------------------------------------------------------------------------
# 定位：三分法的每条分支（用假的 HEAD 基线，不碰 git）
# --------------------------------------------------------------------------------------


class _FakeOp(object):
    """最小的写操作替身（`locate_op` 只读这些字段）。"""

    def __init__(self, kind, rel="src/a.py", old=(), new=(), replace_all=False, content=(),
                 reason=None, in_worktree=True):
        self.kind = kind
        self.path_raw = "C:/repo/" + rel if rel else None
        self.cwd = "C:/repo"
        self.workspace = "C:/repo"
        self.in_worktree = in_worktree
        self.old_lines = tuple(old)
        self.new_lines = tuple(new)
        self.replace_all = replace_all
        self.content_lines = tuple(content)
        self.reason = reason

    def rel_path(self):
        return intent.to_workspace_relative(self.path_raw, self.cwd)[0] if self.path_raw else None


@pytest.fixture
def fake_head(monkeypatch):
    """把 `read_head_lines` 换成固定基线，使这些用例不需要 git。"""
    state = {"lines": ["def f():", "    a = 1", "    b = 2"], "reason": None}

    def _fake(workspace, path, timeout):
        return state["lines"], state["reason"]

    monkeypatch.setattr(intent, "read_head_lines", _fake)
    return state


def test_locate_unique_anchor_is_exact(fake_head):
    op = _FakeOp(intent.OP_EDIT, old=("    b = 2",), new=("    b = 3",))
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_EXACT
    assert located.ranges == [(3, 3)]
    assert located.reasons == []


def test_locate_ambiguous_anchor_is_coarse_and_names_the_count(fake_head):
    fake_head["lines"] = ["    a = 1", "", "    a = 1"]
    op = _FakeOp(intent.OP_EDIT, old=("    a = 1",), new=("    a = 2",))
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE
    assert located.ranges == [], "多处命中不许给区间"
    assert located.reasons == ["anchor_ambiguous#2"]


def test_locate_missing_anchor_is_coarse(fake_head):
    op = _FakeOp(intent.OP_EDIT, old=("    z = 9",), new=("    z = 10",))
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE
    assert located.reasons == ["anchor_not_found"]


def test_locate_replace_all_never_claims_a_range(fake_head):
    """即使锚点唯一，`replace_all` 也不给区间（它的语义是"全部命中"）。"""
    op = _FakeOp(intent.OP_EDIT, old=("    b = 2",), new=("    b = 3",), replace_all=True)
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE
    assert located.ranges == []
    assert located.reasons == ["replace_all"]


def test_locate_write_compares_against_head(fake_head):
    op = _FakeOp(intent.OP_WRITE, content=("def f():", "    a = 100", "    b = 2"))
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_EXACT
    assert located.ranges == [(2, 2)], "整文件 Write 只改了第 2 行"


def test_locate_write_identical_to_base_is_coarse(fake_head):
    op = _FakeOp(intent.OP_WRITE, content=("def f():", "    a = 1", "    b = 2"))
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE
    assert located.reasons == ["write_identical_to_base"]


def test_locate_new_file_write_is_the_whole_file(fake_head):
    """基线取不到（新文件）→ 整文件都是新增（可复算，不是"看起来精确"）。"""
    fake_head["lines"] = None
    fake_head["reason"] = intent.REASON_BASELINE_UNAVAILABLE
    op = _FakeOp(intent.OP_PATCH_ADD, content=("def f():", "    return 1"))
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_EXACT
    assert located.ranges == [(1, 2)]


def test_locate_outside_worktree_is_coarse_and_reads_nothing(monkeypatch):
    """不在任何 worktree → `coarse` + `not_in_worktree`，且**根本不去读 HEAD**。"""
    called = []

    def _boom(*args, **kwargs):
        called.append(args)
        raise AssertionError("不在 worktree 内时不得读盘")

    monkeypatch.setattr(intent, "read_head_lines", _boom)
    op = _FakeOp(intent.OP_EDIT, old=("    b = 2",), new=("    b = 3",), in_worktree=False)
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE
    assert located.reasons == ["not_in_worktree"]
    assert called == []


def test_locate_delete_is_coarse_without_range(fake_head):
    op = _FakeOp(intent.OP_PATCH_DELETE)
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE
    assert located.ranges == []
    assert located.reasons == ["deleted_path"]


def test_locate_multi_edit_reason_maps_to_unknown(fake_head):
    op = _FakeOp(intent.OP_OPAQUE, rel=None, reason=intent.REASON_MULTI_EDIT)
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_UNKNOWN


def test_locate_patch_without_instruction_maps_to_coarse(fake_head):
    """文件是知道的（只是 patch 里没有指令行）→ `coarse`，不是 `unknown`。"""
    op = _FakeOp(intent.OP_OPAQUE, rel="src/a.py", reason=intent.REASON_PATCH_WITHOUT_INSTRUCTION)
    located = intent.locate_op(op, "C:/repo", True, None)
    assert located.precision == intent.PRECISION_COARSE


# --------------------------------------------------------------------------------------
# 磁盘侧解析（纯文本 → 区间），不调 git
# --------------------------------------------------------------------------------------


def test_parse_hunks_uses_the_new_file_coordinates():
    diff = (
        "diff --git a/src/a.py b/src/a.py\n"
        "index 111..222 100644\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -9 +9 @@ def f():\n"
        "-    j = 8\n"
        "+    j = 609\n"
    )
    ranges, reasons = intent.parse_hunks(diff)
    assert ranges == {"src/a.py": [(9, 9)]}, "hunk 头里的 `+9` 才是新文件坐标"
    assert reasons == {}


def test_parse_hunks_handles_counts_and_multiple_hunks():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,3 @@\n"
        "@@ -10,0 +12,2 @@\n"
    )
    ranges, _reasons = intent.parse_hunks(diff)
    assert ranges == {"a.py": [(1, 3), (12, 13)]}


def test_parse_hunks_marks_pure_deletion_as_no_range():
    """`+c,0`（纯删除）在新文件里没有坐标 → 落原因码，不编区间。"""
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -3,2 +3,0 @@\n"
    )
    ranges, reasons = intent.parse_hunks(diff)
    assert ranges == {}
    assert reasons == {"a.py": intent.REASON_DELETED_PATH}


def test_parse_hunks_marks_binary_diff():
    diff = (
        "diff --git a/a.bin b/a.bin\n"
        "Binary files a/a.bin and b/a.bin differ\n"
    )
    ranges, reasons = intent.parse_hunks(diff)
    assert ranges == {}
    assert reasons == {"a.bin": intent.REASON_BINARY_DIFF}


def test_decode_status_records_uses_the_null_delimited_protocol():
    stdout = " M src/alpha.py\0?? docs/new.md\0R  src/old.py\0src/older.py\0"
    parsed = intent.decode_status_records(stdout)
    assert parsed == {"src/alpha.py": " M", "docs/new.md": "??", "src/old.py": "R "}, (
        "rename 形态后面那条原始路径必须被协议消费掉（不能当成一个新文件）"
    )


def test_decode_status_records_keeps_non_ascii_paths_verbatim():
    """`-z` 的意义：中文路径原样出现（行模式会显示成八进制转义，本机实测踩过）。"""
    parsed = intent.decode_status_records(" M src/中文.py\0")
    assert list(parsed) == ["src/中文.py"]


# --------------------------------------------------------------------------------------
# 计数口径（K12）：条目数 vs 写操作条数
# --------------------------------------------------------------------------------------


def test_precision_order_is_strongest_to_weakest():
    assert intent.PRECISION_ORDER == ("exact", "coarse", "unknown")
    assert intent._worst_precision(["exact", "coarse"]) == "coarse"
    assert intent._worst_precision(["exact", "unknown"]) == "unknown"
    assert intent._worst_precision([]) == "exact", "没有反面证据就不降级"
