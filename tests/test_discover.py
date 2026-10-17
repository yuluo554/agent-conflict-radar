"""`discover.py` 的字段级对账（M1 DoD：归集正确 / 未知格式不静默 / 源缺失不伪造 / 确定性）。

本文件的纪律来源：

* `plan/04` M1 的"输出字段口径"表（`session_key` / `derived_from` / `is_subagent` / `seq` / `in_worktree`）；
* `data/README.md` §6.4 的两侧实测形态（**Claude 首行不是消息行**、Codex 子会话没有 `session_id`）；
* `plan/05` §七"凡自动发现本机数据的参数，测试与演示一律显式传临时目录"——
  本文件**每一个**用例都显式传临时根：缺省值会落到真实用户日志，那既是隐私问题，也让断言不稳定。
"""

import json
import os
import subprocess

import pytest

from agent_conflict_radar import config as config_module
from agent_conflict_radar import discover
from agent_conflict_radar.errors import EnvironmentError_
from agent_conflict_radar.serialize import dumps_json

# --------------------------------------------------------------------------------------
# 夹具：临时 git 仓库 + 双 root（全部显式传，绝不用缺省探测）
# --------------------------------------------------------------------------------------


@pytest.fixture
def cfg(config_path):
    return config_module.load(str(config_path))


@pytest.fixture
def git_repo(tmp_path):
    """一个临时 git 仓库。**缺 git 就显式跳过并说明**（不静默变成"通过"）。"""
    repo = tmp_path / "work" / "demo-radar-alpha"
    repo.mkdir(parents=True)
    if subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0:
        pytest.skip("找不到 git：本组用例要真造仓库来验 worktree 枚举（缺依赖不是通过）")
    subprocess.run(["git", "init", "--quiet"], cwd=str(repo), check=True)
    return repo


@pytest.fixture
def roots(tmp_path):
    claude = tmp_path / "conf" / "claude"
    codex = tmp_path / "conf" / "codex"
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    return {discover.versions.SOURCE_CLAUDE: claude, discover.versions.SOURCE_CODEX: codex}


def _claude_lines(session_id, cwd, branch="feat/agent-a", sidechain=False, *, first_line="last-prompt",
                  drop_keys=(), timestamp="2026-01-01T00:01:00Z"):
    head = {"type": first_line, "uuid": "%s-lp" % session_id, "sessionId": session_id, "cwd": cwd,
            "gitBranch": branch, "isSidechain": sidechain, "timestamp": "2026-01-01T00:00:00Z"}
    message = {"type": "assistant", "uuid": "%s-m", "sessionId": session_id, "cwd": cwd,
               "gitBranch": branch, "isSidechain": sidechain, "timestamp": timestamp,
               "message": {"role": "assistant", "content": []}}
    for key in drop_keys:
        message.pop(key, None)
    return [head, message]


