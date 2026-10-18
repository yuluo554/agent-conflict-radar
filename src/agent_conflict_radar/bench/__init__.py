"""合成冲突矩阵的生成器（**包内模块**，不是仓库根的脚本）。

放包内是有意的（`plan/03` §六 / `plan/07` 决策记录）：仓库根的顶层脚本不进安装面，
装完之后 `python -m agent_conflict_radar.bench.gen` 就会 `ModuleNotFoundError`——
这类"源码态能跑、安装面报错"的缺陷会潜伏好几个里程碑。

分工（`plan/05` §二）：

* `agent_conflict_radar.bench.rng` —— 确定性伪随机流（禁 stdlib `random`）；
* `agent_conflict_radar.bench.gen` —— 场景构造 + 植入真值 + 覆盖度台账 + 两层 `--check`；
* `agent_conflict_radar.bench.score` —— `radar bench` 的**评分**（物化 → 跑链路 → 集合精确匹配）；
* 仓库根的 `bench/` —— **冻结数据**（生成物，禁手改）。

> **可导入的是生成器与评分器，`bench/` 只是数据**：两者名字相近但性质不同，别把数据当模块改。
>
> **评分为何不叫 `bench.py`**：`agent_conflict_radar.bench` 已经是本包的名字，同目录再放
> `bench.py` 会被包静默遮蔽（本机实测：`import pkg.bench` 拿到的是 `pkg/bench/__init__.py`）。
> 命令面仍是 `radar bench`，实现落在 `bench/score.py`。

这里**刻意不做** `from . import gen` 的预导入：`python -m agent_conflict_radar.bench.gen`
本来就会导入子模块，预导入只会让"包 __init__ 拉着生成器一起进内存"（并制造无谓的循环导入风险）。
"""
