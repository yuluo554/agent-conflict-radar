"""`detect.py` / `gitio.merge_tree` 的纯函数级与合成用例（M3 DoD：三态 / 只读白名单 / 降级）。

分工：

* `tests/test_detect.py`：端到端跑冻结矩阵（七条场景）；
* 本文件：**不依赖冻结矩阵**的判据——AST 符号区间、相邻容差边界、`merge-tree` 输出解析，
  以及三态（`degraded` / `approximate` / `unsupported_format`）各自**真的被触发**的合成用例。
  这些形态在冻结矩阵里没有合适的落点（矩阵七条场景都是 Python 文件 + 两条正常分支），
  硬塞进冻结树就得改真值与台账；**这里手造最小夹具，不动冻结产物**。

纪律：所有用例都显式传两侧会话根（`plan/05` §七），时间戳从固定基准 `2026-01-01T00:00:00Z` 起。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import config as config_module
from agent_conflict_radar import detect, gitio
from agent_conflict_radar.bench import gen
from agent_conflict_radar.exit_codes import EXIT_CONFLICTS_FOUND, EXIT_OK

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
NOW = "2026-01-01T00:10:00Z"


def _git_available():
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="合成 git 仓库需要 git（缺依赖不是通过）")


# --------------------------------------------------------------------------------------
# 最小夹具：真 git 仓库 + 真 Claude 会话日志（**不碰冻结矩阵**）
# --------------------------------------------------------------------------------------

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "radar-user",
    "GIT_AUTHOR_EMAIL": "radar-user@example.invalid",
    "GIT_COMMITTER_NAME": "radar-user",
    "GIT_COMMITTER_EMAIL": "radar-user@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}

_PY_ALPHA = """def f():
    a = 1
    b = 2
    c = 3


def g():
    m = 4
    n = 5