def _codex_lines(session_id, cwd, *, parent=None, timestamp="2026-01-01T00:01:00Z"):
    payload = {"id": session_id, "timestamp": "2026-01-01T00:00:00Z", "cwd": cwd}
    if parent is None:
        payload["session_id"] = session_id
    else:
        payload["parent_thread_id"] = parent
    return [
        {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z", "payload": payload},
        {"type": "event_msg", "timestamp": timestamp, "payload": {"type": "token_count"}},
    ]


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def _write_jsonl(write_lf, path, records):
    return write_lf(path, "".join(json.dumps(record, sort_keys=True) + "\n" for record in records))


# --------------------------------------------------------------------------------------
# worktree 逐字段解析
# --------------------------------------------------------------------------------------


def test_worktree_porcelain_parses_paths_with_spaces_detached_and_bare():
    """`--porcelain` 必须**按行**解析：路径可含空格、可有 detached / bare 形态（`data/README` §2.4）。"""
    text = (
        "worktree C:/repo with space/demo-radar-alpha\n"
        "HEAD 1111111111111111111111111111111111111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree C:/repo/detached one\n"
        "HEAD 2222222222222222222222222222222222222222\n"
        "detached\n"
        "\n"
        "worktree C:/repo/bare.git\n"
        "HEAD 3333333333333333333333333333333333333333\n"
        "bare\n"
    )
    parsed = discover.parse_worktree_porcelain(text)
    assert [item.path for item in parsed] == [
        "C:/repo with space/demo-radar-alpha",
        "C:/repo/detached one",
        "C:/repo/bare.git",
    ], "路径被空格切分了（按行解析的判据就在这条用例上）"
    assert parsed[0].branch == "main" and parsed[0].is_main is True
    assert parsed[1].branch == "(detached)" and parsed[1].is_main is False
    assert parsed[2].branch == "" and parsed[2].is_main is False, "初始无 branch 字段的形态不得被误判成分支名"


# --------------------------------------------------------------------------------------
# 会话形态：seq 必须是源行号 / 未知格式不静默
# --------------------------------------------------------------------------------------


def test_claude_first_line_is_not_message_line_and_seq_is_source_line_number(write_lf, roots):
    """实测形态：Claude 首行多为 `last-prompt`。`seq` 必须是**消息行的源行号**（=2），不是 1。"""
    path = roots[discover.versions.SOURCE_CLAUDE] / "sess-radar-0001.jsonl"
    _write_jsonl(write_lf, path, _claude_lines("sess-radar-0001", "C:/w/demo-radar-alpha"))
    sessions, undetermined = discover.scan_sessions(
        [(discover.versions.SOURCE_CLAUDE, roots[discover.versions.SOURCE_CLAUDE])], 100000
    )
    assert undetermined == []
    assert len(sessions) == 1
    assert sessions[0].seq == 2, "seq 取成了首行或数组下标——它必须是承载元信息那一行的源文件行号"
    assert sessions[0].git_branch == "feat/agent-a"
    assert sessions[0].session_key == "claude:sess-radar-0001.jsonl"


def test_unknown_shape_is_undetermined_with_missing_keys_and_named_file(write_lf, roots):
    """缺键日志 → `unsupported_format` + 列出缺失键 + 点名文件；**且不产出空表让人以为没事**。"""
    path = roots[discover.versions.SOURCE_CLAUDE] / "sess-radar-0009.jsonl"
    _write_jsonl(write_lf, path, _claude_lines("sess-radar-0009", "C:/w/x", drop_keys=("cwd", "sessionId")))
    sessions, undetermined = discover.scan_sessions(
        [(discover.versions.SOURCE_CLAUDE, roots[discover.versions.SOURCE_CLAUDE])], 100000
    )
    assert sessions == [], "形状不符的文件不得被塞进 sessions（那会让下游以为它是有效会话）"
    assert len(undetermined) == 1
    item = undetermined[0]
    assert item.code == discover.CODE_UNSUPPORTED_FORMAT
    assert item.file == "sess-radar-0009.jsonl", "必须点名文件"
    assert set(item.missing_keys) == {"cwd", "sessionId"}, "必须列出缺失键"
    assert "sess-radar-0009" not in json.dumps(undetermined[0].as_dict()).replace(item.file, "")


def test_file_without_any_message_line_is_reported_not_swallowed(write_lf, roots):
    """只有元信息行、没有任何消息行 → `no_message_line`（实测存在这类文件，不能静默丢弃）。"""
    path = roots[discover.versions.SOURCE_CLAUDE] / "sess-radar-0010.jsonl"
    _write_jsonl(write_lf, path, _claude_lines("sess-radar-0010", "C:/w/x", first_line="started")[:1])
    sessions, undetermined = discover.scan_sessions(
        [(discover.versions.SOURCE_CLAUDE, roots[discover.versions.SOURCE_CLAUDE])], 100000
    )
    assert sessions == []
    assert [item.code for item in undetermined] == [discover.CODE_NO_MESSAGE_LINE]
    assert undetermined[0].file == "sess-radar-0010.jsonl"


def test_codex_child_without_session_id_falls_back_to_id_and_marks_subagent(write_lf, roots):
    """实测：Codex 子会话没有 `session_id`（只有主会话有）→ 标识回落 `id`，`is_subagent` 由 parent 认定。"""
    root = roots[discover.versions.SOURCE_CODEX]
    _write_jsonl(write_lf, root / "sess-radar-0007.jsonl", _codex_lines("sess-radar-0007", "C:/w/x"))
    _write_jsonl(write_lf, root / "sess-radar-0008.jsonl", _codex_lines("sess-radar-0008", "C:/w/x", parent="sess-radar-0007"))
    sessions, undetermined = discover.scan_sessions([(discover.versions.SOURCE_CODEX, root)], 100000)
    assert undetermined == []
    by_id = {item.session_id: item for item in sessions}
    assert set(by_id) == {"sess-radar-0007", "sess-radar-0008"}
    assert by_id["sess-radar-0008"].is_subagent is True
    assert by_id["sess-radar-0008"].seq == 1, "Codex 的元信息在首行 `session_meta`"
    discover.link_derivations(sessions, [])
    assert by_id["sess-radar-0008"].derived_from == "codex:sess-radar-0007.jsonl"
    assert by_id["sess-radar-0007"].derived_from is None


def test_parent_outside_scan_scope_keeps_derived_from_null_and_is_reported(write_lf, roots):
    """父会话不在扫描范围内 → `parent_not_found`，且 `derived_from` **保持 null**（不猜、不指向自己）。"""
    root = roots[discover.versions.SOURCE_CODEX]
    _write_jsonl(write_lf, root / "sess-radar-0020.jsonl", _codex_lines("sess-radar-0020", "C:/w/x", parent="sess-radar-9999"))
    sessions, undetermined = discover.scan_sessions([(discover.versions.SOURCE_CODEX, root)], 100000)
    discover.link_derivations(sessions, undetermined)
    assert sessions[0].derived_from is None
    codes = [item.code for item in undetermined]
    assert discover.CODE_PARENT_NOT_FOUND in codes
    assert undetermined[0].file == "sess-radar-0020.jsonl"


def test_claude_sidechain_is_linked_by_shared_session_id(write_lf, roots):
    """Claude 派生关系 = 同一 `sessionId` 下 `isSidechain=False` 的那只文件（实测 28/28 满足）。"""
    root = roots[discover.versions.SOURCE_CLAUDE]
    _write_jsonl(write_lf, root / "sess-radar-0001.jsonl", _claude_lines("sess-radar-0001", "C:/w/x"))
    _write_jsonl(
        write_lf, root / "sess-radar-0001-side.jsonl", _claude_lines("sess-radar-0001", "C:/w/x", sidechain=True)
    )
    sessions, undetermined = discover.scan_sessions([(discover.versions.SOURCE_CLAUDE, root)], 100000)
    discover.link_derivations(sessions, undetermined)
    assert undetermined == []
    side = [item for item in sessions if item.is_subagent][0]
    assert side.derived_from == "claude:sess-radar-0001.jsonl"
    assert side.session_key == "claude:sess-radar-0001-side.jsonl", "共享 sessionId 时唯一键必须是文件路径"


def test_overlong_line_becomes_line_too_long_and_is_not_truncated(write_lf, roots):
    """超长行 → `undetermined(line_too_long)`，**且不静默截断**（截断会产出半条记录）。"""
    path = roots[discover.versions.SOURCE_CLAUDE] / "sess-radar-0002.jsonl"
    records = _claude_lines("sess-radar-0002", "C:/w/x")
    records[1]["message"]["content"] = [{"type": "tool_use", "input": {"blob": "x" * 4000}}]
    _write_jsonl(write_lf, path, records)
    sessions, undetermined = discover.scan_sessions(
        [(discover.versions.SOURCE_CLAUDE, roots[discover.versions.SOURCE_CLAUDE])], 200
    )
    assert sessions == []
    assert [item.code for item in undetermined] == [discover.CODE_LINE_TOO_LONG]
    assert "4000" not in undetermined[0].detail
    assert "max_line_bytes" in undetermined[0].detail, "报错要指向可调的那个配置键，否则用户不知道怎么办"


# --------------------------------------------------------------------------------------
# 源缺失不伪造
# --------------------------------------------------------------------------------------


def test_missing_explicit_root_raises_environment_error(cfg, tmp_path, git_repo):
    """显式传的 root 不存在 → exit 3（不是 exit 0 空结果）。"""
    with pytest.raises(EnvironmentError_) as excinfo:
        discover.build_workspace_table(
            str(git_repo), str(tmp_path / "nope"), str(tmp_path / "nope2"), cfg, now="2026-01-01T00:10:00Z"
        )
    assert "不会伪造空结果" in str(excinfo.value)


def test_non_git_repo_raises_environment_error(cfg, tmp_path):
    """`--repo` 不在 git 仓库内 → exit 3：worktree 枚举与试合并都依赖 git，退化成空表会被读成"无冲突"。"""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(EnvironmentError_):
        discover.build_workspace_table(str(plain), None, None, cfg, now="2026-01-01T00:10:00Z")


# --------------------------------------------------------------------------------------
# 活跃 cell 匹配与确定性
# --------------------------------------------------------------------------------------


def test_cwd_outside_worktree_is_kept_and_flagged(cfg, git_repo, roots, write_lf):
    """`cwd` 匹配不到 worktree → `in_worktree=false` 且**保留原始 cwd**（不丢弃、不假装归属）。"""
    outside = "C:/somewhere/else/demo-radar-beta"
    _write_jsonl(write_lf, roots[discover.versions.SOURCE_CLAUDE] / "s.jsonl", _claude_lines("sess-radar-0030", outside))
    table = discover.build_workspace_table(
        str(git_repo),
        str(roots[discover.versions.SOURCE_CLAUDE]),
        str(roots[discover.versions.SOURCE_CODEX]),
        cfg,
        now="2026-01-01T00:10:00Z",
    )
    assert table.as_dict()["counts"]["cells_outside_worktree"] == 1
    cell = table.active_cells[0]
    assert cell.in_worktree is False
    assert cell.workspace == outside, "匹配不上时必须保留原始 cwd（否则用户看不到它属于哪）"


def test_cwd_inside_worktree_matches_and_sets_flag(cfg, git_repo, roots, write_lf):
    """`cwd` 落在 worktree 内（含子目录）→ `in_worktree=true`（最长前缀匹配）。"""
    inside = str(git_repo).replace("\\", "/") + "/src"
    _write_jsonl(write_lf, roots[discover.versions.SOURCE_CLAUDE] / "s.jsonl", _claude_lines("sess-radar-0031", inside))
    table = discover.build_workspace_table(
        str(git_repo),
        str(roots[discover.versions.SOURCE_CLAUDE]),
        str(roots[discover.versions.SOURCE_CODEX]),
        cfg,
        now="2026-01-01T00:10:00Z",
    )
    assert table.active_cells[0].in_worktree is True
    # git 报的 worktree 路径是正斜杠形态，`str(git_repo)` 是平台原生形态——比对一律先归一。
    assert _norm(table.active_cells[0].workspace) == _norm(str(git_repo)), (
        "工作区应归到 worktree 根（git 报的那个路径），而不是 cwd 自己"
    )


def test_scan_is_byte_identical_across_two_runs(cfg, git_repo, roots, write_lf):
    """同输入双跑逐字节一致（显式 `--now`，全程不读时钟）。"""
    _write_jsonl(write_lf, roots[discover.versions.SOURCE_CLAUDE] / "a.jsonl", _claude_lines("sess-radar-0040", "C:/w/x"))
    _write_jsonl(write_lf, roots[discover.versions.SOURCE_CODEX] / "b.jsonl", _codex_lines("sess-radar-0041", "C:/w/x"))
    args = (
        str(git_repo),
        str(roots[discover.versions.SOURCE_CLAUDE]),
        str(roots[discover.versions.SOURCE_CODEX]),
        cfg,
    )
    first = dumps_json(discover.build_workspace_table(*args, now="2026-01-01T00:10:00Z").as_dict())
    second = dumps_json(discover.build_workspace_table(*args, now="2026-01-01T00:10:00Z").as_dict())
    assert first == second
    assert json.loads(first)["counts"]["sessions"] == 2


def test_default_reference_time_is_a_function_of_the_input(cfg, git_repo, roots, write_lf):
    """不传 `--now` 时参考时刻取"观测到的最大时间戳"——**输入的函数**，故双跑仍一致。"""
    _write_jsonl(write_lf, roots[discover.versions.SOURCE_CLAUDE] / "a.jsonl", _claude_lines("sess-radar-0050", "C:/w/x"))
    args = (str(git_repo), str(roots[discover.versions.SOURCE_CLAUDE]), str(roots[discover.versions.SOURCE_CODEX]), cfg)
    first = discover.build_workspace_table(*args)
    second = discover.build_workspace_table(*args)
    assert first.reference_time == second.reference_time == "2026-01-01T00:01:00Z"
    assert any("最大会话时间戳" in note for note in first.notes)


def test_timestamp_parser_does_not_guess_on_garbage():
    assert discover.parse_timestamp("2026-01-01T00:00:00Z") is not None
    assert discover.parse_timestamp("not-a-date") is None
    assert discover.parse_timestamp(None) is None
    assert discover.parse_timestamp("") is None


def test_match_worktree_longest_prefix_wins():
    worktrees = [
        discover.Worktree(path="C:/w/demo-radar-alpha", head="a", branch="main", is_main=True),
        discover.Worktree(path="C:/w/demo-radar-alpha/nested", head="b", branch="feat/agent-b", is_main=False),
    ]
    matched, inside = discover.match_worktree("C:/w/demo-radar-alpha/nested/src", worktrees)
    assert (matched, inside) == ("C:/w/demo-radar-alpha/nested", True)
    matched, inside = discover.match_worktree("C:/w/demo-radar-alpha", worktrees)
    assert (matched, inside) == ("C:/w/demo-radar-alpha", True)
    matched, inside = discover.match_worktree("C:/w/other", worktrees)
    assert (matched, inside) == ("C:/w/other", False)
