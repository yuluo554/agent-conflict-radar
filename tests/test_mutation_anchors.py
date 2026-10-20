"""变异脚本的**锚点守门**（`tools/verify_mutation.py` 的 MUTATIONS 表）。

为什么需要这一条：变异脚本的"三重断言"只有在**跑到那一组**时才会发现锚点漂了。而
`apply_mutation` 的第三条断言（marker 必须命中）**只在运行时触发**——于是"锚点写着上一版
版本号"这种缺陷可以一路通过测试、通过发布门、被上传成 Release 附件，直到**下载者**按
README 跑 `python tools/verify_mutation.py` 才当场炸。

实测（v0.0.2 已发布物，2026-10-20）：

    M6 的 marker 是 `__version__ = "0.0.1"`，而包内 `__version__` 已是 `0.0.2`
    → python tools/verify_mutation.py --only M6
    → AssertionError: M6：锚点未命中 src/agent_conflict_radar/__init__.py …
    → exit 1

所以本文件把"每组的 marker 必须在其目标文件里**恰好命中一次**"落成**跑测试就能发现**的判据，
而不是留给变异脚本自己在其运行期发现。

判据三条（都对得上 `verify_mutation.py` 自己的纪律）：

1. 目标文件必须存在，且 marker **恰好命中 1 次**（0 次 = 锚点漂了；多次 = 锚点不够特异，
   `str.replace(..., 1)` 会改错地方）；
2. replacement 必须与 marker 不同（否则是一次静默 no-op 的"变异"）；
3. 每条 `must_fail` 的目标测试（`tests/<f>.py::<node>`）必须真实存在——变异打红一个不存在的
   测试会在 pytest 里得到"no tests ran"的**非零**退出码，被误读成"抓到了"（这是最坏的假绿）。

另配一条**可证伪**自证：拿一组人为造坏的锚点喂给同一个检查函数，必须被报出来。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_mutation_tool(repo_root: Path):
    """按文件路径加载 `tools/verify_mutation.py`（它不是包的一部分，不能 import 名字）。"""
    path = Path(repo_root) / "tools" / "verify_mutation.py"
    assert path.is_file(), "缺少守门变异脚本 tools/verify_mutation.py"
    spec = importlib.util.spec_from_file_location("radar_verify_mutation", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["radar_verify_mutation"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mutation_tool(repo_root):
    return _load_mutation_tool(Path(repo_root))


def _read(path: Path) -> str:
    with open(str(path), "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def anchor_problems(mutations, repo_root: Path):
    """返回 `[(ident, 原因)]`；空列表 = 全部锚点可落。

    抽成独立函数是为了让自证用例能喂**人为造坏**的锚点进来——否则"检查函数永远返回空列表"
    和"锚点真的都对"在测试里长得一模一样。
    """
    problems = []
    for mutation in mutations:
        target = Path(repo_root) / mutation.path
        if not target.is_file():
            problems.append((mutation.ident, "目标文件不存在：%s" % mutation.path))
            continue
        if mutation.replacement == mutation.marker:
            problems.append((mutation.ident, "replacement 与 marker 相同（静默 no-op）"))
            continue
        hits = _read(target).count(mutation.marker)
        if hits != 1:
            problems.append(
                (
                    mutation.ident,
                    "marker 在 %s 里命中 %d 次（要求恰好 1 次）：%r"
                    % (mutation.path, hits, mutation.marker),
                )
            )
    return problems


def test_every_mutation_anchor_lands_exactly_once(mutation_tool, repo_root):
    """MUTATIONS 表里**每一组**的 marker 都必须在其目标文件里恰好命中一次。

    这条若红，`tools/verify_mutation.py` 会在跑到那一组时抛 AssertionError——
    在发布物里就是"下载者第一条命令就炸"。
    """
    problems = anchor_problems(mutation_tool.MUTATIONS, Path(repo_root))
    assert problems == [], "\n  ".join(
        ["变异脚本的锚点不可落（%d 组）：" % len(problems)]
        + ["%s：%s" % (ident, reason) for ident, reason in problems]
    )


def test_mutation_ids_are_unique_and_cover_the_table(mutation_tool):
    """组号唯一且非空：重复组号会让"每组都跑过"看起来成立而实际漏跑。"""
    idents = [mutation.ident for mutation in mutation_tool.MUTATIONS]
    assert len(idents) >= 30, "变异组只剩 %d 个：表被删减过？" % len(idents)
    assert len(set(idents)) == len(idents), "变异组号重复：%s" % idents


def test_every_must_fail_target_exists(mutation_tool, repo_root):
    """每条 `must_fail` 指向的 `tests/<f>.py::<node>` 必须真实存在。

    为什么必须查：pytest 对**不存在的 node id** 返回非零退出码（"no tests ran"），
    变异脚本会把那种非零当成"守门被变异打红"——于是门是假的而报告是 PASS。
    """
    missing = []
    for mutation in mutation_tool.MUTATIONS:
        node = mutation.must_fail
        file_part, _, node_part = node.partition("::")
        target = Path(repo_root) / file_part
        if not target.is_file():
            missing.append("%s：测试文件不存在 %s" % (mutation.ident, file_part))
            continue
        if node_part and ("def %s(" % node_part) not in _read(target):
            missing.append("%s：测试函数不存在 %s" % (mutation.ident, node))
    assert missing == [], "\n  ".join(["变异脚本指向不存在的守门："] + missing)


def test_anchor_check_is_not_vacuous(mutation_tool, repo_root):
    """可证伪：人为造坏的三种锚点必须被同一个检查函数报出来。"""
    Mutation = mutation_tool.Mutation
    broken = [
        Mutation("X0", "src/agent_conflict_radar/__init__.py", "不存在的锚点串", "x", "tests/x.py::y", ""),
        Mutation("X1", "src/agent_conflict_radar/__init__.py", "__version__ = ", "__version__ = ", "tests/x.py::y", ""),
        Mutation("X2", "src/agent_conflict_radar/__missing__.py", "x", "y", "tests/x.py::y", ""),
    ]
    reasons = dict(anchor_problems(broken, Path(repo_root)))
    assert "X0" in reasons and "命中 0 次" in reasons["X0"], "锚点未命中没被报出来"
    assert "X1" in reasons and "no-op" in reasons["X1"], "replacement == marker 没被报出来"
    assert "X2" in reasons and "不存在" in reasons["X2"], "目标文件缺失没被报出来"


def test_the_version_literal_is_not_an_anchor_anywhere(mutation_tool):
    """版本号不得出现在任何 marker 里（v0.0.2 实测踩中的失效模式）。

    锚点里写当前版本号 → **每次发版都会失效**，而失效只在运行期发现。M6 已改成
    `__version__ = "` + 注释掉余下的原值，本用例钉住"别再退回去"。
    """
    offenders = [
        (mutation.ident, mutation.marker)
        for mutation in mutation_tool.MUTATIONS
        if mutation.path.endswith("__init__.py") and '"0.' in mutation.marker
        or mutation.path.endswith("__init__.py") and "'0." in mutation.marker
    ]
    assert offenders == [], "包版本文件的变异锚点里含版本号字面量（发版即失效）：%s" % offenders
