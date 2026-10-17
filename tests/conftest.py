"""测试共用夹具。

**关于 sys.path 兜底**：README 的快速开始是 `python -m pip install -e ".[dev]"`，CI 也照这条走
（装完再跑测试），所以正常情况下被测对象是**安装面**上的包。本地未安装时本文件把 `src/` 放进
`sys.path` 作为便民兜底，并打印一行提示——避免"测试跑的是源码树、用户敲的是安装面"这种
两条通路混淆（`tools/verify_offline.py` 在 CI 里用 `--strict` 断言 console script 真的存在）。
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"

#: 是否走了 sys.path 兜底（未安装）。需要"安装面"证据的测试据此跳过并显式说明。
SRC_FALLBACK = False


def _installed_version():
    try:
        import importlib.metadata as metadata

        return metadata.version("agent-conflict-radar")
    except Exception:
        return None


if _installed_version() is None:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    SRC_FALLBACK = True
    sys.stderr.write(
        "[conftest] 未检测到已安装的 agent-conflict-radar，已回退到源码树 %s；"
        "安装面相关的断言将显式跳过。\n" % SRC_ROOT
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def src_root() -> Path:
    return SRC_ROOT


@pytest.fixture(scope="session")
def config_path(repo_root: Path) -> Path:
    return repo_root / "config" / "radar.toml"


@pytest.fixture(scope="session")
def installed_version():
    return _installed_version()


@pytest.fixture(scope="session")
def src_fallback() -> bool:
    return SRC_FALLBACK


def write_lf_text(path, text):
    """以 LF 行尾写文本。

    ⚠️ 不用 `Path.write_text(newline=)`：`newline` 参数是 **Python 3.10+** 才有的，
    在本项目底线解释器 3.8 上直接 `TypeError`（本机双解释器实测抓到过）。
    """
    target = Path(path)
    with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return target


@pytest.fixture
def write_lf():
    return write_lf_text


@pytest.fixture
def make_config(tmp_path, config_path):
    """把真实配置复制到临时目录并按需改写，返回 (路径, 写入函数) 二元组。

    复制真配置而不是手写一份：手写的"配置样本"会与 `config/radar.toml` 各自演化，
    测试就变成在验一个不存在的键空间。
    """

    def _make(mutate=None, extra_lines=(), drop_keys=(), filename="radar.toml"):
        text = config_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        kept = []
        section = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1]
            drop = False
            for path in drop_keys:
                drop_section, _, drop_key = path.partition(".")
                if section == drop_section and stripped.split("=")[0].strip() == drop_key:
                    drop = True
                    break
            if not drop:
                kept.append(line)
        text = "\n".join(kept)
        if mutate is not None:
            text = mutate(text)
        if extra_lines:
            text = text + "\n" + "\n".join(extra_lines) + "\n"
        return write_lf_text(Path(tmp_path) / filename, text)

    return _make


@pytest.fixture
def run_cli(capsys):
    """在进程内跑 CLI，返回 (退出码, stdout, stderr)。

    `capsys.readouterr()` 只能消费一次，故一次接住再分别返回（SKILL pytest 四坑之一）。
    """

    def _run(argv):
        from agent_conflict_radar.cli import main

        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def clean_cwd(tmp_path, monkeypatch):
    """把 CWD 切到临时目录，防止任何"回落当前目录"的行为污染仓库。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _env_without_network_proxy():
    env = dict(os.environ)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env
