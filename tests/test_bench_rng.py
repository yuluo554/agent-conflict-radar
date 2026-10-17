"""确定性 RNG 的守门（`plan/05` §六：禁 stdlib `random`、禁系统时钟、禁 set 迭代序）。

为什么值得单独一个文件：`--check` 的"重跑生成器逐字节比对"只有在**序列本身跨版本稳定**时才有意义。
`random` 只承诺同一实现内可复现，跨 3.8/3.12 不保证——所以这里把序列**钉死成黄金值**：
黄金值变了，说明算法被动过，冻结产物必须整目录重生成（而不是让 CI 悄悄换一份矩阵）。
"""

import ast
import inspect
from pathlib import Path

import pytest

from agent_conflict_radar.bench import rng as rng_module


def _source() -> str:
    return Path(inspect.getsourcefile(rng_module)).read_text(encoding="utf-8")


def test_no_stdlib_random_import():
    """禁 `random`：它的序列只承诺同一实现内可复现，跨解释器版本不保证。"""
    tree = ast.parse(_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert "random" not in imported, "确定性纪律禁止 stdlib random（plan/05 §六）"


def test_no_clock_import():
    """禁系统时钟：产物里出现"生成时间"会让双跑逐字节一致永远红。"""
    tree = ast.parse(_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert not ({"time", "datetime"} & imported), "确定性纪律禁止读系统时钟（plan/05 §六）"


def test_golden_sequence_is_pinned():
    """黄金值：算法一旦被动过，这里先红——而不是让 CI 悄悄换一份矩阵。"""
    stream = rng_module.Rng(20260101)
    assert [stream.next_u64() for _ in range(4)] == [
        17486582413981831226,
        3190848937081373894,
        13905571665034498228,
        14227071806888807403,
    ]


def test_below_is_in_range_and_deterministic():
    first = [rng_module.Rng(1).below(10) for _ in range(1)]
    assert first == [9]
    stream = rng_module.Rng(1)
    values = [stream.below(10) for _ in range(8)]
    assert values == [9, 7, 7, 8, 4, 6, 9, 7]
    assert all(0 <= value < 10 for value in values)


def test_below_uses_rejection_sampling_not_modulo():
    """取模会让低位偏置；这里只断言"边界内每个值都取得到"，并把分布形态钉在黄金值上。"""
    stream = rng_module.Rng(42)
    seen = {stream.below(3) for _ in range(200)}
    assert seen == {0, 1, 2}, "3 个可能值里有取不到的：采样有偏或范围算错"


def test_shuffled_and_choice_are_pinned_and_do_not_mutate_input():
    items = ["a", "b", "c", "d", "e"]
    assert rng_module.Rng(7).shuffled(items) == ["e", "b", "c", "a", "d"]
    assert items == ["a", "b", "c", "d", "e"], "shuffled 不得就地修改入参"
    assert rng_module.Rng(3).choice(("x", "y", "z")) == "x"


def test_set_like_inputs_are_rejected_explicitly():
    """set 的迭代顺序随哈希漂移——显式拒绝，而不是"看起来能用"。"""
    for bad in ({"a", "b"}, frozenset({"a"}), {"a": 1}):
        with pytest.raises(TypeError):
            rng_module.Rng(1).choice(bad)
    with pytest.raises(TypeError):
        rng_module.Rng(1).shuffled({"a", "b"})


def test_non_integer_seed_and_bad_bound_are_rejected():
    with pytest.raises(TypeError):
        rng_module.Rng(1.5)
    with pytest.raises(TypeError):
        rng_module.Rng(True)
    with pytest.raises(ValueError):
        rng_module.Rng(1).below(0)
