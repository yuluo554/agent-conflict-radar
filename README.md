# agent-conflict-radar · 多 agent 并行开发冲突雷达

**多个 agent 并行改同一个仓库时，冲突往往在合并那一刻才暴露——而那时一个 agent 已经悄悄覆盖了另一个的工作。本工具在写入发生前预警**：按 worktree / 会话 / 文件 / 函数符号四个粒度比对"谁正在改什么"，给出即将冲突的清单。

纯本地 Python CLI · 只读 · 零上传 · 零第三方运行时依赖。

---

## ✅ 已发布：v0.0.1（2026-10-18），命令面 7/7

七条命令全部落地，合成冲突矩阵与意图矩阵已入仓可审计，`radar bench` 可**一键复跑评分**。

**发布物**：[Release v0.0.1](https://github.com/yuluo554/agent-conflict-radar/releases/tag/v0.0.1)
附**手工上传**的源码包 `agent_conflict_radar-0.0.1.tar.gz`
（sha256 `f19688f1d6338b2adc3455bcc3b216e0c0633fda1eafa73da0598ddfa14347ab`，登记在
`plan/release-assets.json`）。CI 四矩阵 `windows/ubuntu × 3.8/3.12` 全绿。

`scripts/check_release.py` 是**发布终态自检门**（离线 C01–C11 / 在线 O01–O07，刻意不进 CI），
总共 18 条检查、18 组门自身变异（**检查项数 == 变异组数**），发布时 `--online` 无 FAIL。

| 命令 | 状态 | 计划里程碑 |
|---|---|---|
| `radar scan` | ✅ 已交付 | M1 |
| `radar intent` | ✅ 已交付 | M2 |
| `radar detect` | ✅ 已交付 | M3 |
| `radar report` | ✅ 已交付 | M4 |
| `radar bench` | ✅ 已交付 | M5 |
| `radar config` | ✅ 已交付 | M0 |
| `radar selftest` | ✅ 已交付 | M0 |

M5 起**没有"阶段未就绪"这第五条退出码**：`4` 随最后一条命令交付整条退役（K1 四步），
命令面只剩题面锁定的 `0/1/2/3` 四语义。

**`radar bench` 的退出码语义**：**全部场景通过 → 0；任一场景失败 → 1**。这里的 `1` 是
"**基准未达标**"，与 `detect` / `report` 的"检出冲突"**不是同一件事**——不要因为评分失败去改仓库代码。
`--only` 未知 id 或过滤后为空 → 2；矩阵目录缺失 / 缺 git → 3。

**`radar scan` 的退出码语义**：成功**恒为 0**；`undetermined`（未识别的会话形态、无消息行的文件等）只作为提示出现在产物里，**不改退出码**——它是"我们没看懂"，不是"有冲突"。真正的环境问题（`--repo` 不在 git 仓库内、显式指定的会话根不存在）才给 exit 3，且不吐任何产物。

**`radar intent` 的退出码语义**：同样**成功恒为 0**。落点三分法 `exact` / `coarse` / `unknown` 是**产物字段**而不是退出码——`coarse`（`replace_all` / 锚点多处命中）与 `unknown`（`MultiEdit` / `file_path` 缺失）是"我们没定位到精确区间"，不是"有冲突"。环境问题（非 git 仓库 / 会话源不存在）仍是 exit 3。

**`radar detect` 的退出码语义**：**有冲突 → 1，无冲突 → 0**（这是本项目第一条真的会用 1 的命令，也是题面 §M4 的 `1 = 有冲突` 首次落地）。`undetermined` / `degraded` / `approximate` **不改变**这个判定——它们是"这条判不准"的显式标注，不是"有冲突"；但产物与报告里必须逐条列出来（"没底"绝不能读成"没问题"）。环境问题（非 git 仓库 / 会话源不存在 / git 超时）仍是 exit 3。

**`radar report` 的退出码语义**：与 `detect` **同一条口径**——**有冲突 → 1，无冲突 → 0**。它不重新判定：报告只消费 `detect` 的结论（渲染层零判定）。`undetermined` / `degraded` / `approximate` **不改**退出码，但报告里有独立的「未判定」小节逐条列出。环境问题（非 git 仓库 / 会话源不存在 / git 超时）仍是 exit 3；未知 `--format` → exit 2。

进度与逐棒 DoD 见 [`plan/06-里程碑.md`](plan/06-里程碑.md)；发布留档见
[`plan/RELEASE-M6.md`](plan/RELEASE-M6.md)（tag 前内容 + 文末「tag 后追加事实」分栏）。

---

## 三分钟上手

```bash
# 1) 安装（零运行时依赖，秒装；dev extra 只含测试期依赖 pytest，外加发布门真建 sdist 用的 build）
python -m pip install -e ".[dev]"

# 2) 看生效配置：确认所有数值只有一个来源
radar config

# 3) 自检：配置 / 退出码契约 / 序列化契约 / 阶段表 / 包版本
radar selftest

# 4) 等价的模块通路（README 与 CI 对两条通路都冒烟）
python -m agent_conflict_radar --version
```

`pip install -e ".[dev]"` 之后跑测试：

```bash
python -m pytest -q
```

### 合成场景演示（`bench` 评分）

```bash
radar bench                                   # 跑整棵矩阵（冲突 7 条 + 意图 8 条）并对账真值
radar bench --only same_symbol_diff_lines     # 只跑指定场景（逗号分隔可多条）
radar bench --bench-dir bench --out-dir out   # 显式指定矩阵目录与产物目录
```

输出：逐场景 `期望 / 实际 / 判定` 三列 + 覆盖度门槛复核 + 汇总；整矩阵跑时 `last_run.json`
默认落在矩阵目录（给 `--out-dir` 则落那里），走冻结序列化契约（K2），**不含本机路径**（K17）。
`--only` 是**抽检**：它**不覆盖**矩阵目录里的整矩阵记录（要落盘请显式给 `--out-dir`）——
否则跑一次单场景就会把"最近一次整矩阵判定"换成半份结果。

### 真实数据的只读演示（`scan` / `intent` / `detect` / `report` 已交付）

```bash
# 工作区与会话发现（会话根默认按常见位置探测；也可显式传）
radar scan --repo .

# 显式指定双 harness 的会话根（推荐：控制扫描面，避免顺手读进无关目录）
radar scan --repo . --claude-root <你的 Claude 会话根> --codex-root <你的 Codex 会话根>

# 落盘产物 + 固定参考时刻（确定性演示与基准必须显式传 --now）
radar scan --repo . --out-dir out --now 2026-01-01T10:00:00Z

# 变更意图：会话写操作 + 未提交 diff → 文件集合与改动行区间
radar intent --repo . --claude-root <你的 Claude 会话根> --codex-root <你的 Codex 会话根>
radar intent --repo . --out-dir out --now 2026-01-01T10:00:00Z

# 三级检测：文件级 → 区块级（无副作用试合并）→ 符号级；有冲突 exit 1、无冲突 exit 0
radar detect --repo . --claude-root <你的 Claude 会话根> --codex-root <你的 Codex 会话根>
radar detect --repo . --out-dir out

# 报告：Markdown（人读）+ conflicts.json（机读）双轨；有冲突 exit 1、无冲突 exit 0
radar report --repo . --out-dir out --format both
radar report --repo . --format json          # 只打机读 JSON（与 detect 的 conflicts.json 同内容同字节）
radar report --repo . --format md            # 只打人读 Markdown
```

`scan` 的输出（stdout，或 `--out-dir` 下的 `scan.json`）：工作区表、会话归集表（含 `derived_from` 去重）、活跃 cell 表、`undetermined` 独立分区与计数。**它不做任何冲突判定**——判定在 M3。

`intent` 的输出（stdout，或 `--out-dir` 下的 `intent.json`）：每条 `(workspace, path)` 的 `sessions` / `last_write_ts` / `changed_ranges` / `precision` / `ranges_source` / `approximate` / `reasons` / `evidence`，逐会话的 `writes[]`（谁改了哪一段），以及 `undetermined` 与计数。**它也不做冲突判定**——只把"谁正在改什么"整理成可对账的结构。

`detect` 的输出（stdout，或 `--out-dir` 下的 `conflicts.json`）：每条**冲突记录 = 一个 `(workspace_a, workspace_b, path)` 组合**，字段 `levels` 是命中的粒度**集合**（`file` / `block` / `symbol`）、`level` 是其中最高的一档、`symbols` 是命中的符号限定名集合、`line_ranges` 是见证对两侧的改动区间、`severity` 按 `[severity]` 权重打分，另有 `degraded` / `approximate` / `evidence` 与会话归属。

`report` 的输出（stdout，或 `--out-dir` 下的 `report.md` + `conflicts.json`）：**Markdown 人读**（参数来源块 / 结论摘要 / 冲突明细 / 独立的「未判定」小节 / 引擎说明）与 **JSON 机读**。两条纪律：

* **单一渲染源**：JSON 就是 `detect` 的 `conflicts.json`（**同内容同字节**），Markdown 是这份 JSON 的**纯函数**——不存在"两份各自生成再人工比对"的形态；`--format` 只决定打印/落盘哪一份，不改变内容。
* **渲染三律**（K13）：零判定（不 import 任何判定模块、不含阈值字面量）+ 零外链（断网可打开，断言**常驻渲染出口**）+ 双跑逐字节一致。建议文案是**规则模板**（按 `severity_key` 分派固定文案），不是模型判断；时间一律呈现原值，不编造"预计完成时间"。

### 三级判据与降级纪律（`detect`）

| 粒度 | 判据 |
|---|---|
| **文件级** | 同一 `path` 出现在两个**不同且活跃**的 `(workspace, session)` 组里（活跃 = M1 的 `active_cells`） |
| **区块级** | 两侧所在分支做 `git merge-tree --write-tree`（只读），冲突路径里含本 `path` |
| **符号级** | `ast` 取 `HEAD` 版本里函数/类/方法的限定名与行区间（含嵌套 `A.B.f`），两侧改动落在**同一符号**、或落在**相邻符号**（间距 ≤ `symbol.adjacent_tolerance`） |

四条纪律（都写进了测试）：

* **同符号 / 相邻都算命中，"同文件不同符号"不升格**：`threshold_exact`（间距 == 容差，命中）与 `threshold_near_miss`（间距 == 容差 + 1，不命中）**成对**卡在阈值两侧；符号按**限定名**匹配，同名不同作用域不同键。
* **subagent 去重**：两侧 `derived_from` 相同（同一 parent 派生的 subagent）→ **默认不产出该对**，产物里登记 `derived_sibling_pairs_skipped`（"有痕迹"而不是悄悄消失）。
* **判不出来就说判不出来**：`merge-tree` 无共同祖先（exit 128）/ 会话没有 `gitBranch` / 两侧不在同一仓库 / 试合并超时 / 配置里关闭了试合并 → 该条 `degraded=true` + `undetermined(degraded)`，粒度降为文件级。`ast` 失败 / 取不到 `HEAD` 版本 / 两侧跨工作区（行号不可比）→ `approximate=true` + `undetermined(symbol_unavailable)`，且该条**不出现符号级字段**（R4 口径：那是"我们没做"，不是"没有符号命中"）。**任何情况下都不把"没底"写成"无冲突"。**
* **计数两栏**：`counts.by_max_level` 是**条目数按最高粒度的集合划分**（`sum == len(conflicts)`），`counts.by_level_membership` 是**各粒度的成员数**（一条记录可同时命中多级，故可大于条目数）；`undetermined` 独立分区、不计入冲突。真值按 `levels` / `symbols` **集合精确匹配**（多报、漏报均失败）。

### 意图落点三分法（`exact` / `coarse` / `unknown`）

| 落点 | 判据 | 产物形态 |
|---|---|---|
| `exact` | 改动区间可**独立复算**：磁盘 `git diff -U0` 的 hunk，或会话锚点在 `HEAD` 基线里**唯一命中** | `changed_ranges` 非空 |
| `coarse` | 文件定位到了，但区间不可精确断言：`replace_all` / 锚点 0 处或多处命中 / 写内容与基线相同 / 删除 / 非 git 工作区 | `changed_ranges` 为空（**不编"看起来精确"的区间**） |
| `unknown` | 连文件都定不下来：`MultiEdit`（本机 0 次出现）/ `file_path` 缺失 / patch 里没有文件指令行 | `path` 为空 + 计数 |

三条纪律（都写进了测试）：

* **锚点多处命中 → 显式降级**，并在 `reasons` 里点名命中次数（`anchor_ambiguous#2`），**绝不挑第一个**；
* **磁盘是事实**：会话区间与磁盘 hunk 不一致时以磁盘为准，`ranges_source=disk`，并在 `reasons` 里点名 `disk_and_session_disagree`（会话原值保留在 `writes[]` 里，可回指）；
* **非 Python 文件**（R4）：行区间照给但 `approximate=true`，产物里**不出现任何符号字段**——符号级能力只对 `.py` 成立，未闭环的不宣称已支持。

> 真实本机数据只作**可行性演示与人工抽验**：本机实测（基准日 2026-10-17）309 对时间重叠会话、63 个独立会话、独立重叠 22 对，而**同文件重叠 0 对**——真实并行冲突样本几乎为零。因此检出能力**只能由合成矩阵断言**（见下方"诚实披露"）。

---

## 四级粒度

| 级别 | 判据 | 证据 |
|---|---|---|
| **文件级** | 同一文件在两个**活跃**工作区/会话中被修改 | 各会话最后写入时间 |
| **区块级** | `git merge-tree --write-tree` **无副作用试合并**后的冲突块 | 冲突路径与冲突块（HF 形态） |
| **符号级** | Python `ast` 取函数/类/方法的限定名与行区间，两侧改动落在**同一或相邻符号** | 符号限定名 + 重叠/相邻行区间 |
| **会话/工作区级** | 归集"活跃 agent × 工作区 × 时间窗"表，subagent 标 `derived_from` 去重 | 会话文件 + 源行号 |

**只读边界**：`--write-tree` 会在对象库写入临时 tree/blob 对象（**不改索引、不改工作区、不建分支、不动 HEAD**）。本工具**绝不**执行 merge/rebase、绝不写 git 索引、绝不修改你的代码。`tests/test_detect.py::test_detect_is_read_only_for_worktree_and_index` 在跑前跑后核对工作区/索引/HEAD 指纹。

`radar detect` 的严重度按 `[severity]` 权重选档（**只引用键名，数值只在 `config/radar.toml`**）：同一符号被两侧修改 > 同文件不同符号 > 行区间相邻 > 仅文件级同改。

---

## 合成冲突矩阵（已入仓，M1）与意图矩阵（M2）

真实并行冲突样本几乎为零（见下方"诚实披露"），所以**检出能力只能由合成矩阵断言**。矩阵已随仓冻结在 `bench/`：

| 路径 | 内容 |
|---|---|
| `bench/manifest.json` | 冲突场景清单 + 覆盖度门槛（每类 ≥1 + 集合覆盖 + 显式 `missing_types`）+ 生成器版本 + 真值 sha256 台账 |
| `bench/scenarios/<id>/repo/` | 合成仓库的**基线**源码（纯文本；`.git` 刻意不入仓，见下） |
| `bench/scenarios/<id>/sessions/` | 合成会话日志（仿 Claude Code / Codex 的真实形态，`{{REPO_ROOT}}` 为占位符） |
| `bench/scenarios/<id>/truth.json` | **植入真值**：只存输入与期望（几何 + `levels_expected`/`symbols_expected` + `objects_forbidden` 反向样例） |
| `bench/intents/manifest.json` | **意图矩阵**台账（M2）：覆盖度门槛 + 每条意图真值的 sha256 |
| `bench/intents/<id>/` | 意图场景：`repo/`（基线）+ `sessions/` + `truth.json`（`entries_expected` / `unknown_expected` / `counts_expected` / `geometry`） |

冲突场景七条：`same_file_diff_symbol` / `same_symbol_diff_lines` / `whole_file_overwrite` / `subagent_derived` / `negative_no_overlap` / `threshold_exact` / `threshold_near_miss`（最后两条**成对**卡在相邻容差两侧）。

意图场景八条（每条对应三分法的一条分支或一条降级纪律）：`intent_edit_exact` / `intent_replace_all_coarse` / `intent_ambiguous_anchor_coarse` / `intent_multi_edit_unknown` / `intent_codex_exec_patch` / `intent_write_and_non_python` / `intent_multi_write_merge` / `intent_disk_wins`。

三条值得写进 README 的纪律：

* **真值可独立复算**：真值里没有 `observed_*` 字段；把检测引擎整个注释掉，光看 `repo/` 原文 + 几何 + `config/radar.toml` 也能把期望值重新算出来（`tests/test_bench_matrix.py` 与 `tests/test_intent.py` 就是这么验的）。
* **阈值不在真值里复制**：涉及阈值处一律写成指向 `config` 的符号引用；`--check` 会**现场读 config 求值**——改了阈值而真值不动，当场变红。
* **`.git` 不入冻结产物**：`.git` 内部字节随 zlib/git 版本漂，跨平台不可能逐字节重现。提交的可复现性改用更强的判据——`--check` 重新物化合成仓库并**复算提交 sha**（sha 只由内容与固定元数据决定）。

矩阵生成器在包内（`python -m agent_conflict_radar.bench.gen`；`--out bench` 重建 / `--check` 两层自检 / `--materialize <id> --dest <dir>` 物化冲突场景 / `--materialize-intent <id> --dest <dir>` 物化意图场景）。CI 每次都会跑 `--check`。

`radar bench` 是**消费侧**：它把矩阵逐场景物化成真 git 仓库 + 真会话日志，跑 `scan → intent → detect` 完整链路，再与真值做**集合精确匹配**——多报（extra）、漏报（missing）都计失败。评分的实现在包内 `agent_conflict_radar/bench/score.py`（不与 `bench/` 数据目录同名，否则会被包遮蔽）。

> 合成数据白名单（K11）：假项目名 `demo-radar-alpha`、假 session id `sess-radar-NNNN`、假用户名 `radar-user`、固定基准时间 `2026-01-01T00:00:00Z` 起的确定偏移。真实日志、真实路径、真实 session id **一律不入仓**（`tools`/`tests` 有零命中断言）。

---

## 退出码语义

| 码 | 语义 |
|---|---|
| `0` | 无冲突 |
| `1` | 有冲突 |
| `2` | 用法错误（未知子命令 / 缺必填参数 / 未知 `--format` / 路径不存在） |
| `3` | 依赖或环境缺失（git 不可用 / 配置缺失或不可解析 / 会话源不存在 / `--repo` 不在 git 仓库内） |

> 退出码非 0 **不一定**是跑挂：`detect` / `report` 对存在冲突的仓库返回 `1` 是**既定语义**，不是故障；
> `scan` / `intent` 采到 `undetermined` / `coarse` / `unknown` 仍是 `0`；`detect` / `report` 采到
> `undetermined` / `degraded` / `approximate` 也**不改**退出码——只在产物里逐条列出（见上文"当前状态"）。
> `bench` 的 `1` 是"**基准未达标**"（某条场景与真值不符），不是"检出冲突"。
>
> 骨架期曾有 `4 = 阶段未就绪`，M5 交付最后一条命令后整条退役（`exit_codes.py` 只剩四语义，
> 并有 `not hasattr` 防复活断言）。

---

## 配置项与数值的唯一位置

**所有数值只在 [`config/radar.toml`](config/radar.toml) 定义一次**；README、报告、基准、计划文档一律**引用**它，没有第二份数值表。代码里**零内联默认值**：配置缺失、键名未知、类型不符或出现解析器不支持的 TOML 形态，一律**显式报错**（退出码 3），**绝不回落默认值**。

| 配置节 | 管什么 |
|---|---|
| `[schema]` | 键空间版本（不认识即报错，不按最宽松规则猜测） |
| `[window]` | 活跃时间窗、会话扫描窗口 |
| `[symbol]` | 行区间"相邻"容差、"重叠"最小行数 |
| `[severity]` | 四级严重度权重（排序与分级唯一依据） |
| `[git]` | git 子进程超时、是否启用 `merge-tree` 试合并 |
| `[report]` | 单条冲突证据条数上限、是否尝试桌面通知 |
| `[paths]` | 会话根目录（留空 = 按常见位置探测，**不硬编码用户名**） |

看生效值：`radar config`（输出含 `source_path`，便于核对"这个阈值是从哪个文件读出来的"）。

---

## 命令总表

| 命令 | 用途 | 里程碑 |
|---|---|---|
| `radar scan` | 工作区与会话发现（worktree + 双 harness 会话归集） | M1 |
| `radar intent` | 变更意图提取（写操作 + 未提交 diff） | M2 |
| `radar detect` | 三级冲突检测（文件 / 区块 / 符号） | M3 |
| `radar report` | 预警报告（Markdown + JSON 双输出） | M4 |
| `radar bench` | 合成矩阵评分 + 植入真值对账（逐场景 期望/实际/判定） | M5 |
| `radar config` | 打印生效配置 | M0 |
| `radar selftest` | 自检 | M0 |
全局选项写在子命令**之前**：`radar --config path config`。

---

## 诚实披露（三项风险，如实写，不粉饰）

1. **同类多且低星**：GitHub 检索（基准日 2026-10-17，软论据）`AI coding agent conflict` → 130 个结果，头部 65★ / 46★ / 31★。**需求存在，但用户愿不愿给星/付费未被验证**——这是本题最大风险。
2. **符号级已被口头占位**：`amaar-mc/wit` 的 README 原文写着 "Lock symbols. Detect conflicts before code is written"（46★，一天后停更）。**本题不宣称首创**；差异化只押"会话进行中的实时符号区间比对 + worktree 拓扑 + 可复现冲突矩阵三者同时覆盖"。
3. **本机真实并行冲突样本几乎为零**：同文件重叠 **0 对**（详见上文与本仓 `data/README.md`）。因此任何检出率/准确率口径的分母**都来自合成基准**，本 README 不用真实样本数包装准确率。

**反方观点（一并写入，不挑证据）**：如果每个 agent 都在独立 worktree 且最终走人工合并，冲突确实会在合并时被 git 拦下（HN item 47626971）。**本工具的价值是"提前量"（省返工、省覆盖损失），不是安全边界**——它不能让错误的合并变正确，也不能防止所有覆盖。

---

## 隐私

* **纯本地、零上传、零遥测、不联网**：无网络调用路径（CI 侧有导入面审计）。
* 会话日志含 prompt 与代码 → 检测链路**只抽结构化字段**（工作目录 / 分支 / 时间戳 / 文件路径 / 改动片段），**不落 prompt 正文**；证据只记 `文件:行号`。
* **真实日志、真实路径清单、真实 session id 一律不入仓**；公开仓库只含合成场景（白名单：假项目名 `demo-radar-alpha`/`demo-radar-beta`、假 session id `sess-radar-NNNN`、假用户名 `radar-user`、固定基准时间 `2026-01-01T00:00:00Z`）。
* 输出只写你指定的 `--out-dir`（默认不落盘，只打 stdout）：`scan.json` / `intent.json` / `conflicts.json` / `report.md`。**不给 `--out-dir` 时零写盘**（有测试断言 CWD 里一个文件都不落）。

**判定为辅助参考，处置由你决定**：本工具不合并、不解决冲突、不接管编排。

---

## 已知环境问题

* **配置文件解析用自写受限 TOML 子集解析器**（项目底线 Python 3.8 没有 `tomllib`）。支持：注释、`[section]`、`key = 整数/浮点/布尔/带引号字符串/标量数组`。**不支持**：表数组 `[[...]]`、内联表 `{...}`、多行字符串、点号键——遇到即在**报错信息里点名行号**（不静默跳过）。
* **`radar bench` 默认在仓库根的 `bench/` 找合成矩阵**；源码包/解包后目录不同时请显式传 `--bench-dir`。默认把 `last_run.json` 落回**矩阵目录**（给 `--out-dir` 则落那里）。
* **Windows 路径**：一律用参数传路径，不要依赖 shell 的 `~` 展开（Git Bash 的 `~` 与 Windows Python 不互通）；`~` 解不出主目录时本工具**显式报错**，不会在当前位置创建名为 `~` 的目录。
* **`radar` 与 `python -m agent_conflict_radar` 是两条通路**（`sys.path` 来源不同）：前者要求已安装，后者在源码态配 `PYTHONPATH=src` 也可跑。CI 对两条都冒烟。

---

## 开发与测试

```bash
python -m pytest -q                 # 全量测试
python tools/verify_offline.py      # 离线冒烟（CI 与本地共用同一条通路）
python tools/verify_offline.py --strict   # console script 缺失即失败（CI 用）
python tools/verify_mutation.py     # 守门变异验证（新增/改写守门后必跑）
```

合成矩阵的自检与重建：生成器在**包内**，不是 `radar` 子命令（所以不列进上面的"命令总表"，
也不参与 README↔CLI 指令面对账）——`python -m agent_conflict_radar.bench.gen --check` 做两层自检
（CI 每棒必跑），`python -m agent_conflict_radar.bench.gen --out bench` 在改生成器/体例后整目录重建，
`--materialize <id> --dest <dir>` 把某条场景物化成真 git 仓库（供 M2/M3 用）。

CI：`.github/workflows/ci.yml`，四矩阵 `windows/ubuntu × Python 3.8/3.12`（每腿依次跑全量测试 → 矩阵自检 → 离线冒烟）。

### 发布终态自检（`scripts/check_release.py`，**刻意不进 CI**）

```bash
python scripts/check_release.py            # 离线 C01–C11：工作树/产物/名字四向/退出码/矩阵/脱敏/MANIFEST/真建 sdist/解包即用
python scripts/check_release.py --online --tag v0.0.1   # 在线 O01–O07：公开/tag 指向/CI 逐 job/附件集合/逐个下载复算 sha256/附件与 tag 树同源
python scripts/check_release.py --mutation # 门自身变异验证：检查项数 == 变异组数
```

为什么不在 CI：它判的是"发布这件事做完了没有"（仓库公开、tag、CI 已绿、附件已传），这些状态
只在发布时才存在——放进 CI 只能被跳过或被放宽，那就是假门。退出码沿用 `0/1/2/3`，不新增第五个码。

**计划文档**（读完 README 想知道"为什么这么设计"就看这里）：

| 文档 | 内容 |
|---|---|
| [`plan/00-README总览.md`](plan/00-README总览.md) | 文档索引 / 决策记录 / 承诺-证据台账 / 里程碑 |
| [`plan/01-题目文档.md`](plan/01-题目文档.md) | 项目题全文（痛点证据、四级粒度、评分标准、边界） |
| [`plan/02-需求解读.md`](plan/02-需求解读.md) | 痛点→能力转译、FR 清单、用户旅程、验收口径 |
| [`plan/03-架构与技术选型.md`](plan/03-架构与技术选型.md) | 分层、数据流、模块接口、目录结构、风险对策 |
| [`plan/04-模块详设.md`](plan/04-模块详设.md) | M1–M5 逐模块输入/输出/算法/确定性纪律 |
| [`plan/05-数据计划.md`](plan/05-数据计划.md) | 合成矩阵格式、植入真值语义、覆盖度门槛 |
| [`plan/06-里程碑.md`](plan/06-里程碑.md) | M1–M6 目标 / 任务 / DoD / 降级策略 |
| [`plan/RELEASE-M6.md`](plan/RELEASE-M6.md) | 发布留档：坐标 / 发布门判据 / 源码包边界 / 步骤顺序 / DoD 三件套 / tag 后追加事实 |
| [`plan/07-交付对标与决策记录.md`](plan/07-交付对标与决策记录.md) | 材料与评分对标、决策记录、既定口径 K 清单 |
| [`docs/技术报告.md`](docs/技术报告.md) | 技术报告：归集口径 / 试合并边界 / AST 符号方法 / 严重度 / 隐私 / 基准可复现性 |
| [`data/README.md`](data/README.md) | 依据查证（HN 原话 + 检索式）、本机实测、合成数据纪律 |

---

## 许可

MIT，见 [`LICENSE`](LICENSE)。署名 `yuluo554`。
