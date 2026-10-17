"""路径自适应与 expanduser 哨兵（K16）。

本机实测的两条坑：

1. **Windows 路径两套写法**：Git Bash 把 `~` 展开成 `/c/Users/...`，Windows Python 不认。
   所以工具必须自己在 Python 侧展开，且**不硬编码用户名**。
2. **`os.path.expanduser` 解不出主目录时把 `~` 原样返回**（不抛异常、`except` 防不住），
   天真实现在当前目录下建一个名为 `~` 的文件夹。本文件的判据是"**不写盘、不抛系统异常、
   不回落 CWD**"，三条都要断。
"""

import getpass
import os
from pathlib import Path

import pytest

from agent_conflict_radar.errors import ConfigError, EnvironmentError_
from agent_conflict_radar.paths import (
    expand_home,
    find_repo_root,
    normalize_path,
    require_repo_root,
)


def test_tilde_is_expanded_without_shell(tmp_path):
    expanded = expand_home("~")
    assert not expanded.startswith("~")
    assert os.path.isabs(expanded)


def test_expanduser_sentinel_raises_and_writes_nothing(monkeypatch, clean_cwd):
    """`expanduser` 解不出主目录（原样返回哨兵）→ 显式报错，且在 CWD **零写入**。"""

    def fake_expanduser(value):
        return value  # 模拟"解不出"：原样返回

    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)
    with pytest.raises(EnvironmentError_) as excinfo:
        expand_home("~/.claude")
    assert "主目录" in str(excinfo.value)
    assert not (Path(clean_cwd) / "~").exists(), "绝不能在当前目录创建名为 '~' 的目录"
    assert list(Path(clean_cwd).iterdir()) == [], "报错路径必须零写入"


def test_non_tilde_path_is_returned_verbatim(monkeypatch):
    def fake_expanduser(value):  # pragma: no cover - 不该被调用
        raise AssertionError("非 ~ 起头的路径不应调用 expanduser")

    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)
    assert expand_home("relative/path") == "relative/path"


def test_normalize_path_collapses_but_does_not_resolve_symlinks(tmp_path):
    target = tmp_path / "a" / "b"
    target.mkdir(parents=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建目录符号链接")
    normalized = normalize_path(str(link))
    assert str(normalized) == str(link), "worktree 路径可能本身就是符号链接，resolve 会改写它导致匹配失败"


def test_normalize_path_collapses_parent_segments():
    assert normalize_path("a/b/../c").as_posix().endswith("a/c")


def test_find_repo_root_from_package_dir(repo_root):
    assert find_repo_root() == Path(repo_root)
    assert find_repo_root(Path(repo_root) / "src" / "agent_conflict_radar") == Path(repo_root)


def test_find_repo_root_returns_none_when_absent(tmp_path):
    assert find_repo_root(tmp_path) is None


def test_require_repo_root_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        require_repo_root(tmp_path)


def _string_constants_outside_docstrings(tree):
    """返回代码位置上的字符串常量节点（**跳过文档字符串**）。

    为什么要跳过：本门禁的命题是"源码里不得**硬编码**用户名/主目录"。文档字符串里写下
    "Git Bash 把 `~` 展开成 /c/Users/…"是在**解释机制**，不是硬编码路径——不跳过就会命中
    说明文字，而"门禁因误报被随手放宽"是这类检查最常见的死法。
    """
    import ast

    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstring_ids.add(id(body[0].value))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids:
            found.append(node)
    return found


def _hardcoded_path_hits(source_root: Path, forbidden):
    """在源码的**代码位置**上找禁用路径片段，返回 (扫描文件数, 命中列表)。"""
    import ast

    offenders = []
    scanned = 0
    for path in sorted(source_root.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _string_constants_outside_docstrings(tree):
            for needle in forbidden:
                if needle and needle in node.value:
                    offenders.append("%s:%d 含硬编码路径片段 %r" % (path.name, node.lineno, needle))
    return scanned, offenders


def test_source_does_not_hardcode_username_or_home_paths(repo_root):
    """源码的代码位置上不得出现本机用户名或盘符化的用户目录写法。

    ⚠️ 判据必须落在**结构位置**（代码里的字符串常量）且**排除本测试自身**，
    否则测试文件里作为禁用词写下的路径会自己命中自己。
    """
    src = Path(repo_root) / "src" / "agent_conflict_radar"
    try:
        login = getpass.getuser()
    except Exception:  # pragma: no cover
        login = ""
    forbidden = []
    if login and len(login) >= 3:
        forbidden.append(login)
    forbidden.extend(["C:\\Users\\", "/home/", "/Users/"])
    scanned, offenders = _hardcoded_path_hits(src, forbidden)
    assert scanned > 0, "扫描面为空：本门禁在空转"
    assert offenders == [], "\n  ".join(["不得硬编码用户名/主目录（K16）:"] + offenders)


def test_hardcoded_path_scanner_actually_detects(tmp_path, write_lf):
    """探针自证：写一个真硬编码路径的模块，扫描器必须抓到（否则门禁是假门）。"""
    write_lf(tmp_path / "probe_path.py", 'DEFAULT_ROOT = "C:\\\\Users\\\\radar-probe\\\\.claude"\n')
    _scanned, offenders = _hardcoded_path_hits(tmp_path, ["C:\\Users\\"])
    assert offenders, "扫描器未检出注入的硬编码路径"


def test_hardcoded_path_scanner_ignores_docstrings(tmp_path, write_lf):
    """阴性对照：解释机制的文档字符串**不得**被判违规（否则门禁会因误报被放宽掉）。"""
    write_lf(tmp_path / "probe_doc.py", '"""说明：Git Bash 把 ~ 展开成 /home/user 形态。"""\n\nVALUE = 1\n')
    _scanned, offenders = _hardcoded_path_hits(tmp_path, ["/home/"])
    assert offenders == []


def test_paths_fixture_family_is_explicitly_passed(tmp_path, monkeypatch):
    """凡缺省值有副作用的参数，测试与演示一律显式传。

    本项目的规则：会话根目录留空 = 按常见位置探测（会读到**真实用户数据**），
    所以任何测试/演示都必须显式传临时目录，绝不依赖"自动发现"。
    """
    from agent_conflict_radar import config as config_module

    cfg = config_module.load()
    assert cfg.get("paths", "claude_root") == ""
    assert cfg.get("paths", "codex_root") == "", (
        "示例配置里会话根目录应为空（由用户显式传或探测）；测试不得依赖自动探测真实数据"
    )
