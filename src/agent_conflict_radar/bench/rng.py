"""确定性伪随机流（splitmix64）——合成矩阵生成器专用（`plan/05` §六）。

**为什么不用 stdlib `random`**：`random` 只承诺"给定种子在**同一版本**内可复现"，跨
解释器版本/实现（3.8 vs 3.12）不保证序列一致。而本项目的矩阵要跨 CI 四矩阵（ubuntu/windows ×
3.8/3.12）逐字节比对冻结产物——序列一变，`--check` 就红。故自研 64 位流：只依赖整数运算，
序列是**纯函数**。

三条纪律：

* **禁系统时钟**：本模块不 import `time` / 不调用 `datetime.now()`（`tests/test_bench_rng.py`
  用 AST 扫 import 面断言这一点）；
* **禁 set 迭代序**：本模块接口只收/只回 **序列**（list/tuple），调用方不得把 set 喂进来
  （`choice()` 会显式拒绝 set，见下）；
* **只用整数算术**：不使用浮点（浮点在不同平台上没有第二套语义，但会让"逐字节一致"依赖
  格式化精度，属无必要的风险）。

本文件整篇是**算法常量**（黄金比例常数、位移量、掩码、乘子），已按 K5 的维护流程在
`tests/test_config_literals.py` 的 `EXEMPT_FILES` 登记并写明理由——它们不是策略阈值。
"""

#: 64 位掩码（splitmix64 的全域模）。
_MASK64 = (1 << 64) - 1

#: splitmix64 的黄金比例增量。
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15

#: 两轮混淆乘子（与 splitmix64 原文一致）。
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB

_SHIFT_A = 30
_SHIFT_B = 27
_SHIFT_C = 31
_BITS = 64


class Rng(object):
    """64 位确定性伪随机流。状态只由 `seed` 决定，序列是种子的纯函数。"""

    __slots__ = ("_state", "_seed")

    def __init__(self, seed: int) -> None:
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise TypeError("seed 必须是整数（浮点/布尔的序列语义会随平台漂移）：%r" % (seed,))
        self._seed = seed & _MASK64
        self._state = self._seed

    @property
    def seed(self) -> int:
        return self._seed

    def next_u64(self) -> int:
        """下一个 64 位无符号整数（splitmix64 一步）。"""
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        value = self._state
        value = ((value ^ (value >> _SHIFT_A)) * _MIX_A) & _MASK64
        value = ((value ^ (value >> _SHIFT_B)) * _MIX_B) & _MASK64
        return (value ^ (value >> _SHIFT_C)) & _MASK64

    def below(self, bound: int) -> int:
        """返回 `[0, bound)` 内的整数。

        用**拒绝采样**而不是取模：取模会让低位偏置（`% bound` 对小 bound 引入偏差），
        偏置会让"分布均匀"的隐含声明变成假的。拒绝采样只依赖位运算，仍是纯函数。
        """
        if not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0:
            raise ValueError("bound 必须是正整数：%r" % (bound,))
        bits = bound.bit_length()
        while True:
            candidate = self.next_u64() >> (_BITS - bits) if bits < _BITS else self.next_u64()
            if candidate < bound:
                return candidate

    def choice(self, sequence):
        """从**序列**里取一项。

        `set` / `frozenset` / `dict` 一律显式拒绝：它们的迭代顺序取决于哈希，
        在不同解释器版本上会漂——"同一输入同一产物"的守门会因此变成偶发红。
        """
        items = _as_sequence(sequence)
        return items[self.below(len(items))]

    def shuffled(self, sequence):
        """返回打乱后的 **list**（Fisher-Yates；不修改入参）。"""
        items = list(_as_sequence(sequence))
        for index in range(len(items) - 1, 0, -1):
            other = self.below(index + 1)
            items[index], items[other] = items[other], items[index]
        return items


def _as_sequence(sequence):
    if isinstance(sequence, (set, frozenset, dict)):
        raise TypeError(
            "确定性纪律禁止对 %s 取元素/排序（迭代顺序随哈希漂移，K11 同族纪律）。"
            "请先 sorted() 成 list 再传入。" % type(sequence).__name__
        )
    if isinstance(sequence, (str, bytes)):
        raise TypeError("字符串不是元素序列：请传 list/tuple：%r" % (type(sequence).__name__,))
    return list(sequence)
