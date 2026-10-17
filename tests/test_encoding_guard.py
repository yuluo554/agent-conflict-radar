"""编码守卫（K8）——"本机全绿、CI 全红"的头号来源。

`py -X utf8` 只是本机习惯：它只改**我们敲的那条命令**的 stdio，改不了
① 用户直接敲 `radar`（没有该开关）、② 子进程的解码通路（走 locale）、③ CI 管道（cp1252）。

本文件用 `TextIOWrapper(BytesIO(), encoding="cp1252", errors="strict")` **在本机复现 CI 的编码缺口**
（不必等 CI 才知道），并断言中日韩控制台编码**保持不动**（重配反而会让控制台乱码）。
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar.cli import _ensure_utf8_stdio

CHINESE = "中文输出：即将冲突"


class _FakeStream(io.TextIOWrapper):
    pass


def _stream(encoding):
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict", newline="")


def _patch_stream(monkeypatch, name, stream):
    monkeypatch.setattr(sys, name, stream)


def test_cp1252_stream_is_reconfigured_to_utf8(monkeypatch):
    stream = _stream("cp1252")
    _patch_stream(monkeypatch, "stdout", stream)
    _ensure_utf8_stdio()
    assert stream.encoding.lower().replace("_", "-").startswith("utf-8")
    stream.write(CHINESE)
    stream.flush()
    assert stream.buffer.getvalue().decode("utf-8") == CHINESE


def test_cp1252_stderr_is_reconfigured_too(monkeypatch):
    stream = _stream("cp1252")
    _patch_stream(monkeypatch, "stderr", stream)
    _ensure_utf8_stdio()
    stream.write(CHINESE)
    stream.flush()
    assert stream.buffer.getvalue().decode("utf-8") == CHINESE


def test_ascii_stream_is_reconfigured(monkeypatch):
    stream = _stream("ascii")
    _patch_stream(monkeypatch, "stdout", stream)
    _ensure_utf8_stdio()
    stream.write(CHINESE)
    stream.flush()
    assert stream.buffer.getvalue().decode("utf-8") == CHINESE


@pytest.mark.parametrize("encoding", ["cp936", "gbk", "gb18030", "cp950"])
def test_cjk_console_encoding_is_left_untouched(monkeypatch, encoding):
    """中文控制台按本地码页渲染；改成 utf-8 反而乱码，故**保持不动**。"""
    stream = _stream(encoding)
    _patch_stream(monkeypatch, "stdout", stream)
    _ensure_utf8_stdio()
    assert stream.encoding.lower().replace("_", "-") == encoding.replace("_", "-")


def test_utf8_stream_is_left_untouched(monkeypatch):
    stream = _stream("utf-8")
    _patch_stream(monkeypatch, "stdout", stream)
    _ensure_utf8_stdio()
    assert stream.encoding.lower().replace("_", "-").startswith("utf-8")


def test_stream_without_reconfigure_does_not_crash(monkeypatch):
    """StringIO 一类桩对象没有 `reconfigure`：守卫必须静默跳过而不是抛异常。"""
    stream = io.StringIO()
    _patch_stream(monkeypatch, "stdout", stream)
    _ensure_utf8_stdio()
    stream.write(CHINESE)
    assert stream.getvalue() == CHINESE


def test_guard_is_idempotent(monkeypatch):
    stream = _stream("cp1252")
    _patch_stream(monkeypatch, "stdout", stream)
    _ensure_utf8_stdio()
    first = stream.encoding
    _ensure_utf8_stdio()
    assert stream.encoding == first


# --------------------------------------------------------------------------------------
# 端到端：真子进程里把 stdout 编码强制成 cp1252，中文输出不得崩
# --------------------------------------------------------------------------------------


def test_subprocess_with_cp1252_stdio_prints_chinese(repo_root):
    """端到端复现 CI 缺口：`radar selftest` 会打印中文，cp1252 严格流下若无守卫必抛
    `UnicodeEncodeError`（进程退出码非 0）。"""
    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONUTF8", None)
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar", "selftest"],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, (
        "cp1252 stdio 下中文输出失败：stdout=%r stderr=%r"
        % (completed.stdout[:400], completed.stderr[-400:])
    )
    assert "UnicodeEncodeError" not in completed.stderr.decode("utf-8", errors="replace")
    assert completed.stdout.decode("utf-8") != ""


def test_source_files_declare_explicit_encoding(repo_root):
    """源码里的文本 `open(...)` 必须显式声明 `encoding="utf-8"`（不依赖 locale）。

    实现为 AST 判定而不是子串搜索：子串搜索既会漏（写法多样）又会误报（注释里出现 open( ），
    而"判定词表/判据落在结构位置"是这类门禁的通用要求。
    """
    import ast

    src = Path(repo_root) / "src" / "agent_conflict_radar"
    offenders = []
    scanned = 0
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "open"):
                continue
            scanned += 1
            mode = "r"
            for arg in node.args[1:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    mode = arg.value
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    mode = keyword.value.value
            is_binary = "b" in mode
            has_encoding = any(keyword.arg == "encoding" for keyword in node.keywords)
            if is_binary and has_encoding:
                offenders.append("%s:%d 二进制 open 不应带 encoding" % (path.name, node.lineno))
            if not is_binary and not has_encoding:
                offenders.append("%s:%d 文本 open 缺少 encoding=\"utf-8\"" % (path.name, node.lineno))
    assert scanned > 0, "扫描面为空：本门禁在空转"
    assert offenders == [], "\n  ".join(["文本读写必须显式 utf-8（K8）:"] + offenders)