"""

_NOTES = """# notes
line one
line two
"""


def _write_text(path, text):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return target


def _git(args, cwd, extra_env=None):
    env = dict(os.environ)
    env.update(_GIT_ENV)
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        ["git"] + list(args), cwd=str(cwd), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert completed.returncode == 0, "git %s 失败：%s" % (args, completed.stdout.decode("utf-8", "replace"))
    return completed.stdout.decode("utf-8", "replace")


def _make_repo(root, files):
    """建一个只有基线提交的合成仓库（分支名固定 `main`）；返回仓库路径。"""
    repo = Path(root)
    repo.mkdir(parents=True, exist_ok=True)
    for rel, text in sorted(files.items()):
        _write_text(repo / rel, text)
    _git(["init", "--quiet", "-b", "main"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "--quiet", "--no-verify", "-m", "base"], repo)
    return repo


def _commit_on_branch(repo, branch, files):
    """从当前分支切出新分支、改写文件、提交、切回。"""
    base = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    _git(["checkout", "--quiet", "-b", branch, base], repo)
    for rel, text in sorted(files.items()):
        _write_text(Path(repo) / rel, text)
    _git(["add", "-A"], repo)
    _git(["commit", "--quiet", "--no-verify", "-m", "feat"], repo)
    _git(["checkout", "--quiet", base], repo)


def _commit(repo, files, message="feat"):
    for rel, text in sorted(files.items()):
        _write_text(Path(repo) / rel, text)
    _git(["add", "-A"], repo)
    _git(["commit", "--quiet", "--no-verify", "-m", message], repo)


def _stamp(minute):
    hours, minutes = divmod(minute, 60)
    return "2026-01-01T%02d:%02d:00Z" % (hours, minutes)


def _claude_session(path, session_id, cwd, branch, edits, start_minute=0, sidechain=False, calls=()):
    """写一份仿实测形态的 Claude 会话：**首行不是消息行**，然后逐条工具调用，末尾一条收尾行。

    `edits` 生成 `Edit` 调用；`calls` 是额外的 `(工具名, input)`——用它造"有消息行但没有写操作"
    的会话（例：父会话只 `Read`），这对 `derived_from` 的认定是必需的。
    """
    common = {
        "sessionId": session_id,
        "cwd": cwd,
        "gitBranch": branch,
        "isSidechain": sidechain,
    }
    lines = []
    head = dict(common)
    head.update({"type": "last-prompt", "uuid": session_id + "-lp", "timestamp": _stamp(start_minute)})
    lines.append(head)
    minute = start_minute + 1
    plan = []
    for index, (rel, old, new) in enumerate(edits):
        plan.append(
            (
                "Edit",
                {
                    "file_path": "%s/%s" % (cwd, rel),
                    "old_string": old,
                    "new_string": new,
                    "replace_all": False,
                },
            )
        )
    plan.extend(calls)
    for index, (name, tool_input) in enumerate(plan):
        record = dict(common)
        record.update(
            {
                "type": "assistant",
                "uuid": "%s-msg-%d" % (session_id, index),
                "timestamp": _stamp(minute),
                "message": {
                    "id": "msg-%s-%d" % (session_id, index),
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu-%s-%d" % (session_id, index),
                            "name": name,
                            "input": tool_input,
                        }
                    ],
                },
            }
        )
        lines.append(record)
        minute += 1
    tail = dict(common)
    tail.update({"type": "queue-operation", "uuid": session_id + "-qo", "timestamp": _stamp(start_minute + 5)})
    lines.append(tail)
    _write_text(
        path,
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in lines),
    )
    return path


def _roots(path):
    """工作区/会话根：Codex 侧一律显式传一个空目录（钉死探测面）。"""
    claude = Path(path)
    codex = claude.parent / "empty-codex"
    codex.mkdir(parents=True, exist_ok=True)
    return str(claude), str(codex)


def _load_config():
    return config_module.load(str(REPO_ROOT / "config" / "radar.toml"))


def _config_without_merge_tree(tmp_path):
    """复制真配置并把 `git.merge_tree_enabled` 改成 false（区块级在配置里关闭）。"""
    text = (REPO_ROOT / "config" / "radar.toml").read_text(encoding="utf-8")
    mutated = text.replace("merge_tree_enabled = true", "merge_tree_enabled = false")
    assert mutated != text
    return config_module.load(str(_write_text(tmp_path / "radar-no-merge-tree.toml", mutated)))


def _conflict_scene(tmp_path, kind="python"):
    """两个会话同改**同一行**（两条分支各提交一次）→ 文件级 + 区块级必命中。

    `kind="non_python"` 换到 `docs/notes.md`（R4：非 Python 不做符号级）。
    """
    repo = _make_repo(tmp_path / "repo", {"src/alpha.py": _PY_ALPHA, "docs/notes.md": _NOTES})
    if kind == "python":
        target, anchor, left, right = "src/alpha.py", "    a = 1", "    a = 11", "    a = 22"
    else:
        target, anchor, left, right = "docs/notes.md", "line one", "line one left", "line one right"
    base_text = (Path(repo) / target).read_text(encoding="utf-8")
    _commit_on_branch(repo, "feat/agent-a", {target: base_text.replace(anchor, left)})
    _commit_on_branch(repo, "feat/agent-b", {target: base_text.replace(anchor, right)})

    claude = tmp_path / "sessions" / "claude"
    root = str(repo).replace(os.sep, "/")
    for index, branch, new in ((1, "feat/agent-a", left), (2, "feat/agent-b", right)):
        _claude_session(
            claude / ("sess-radar-000%d.jsonl" % index),
            "sess-radar-000%d" % index,
            root,
            branch,
            [(target, anchor, new)],
        )
    return repo, claude


# --------------------------------------------------------------------------------------
# 纯函数：AST 符号区间与相邻容差
# --------------------------------------------------------------------------------------


def test_symbol_spans_use_qualified_names_for_nested_definitions():
    lines = [
        "class A:",
        "    def f(self):",
        "        return 1",
        "",
        "    def g(self):",
        "        return 2",
        "",
        "",
        "def top():",
        "    return 3",
    ]
    assert detect.symbol_spans(lines) == [
        ("A", 1, 6),
        ("A.f", 2, 3),
        ("A.g", 5, 6),
        ("top", 9, 10),
    ]


def test_pair_symbol_hit_distinguishes_same_adjacent_and_far():
    spans = [("f", 1, 10), ("g", 14, 19)]
    assert detect.pair_symbol_hit(spans, (2, 2), (9, 9), 3) == ("same", ("f",))
    # 间距恰好 == 容差 → 命中（`<=` 语义，6a）
    assert detect.pair_symbol_hit(spans, (10, 10), (14, 14), 3) == ("adjacent", ("f", "g"))
    # 间距 == 容差 + 1 → 不命中（6b）
    assert detect.pair_symbol_hit(spans, (10, 10), (15, 15), 3) == ("", ())
    # 不同且不相邻
    assert detect.pair_symbol_hit(spans, (2, 2), (19, 19), 3) == ("", ())


def test_pair_symbol_hit_reports_only_the_innermost_of_a_nested_hit():
    """`A` 与 `A.f` 同时命中时只报 `A.f`——报两个会让人以为动了两个符号。"""
    spans = [("A", 1, 6), ("A.f", 2, 3)]
    assert detect.pair_symbol_hit(spans, (2, 2), (2, 2), 0) == ("same", ("A.f",))


def test_pair_symbol_hit_needs_both_sides_inside_a_symbol_for_adjacency():
    """一侧落不进任何符号（例如改了顶层语句）时**不升格**：宁可不报，也不编一个符号。"""
    spans = [("f", 3, 6)]
    assert detect.pair_symbol_hit(spans, (1, 1), (3, 3), 10) == ("", ())


def test_range_gap_is_the_number_of_lines_between():
    assert detect.range_gap((2, 2), (19, 19)) == 16
    assert detect.range_gap((10, 10), (14, 14)) == 3
    assert detect.range_gap((10, 10), (15, 15)) == 4
    assert detect.range_gap((1, 5), (3, 8)) < 0, "重叠区间的间距为负"


def test_symbols_touching_counts_partial_overlap():
    spans = [("f", 1, 10), ("g", 14, 19)]
    assert detect.symbols_touching(spans, (10, 14)) == ["f", "g"], "部分重叠也算动了这个符号"
    assert detect.symbols_touching(spans, (11, 13)) == [], "落在两个符号之间的空行：不算动符号"


def test_severity_key_follows_the_config_weight_order():
    cfg = _load_config()
    assert detect._severity_key(("file", "symbol"), "same", True) == detect.SEVERITY_SAME_SYMBOL
    assert detect._severity_key(("file", "symbol"), "adjacent", True) == detect.SEVERITY_ADJACENT_LINES
    assert detect._severity_key(("file", "block"), "", True) == detect.SEVERITY_SAME_FILE_DIFF_SYMBOL
    assert detect._severity_key(("file",), "", True) == detect.SEVERITY_SAME_FILE_DIFF_SYMBOL
    assert detect._severity_key(("file",), "", False) == detect.SEVERITY_FILE_ONLY
    assert cfg.get("severity", "same_symbol") > cfg.get("severity", "adjacent_lines")


# --------------------------------------------------------------------------------------
# `gitio.merge_tree`：解析 + 只读白名单
# --------------------------------------------------------------------------------------


def test_parse_merge_tree_conflicts_reads_both_output_forms():
    content = (
        "1cff5ba52cd8fd02cc3368e905ec3e52cf5649af\n"
        "100644 8980d713bbbb30a3a52a8ab37b09d0e3e742ae85 1\tsrc/alpha.py\n"
        "100644 f1128fda8a85f417af564b0cd90013fa88aa9fb0 2\tsrc/alpha.py\n"
        "\n"
        "Auto-merging src/alpha.py\n"
        "CONFLICT (content): Merge conflict in src/alpha.py\n"
    )
    assert gitio.parse_merge_tree_conflicts(content) == ["src/alpha.py"]
    # 无冲突：只有一行 tree sha
    assert gitio.parse_merge_tree_conflicts("49a34d13497b5070d57e9908cfdfb95c0291cd29\n") == []
    # modify/delete 形态**没有**三元组行，路径只在 CONFLICT 文案里
    line = "CONFLICT (modify/delete): src/gone.py deleted in HEAD and modified in other\n"
    assert gitio.parse_merge_tree_conflicts(line) == ["src/gone.py"]


def test_merge_tree_real_run_parses_conflicts_and_leaves_the_worktree_alone(tmp_path):
    """真跑一次 exit 1：tree sha 有值、冲突路径解析出来，且**没有**动索引/工作区。"""
    dest = tmp_path / "scene"
    gen.materialize_scenario(gen.scenario_by_id("whole_file_overwrite"), str(dest))
    repo = str(dest / "repo")
    before = subprocess.run(["git", "status", "--porcelain", "-z"], cwd=repo,
                            stdout=subprocess.PIPE).stdout
    result = gitio.merge_tree(repo, "feat/agent-a", "feat/agent-b")
    assert result.returncode == 1
    assert result.tree and len(result.tree) == 40
    assert result.conflict_paths == ("src/alpha.py",)
    after = subprocess.run(["git", "status", "--porcelain", "-z"], cwd=repo,
                           stdout=subprocess.PIPE).stdout
    assert after == before


def test_git_common_dir_is_shared_by_worktrees_and_distinct_across_repositories(tmp_path):
    repo = _make_repo(tmp_path / "repo", {"src/alpha.py": _PY_ALPHA})
    second = tmp_path / "repo-b"
    _git(["worktree", "add", "--quiet", "-b", "feat/agent-b", str(second)], repo)
    other = _make_repo(tmp_path / "other", {"src/beta.py": _PY_ALPHA})
    assert gitio.git_common_dir(str(repo)) == gitio.git_common_dir(str(second))
    assert gitio.git_common_dir(str(repo)) != gitio.git_common_dir(str(other))


def test_mutating_git_subcommands_are_refused_before_a_process_starts():
    from agent_conflict_radar.errors import ReadOnlyViolation

    with pytest.raises(ReadOnlyViolation):
        gitio.run_readonly(["merge-tree", "--write", "a", "b"])
    with pytest.raises(ReadOnlyViolation):
        gitio.run_readonly(["checkout", "main"])
    assert "merge-tree" in gitio.READ_ONLY_SUBCOMMANDS


# --------------------------------------------------------------------------------------
# 三态之一：`approximate`（R4）——非 Python 文件不做符号级
# --------------------------------------------------------------------------------------


def test_non_python_conflict_is_approximate_and_carries_no_symbol_key(tmp_path):
    repo, claude = _conflict_scene(tmp_path, kind="non_python")
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)

    assert len(result.conflicts) == 1
    record = result.conflicts[0]
    assert record.path == "docs/notes.md"
    assert record.levels == ("file", "block"), "非 Python 也要报文件级与区块级"
    assert record.approximate is True
    assert "symbols" not in record.as_dict(), "非 Python 文件不得出现 symbols 键（R4）"
    assert "symbols" not in json.dumps(result.as_dict(), ensure_ascii=False)


def test_python_conflict_still_hits_the_symbol_level(tmp_path):
    """阳性对照：同一套夹具换成 `.py` 就有符号级（否则"没有 symbols"可能只是没跑到）。"""
    repo, claude = _conflict_scene(tmp_path, kind="python")
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)
    assert len(result.conflicts) == 1
    record = result.conflicts[0]
    assert record.levels == ("file", "block", "symbol")
    assert record.symbols == ("f",)
    assert record.approximate is False


def test_unparsable_python_baseline_degrades_to_approximate(tmp_path):
    """基线语法错误 ⇒ 不做符号级 + `symbol_unavailable`；同批其他记录不受影响。"""
    repo = _make_repo(tmp_path / "repo", {"src/broken.py": "def (:\n    pass\n"})
    target = "src/broken.py"
    _commit_on_branch(repo, "feat/agent-a", {target: "def (:  # left\n    pass\n"})
    _commit_on_branch(repo, "feat/agent-b", {target: "def (:  # right\n    pass\n"})
    claude = tmp_path / "sessions" / "claude"
    root = str(repo).replace(os.sep, "/")
    for index, branch, new in ((1, "feat/agent-a", "def (:  # left"), (2, "feat/agent-b", "def (:  # right")):
        _claude_session(claude / ("sess-radar-000%d.jsonl" % index), "sess-radar-000%d" % index,
                        root, branch, [(target, "def (:", new)])
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)
    assert len(result.conflicts) == 1
    record = result.conflicts[0]
    assert record.approximate is True
    assert "symbols" not in record.as_dict()
    assert [item.code for item in result.undetermined] == [detect.CODE_SYMBOL_UNAVAILABLE]


# --------------------------------------------------------------------------------------
# 三态之二：`degraded`——区块级判不出来时**绝不**写成"无冲突"
# --------------------------------------------------------------------------------------


def test_disabled_merge_tree_degrades_block_level_but_still_reports_the_pair(tmp_path):
    repo, claude = _conflict_scene(tmp_path)
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(
        str(repo), claude_root, codex_root, _config_without_merge_tree(tmp_path), now=NOW
    )
    assert len(result.conflicts) == 1, "区块级关闭不影响「这两侧同改了同一文件」这个事实"
    record = result.conflicts[0]
    assert "block" not in record.levels
    assert record.degraded is True
    assert any("merge_tree_enabled" in item for item in record.degrade_reasons)
    assert [item.code for item in result.undetermined] == [detect.CODE_DEGRADED]
    assert result.counts()["degraded"] == 1
    assert result.counts()["merge_tree_runs"] == 0, "关闭后不该真的去跑 merge-tree"


def test_unrelated_histories_exit_128_is_degraded_not_no_conflict(tmp_path):
    """无共同祖先 → `merge-tree` exit 128 → `degraded` + `undetermined`，**不得**读成无冲突。"""
    repo = _make_repo(tmp_path / "repo", {"src/alpha.py": _PY_ALPHA})
    _git(["checkout", "--quiet", "--orphan", "orphan"], repo)
    _commit(repo, {"src/alpha.py": _PY_ALPHA.replace("    n = 5", "    n = 99")}, "orphan")
    _git(["checkout", "--quiet", "main"], repo)

    claude = tmp_path / "sessions" / "claude"
    root = str(repo).replace(os.sep, "/")
    _claude_session(claude / "sess-radar-0001.jsonl", "sess-radar-0001", root, "main",
                    [("src/alpha.py", "    a = 1", "    a = 11")])
    _claude_session(claude / "sess-radar-0002.jsonl", "sess-radar-0002", root, "orphan",
                    [("src/alpha.py", "    n = 5", "    n = 55")])
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)

    assert len(result.conflicts) == 1, "文件级事实不因试合并失败而消失"
    record = result.conflicts[0]
    assert record.levels == ("file",)
    assert record.degraded is True
    codes = [item.code for item in result.undetermined]
    assert detect.CODE_DEGRADED in codes
    detail = [item.detail for item in result.undetermined if item.code == detect.CODE_DEGRADED][0]
    # 降级原因必须**点到具体那一条**（"无共同祖先"与"未预期的退出码"是两条通路）——
    # 含糊一句"无法试合并"会让复核者无从下手，也会让"只打掉 exit 128 分支"的变异蒙混过关。
    assert "exit 128" in detail and "无共同祖先" in detail, detail


def test_session_without_branch_degrades_the_block_level(tmp_path):
    """会话没有 `gitBranch`（如实测的 Codex 侧）⇒ 无法定位两侧版本 ⇒ `degraded`。"""
    repo, claude = _conflict_scene(tmp_path)
    path = claude / "sess-radar-0002.jsonl"
    text = path.read_text(encoding="utf-8")
    mutated = text.replace('"gitBranch": "feat/agent-b"', '"gitBranch": ""')
    assert mutated != text
    _write_text(path, mutated)
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].degraded is True
    assert "gitBranch" in " ".join(result.conflicts[0].degrade_reasons)


# --------------------------------------------------------------------------------------
# 两个 worktree：区块级仍可判（共享对象库），符号级按"行号不可比"降级
# --------------------------------------------------------------------------------------


def test_two_worktrees_share_the_block_level_but_not_the_symbol_level(tmp_path):
    repo = _make_repo(tmp_path / "repo", {"src/alpha.py": _PY_ALPHA})
    _commit_on_branch(repo, "feat/agent-a", {"src/alpha.py": _PY_ALPHA.replace("    a = 1", "    a = 11")})
    second = tmp_path / "repo-b"
    _git(["worktree", "add", "--quiet", "-b", "feat/agent-b", str(second)], repo)
    _commit(second, {"src/alpha.py": _PY_ALPHA.replace("    a = 1", "    a = 22")})

    claude = tmp_path / "sessions" / "claude"
    root_a = str(repo).replace(os.sep, "/")
    root_b = str(second).replace(os.sep, "/")
    # 两个会话各自在**自己工作区的 HEAD 里**定位锚点（A 的 HEAD 是 main、B 的是 feat/agent-b）。
    _claude_session(claude / "sess-radar-0001.jsonl", "sess-radar-0001", root_a, "feat/agent-a",
                    [("src/alpha.py", "    a = 1", "    a = 11")])
    _claude_session(claude / "sess-radar-0002.jsonl", "sess-radar-0002", root_b, "feat/agent-b",
                    [("src/alpha.py", "    a = 22", "    a = 222")])
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)

    assert len(result.conflicts) == 1
    record = result.conflicts[0]
    assert record.workspace_a != record.workspace_b, "两个 worktree 应记为两个工作区"
    assert "block" in record.levels, "同一仓库的两个 worktree 共享对象库，试合并照样能跑"
    assert record.approximate is True, "跨工作区的行号不可比 ⇒ 不做符号级"
    assert "symbols" not in record.as_dict()
    assert [item.code for item in result.undetermined] == [detect.CODE_SYMBOL_UNAVAILABLE]


# --------------------------------------------------------------------------------------
# 三态之三：`unsupported_format`——上游没看懂的会话必须一路带出来，不静默
# --------------------------------------------------------------------------------------


def test_unsupported_session_format_is_carried_through_to_the_product(tmp_path):
    repo, claude = _conflict_scene(tmp_path)
    # 一条"带 message 但缺 cwd"的消息行：M1 判 unsupported_format，detect 不得把它吞掉。
    _write_text(
        claude / "sess-radar-9999.jsonl",
        json.dumps(
            {"type": "assistant", "sessionId": "sess-radar-9999",
             "message": {"content": []}, "timestamp": "2026-01-01T00:03:00Z"},
            ensure_ascii=False, sort_keys=True,
        ) + "\n",
    )
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)
    codes = [item.code for item in result.undetermined]
    assert "unsupported_format" in codes, "上游的解析缺口必须在 detect 的产物里点了名"
    assert result.conflicts, "带一个坏会话文件不该让整批检测失败"


def test_derived_siblings_are_deduped_at_the_end_to_end_level(tmp_path):
    """`derived_from` 相同的两个 subagent 同改同一文件 ⇒ 一条都不报，但**留下痕迹**。"""
    repo = _make_repo(tmp_path / "repo", {"src/alpha.py": _PY_ALPHA})
    _commit_on_branch(repo, "feat/agent-a", {"src/alpha.py": _PY_ALPHA.replace("    a = 1", "    a = 11")})
    _commit_on_branch(repo, "feat/agent-b", {"src/alpha.py": _PY_ALPHA.replace("    a = 1", "    a = 22")})
    claude = tmp_path / "sessions" / "claude"
    root = str(repo).replace(os.sep, "/")
    # Claude 的派生关系 = 同 `sessionId` 下 `isSidechain=False` 的那只文件（父会话只 `Read`，没有写操作）。
    _claude_session(claude / "sess-radar-0001.jsonl", "sess-radar-0001", root, "main", [],
                    calls=[("Read", {"file_path": "%s/src/alpha.py" % root})])
    _claude_session(claude / "sess-radar-0001a.jsonl", "sess-radar-0001", root, "feat/agent-a",
                    [("src/alpha.py", "    a = 1", "    a = 11")], sidechain=True)
    _claude_session(claude / "sess-radar-0001b.jsonl", "sess-radar-0001", root, "feat/agent-b",
                    [("src/alpha.py", "    a = 1", "    a = 22")], sidechain=True, start_minute=1)
    claude_root, codex_root = _roots(claude)
    result = detect.build_conflict_set(str(repo), claude_root, codex_root, _load_config(), now=NOW)
    assert result.conflicts == ()
    assert result.counts()["derived_sibling_pairs_skipped"] == 1
    assert any("derived_from" in note for note in result.notes)


# --------------------------------------------------------------------------------------
# CLI 契约（退出码 0 / 1）
# --------------------------------------------------------------------------------------


def _run_cli(repo, roots, extra=(), config_path=None):
    claude_root, codex_root = roots
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    argv = [sys.executable, "-m", "agent_conflict_radar"]
    if config_path is not None:
        argv += ["--config", str(config_path)]
    argv += ["detect", "--repo", str(repo),
             "--claude-root", claude_root, "--codex-root", codex_root, "--now", NOW]
    argv += list(extra)
    completed = subprocess.run(argv, cwd=str(REPO_ROOT), env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", "replace")


def test_cli_exit_codes_track_conflicts_and_undetermined_never_changes_them(tmp_path):
    repo, claude = _conflict_scene(tmp_path)
    roots = _roots(claude)
    code, out, err = _run_cli(repo, roots)
    assert code == EXIT_CONFLICTS_FOUND, err
    assert json.loads(out.decode("utf-8"))["conflicts"], "有冲突就必须有条目"

    # 区块级关闭 → `degraded` + `undetermined`，但**判定仍是"有冲突"**（undetermined 不改退出码）。
    cfg_path = tmp_path / "radar-no-merge-tree.toml"
    _config_without_merge_tree(tmp_path)
    code2, out2, err2 = _run_cli(repo, roots, config_path=cfg_path)
    assert code2 == EXIT_CONFLICTS_FOUND, err2
    payload2 = json.loads(out2.decode("utf-8"))
    assert payload2["undetermined"], "降级必须显式列出，不能悄悄降粒度"
    assert payload2["conflicts"], "降级不等于没有冲突"

    # 无冲突 → 0（对照组）
    clean = _make_repo(tmp_path / "clean-repo", {"src/alpha.py": _PY_ALPHA})
    empty = tmp_path / "clean-sessions"
    empty.mkdir()
    code3, _out3, err3 = _run_cli(clean, (str(empty), str(empty)))
    assert code3 == EXIT_OK, err3
