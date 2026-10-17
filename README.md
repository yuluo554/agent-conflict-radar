# agent-conflict-radar · 多 agent 并行开发冲突雷达

**多个 agent 并行改同一个仓库时，冲突往往在合并那一刻才暴露——而那时一个 agent 已经悄悄覆盖了另一个的工作。本工具在写入发生前预警**：按 worktree / 会话 / 文件 / 函数符号四个粒度比对"谁正在改什么"，给出即将冲突的清单。

纯本地 Python CLI · 只读 · 零上传 · 零第三方运行时依赖。

---

## ⚠️ 当前状态：M0 骨架期（2026-10-17）

**这不是一个完成品。** 骨架已可安装、可运行、门禁齐备，但检测能力尚未落地：

| 命令 | 状态 | 计划里程碑 |
|---|---|---|
| `radar config` | ✅ 已交付 | M0 |
| `radar selftest` | ✅ 已交付 | M0 |
| `radar scan` | ⬜ 未交付（exit 4 显式拦截） | M1 |
| `radar intent` | ⬜ 未交付（exit 4） | M2 |
| `radar detect` | ⬜ 未交付（exit 4） | M3 |
| `radar report` | ⬜ 未交付（exit 4） | M4 |
| `radar bench` | ⬜ 未交付（exit 4） | M5 |

未交付的命令**显式报错并退出码 4**，**不会**返回空结果冒充"没有冲突"——把"没检查过"读成"没问题"，对判定类工具是最严重的失真。

进度与逐棒 DoD 见 [`plan/06-里程碑.md`](plan/06-里程碑.md)；下一棒交接见 [`plan/HANDOFF-M1.md`](plan/HANDOFF-M1.md)。

---

## 三分钟上手

```bash
# 1) 安装（零运行时依赖，秒装；dev extra 只含测试期依赖）
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

### 合成场景演示（M5 交付后）

```bash
radar bench                                   # 跑合成冲突矩阵并对账真值
radar bench --only same_symbol_diff_lines      # 只跑指定场景
radar bench --bench-dir bench --out-dir out    # 显式指定矩阵目录与产物目录
```

### 本机只读演示（M1/M3 交付后）

```bash
# 工作区与会话发现（会话根默认按常见位置探测；也可显式传）
radar scan --repo .
radar scan --repo . --claude-root <你的会话根> --codex-root <你的会话根>

# 意图 → 三级检测 → 报告
radar intent --repo .
radar detect --repo .
radar report --repo . --out-dir out --format both
```

> 真实本机数据只作**可行性演示与人工抽验**：本机实测（基准日 2026-10-17）309 对时间重叠会话、63 个独立会话、独立重叠 22 对，而**同文件重叠 0 对**——真实并行冲突样本几乎为零。因此检出能力**只能由合成矩阵断言**（见下方"诚实披露"）。

---

## 四级粒度

| 级别 | 判据 | 证据 |
|---|---|---|
| **文件级** | 同一文件在两个**活跃**工作区/会话中被修改 | 各会话最后写入时间 |
| **区块级** | `git merge-tree --write-tree` **无副作用试合并**后的冲突块 | 冲突路径与冲突块（HF 形态） |
| **符号级** | Python `ast` 取函数/类/方法的限定名与行区间，两侧改动落在**同一或相邻符号** | 符号限定名 + 重叠/相邻行区间 |
| **会话/工作区级** | 归集"活跃 agent × 工作区 × 时间窗"表，subagent 标 `derived_from` 去重 | 会话文件 + 源行号 |

**只读边界**：`--write-tree` 会在对象库写入临时 tree/blob 对象（**不改索引、不改工作区、不建分支**）。本工具**绝不**执行 merge/rebase、绝不写 git 索引、绝不修改你的代码。

---

## 退出码语义

| 码 | 语义 |
|---|---|
| `0` | 无冲突 |
| `1` | 有冲突 |
| `2` | 用法错误（未知子命令 / 缺必填参数 / 未知 `--format` / 路径不存在） |
| `3` | 依赖或环境缺失（git 不可用 / 配置缺失或不可解析 / 会话源不存在） |
| `4` | 阶段未就绪（**骨架期专用**，随模块落地逐项退役） |

> 退出码非 0 **不一定**是跑挂：`detect` 对存在冲突的仓库返回 `1` 是**既定语义**，不是故障。

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
| `radar bench` | 合成冲突矩阵 + 植入真值对账 | M5 |
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
* 输出只写你指定的 `--out-dir`（默认当前目录），只写 `report.md` / `conflicts.json`。

**判定为辅助参考，处置由你决定**：本工具不合并、不解决冲突、不接管编排。

---

## 已知环境问题

* **配置文件解析用自写受限 TOML 子集解析器**（项目底线 Python 3.8 没有 `tomllib`）。支持：注释、`[section]`、`key = 整数/浮点/布尔/带引号字符串/标量数组`。**不支持**：表数组 `[[...]]`、内联表 `{...}`、多行字符串、点号键——遇到即在**报错信息里点名行号**（不静默跳过）。
* **`radar bench` 默认在仓库根的 `bench/` 找合成矩阵**；源码包/解包后目录不同时请显式传 `--bench-dir`。
* **Windows 路径**：一律用参数传路径，不要依赖 shell 的 `~` 展开（Git Bash 的 `~` 与 Windows Python 不互通）；`~` 解不出主目录时本工具**显式报错**，不会在当前位置创建名为 `~` 的目录。
* **`radar` 与 `python -m agent_conflict_radar` 是两条通路**（`sys.path` 来源不同）：前者要求已安装，后者在源码态配 `PYTHONPATH=src` 也可跑。CI 对两条都冒烟。

---

## 开发与测试

```bash
python -m pytest -q                 # 全量测试
python tools/verify_offline.py      # 离线冒烟（CI 与本地共用同一条通路）
python tools/verify_offline.py --strict   # console script 缺失即失败（CI 用）
```

CI：`.github/workflows/ci.yml`，四矩阵 `windows/ubuntu × Python 3.8/3.12`。

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
| [`plan/07-交付对标与决策记录.md`](plan/07-交付对标与决策记录.md) | 材料与评分对标、决策记录、既定口径 K 清单 |
| [`data/README.md`](data/README.md) | 依据查证（HN 原话 + 检索式）、本机实测、合成数据纪律 |

---

## 许可

MIT，见 [`LICENSE`](LICENSE)。署名 `yuluo554`。
