# data/ 数据台账

**基准日**：2026-10-17（出题阶段查证与本机数据源实测）
**纪律**：**未核对字段语义不得落库 / 不得进入检测路径**；数值口径只在 `config/radar.toml` 一处定义；题面不写会漂移的硬数字；数据源条数为**本机实测快照**（附基准日），**非交付承诺**。

---

## 一、依据查证记录（逐条三态 + 来源 + 基准日）

### 1.1 痛点证据（HN 原话，✅ 已核对）

| 依据 | 三态 | 原话 / 说明与来源 |
|---|---|---|
| HN item 47324913 | ✅ **原话已核对**（提交显示 `[dead]`，如实标注） | 原话：*"Been running multiple Claude Code instances on the same repo ... it works great until two agents end up touching the same file — **one quietly undoes the other's work** and you don't notice until merge time."* https://news.ycombinator.com/item?id=47324913 |
| HN item 48238822 | ✅ **原话已核对** | 原话：*"one issue I've seen with other tools doing worktree stuff is they **don't deal with merge conflicts automatically**."*（Superset, YC P26）https://news.ycombinator.com/item?id=48238822 |
| HN item 47289444 | ✅ **原话已核对** | 原话：*"**Duplicate work**: two agents would claim the same task when there was no locking."* https://news.ycombinator.com/item?id=47289444 |
| HN item 47626971（**反方**） | ✅ **原话已核对** | 原话：*"Each agent runs in a separate worktree ... The issue you mentioned gets caught during merge conflicts. No different than a 'real' dev team?"* https://news.ycombinator.com/item?id=47626971 |

> 引用纪律：以上四条为**逐字原话**，可直接引用；三条支持"存在公开抱怨"，一条（反方）**反对"这是新问题"**——四条一并写进题面，**不得只挑有利证据**。四条均**不支撑**任何数值结论。

### 1.2 开源现状检索（5 条检索式，⬜ 软论据；wit 占位为 ✅）

**检索渠道**：GitHub Search API（`api.github.com/search/repositories`），**基准日 2026-10-17**。
**论据强度声明**：星数 / 更新时间 / total_count 为**软论据 ⬜**——有检索式、有基准日、有 API 计数，但**无入库截图**，且**会随时间漂移**；不得与"原话直连核对"并列作硬锚点。

| # | 检索式 | total_count | 命中最相关项 | 判定 |
|---|---|---|---|---|
| 1 | `AI coding agent conflict` | **130** | `clash-sh/clash` **65★**（2026-02 建、2026-07 最后推送）；`amaar-mc/wit` **46★**（一天就停更）；`relayBrain` **31★** | **低星混战**，非空白 |
| 2 | `claude code worktree parallel agents` | **250** | `pro-workflow` **2917★**、`genie` **345★**、`vibe-tree` **268★** | 均为**编排器**，不做冲突检测 |
| 3 | `worktree merge conflict` | **28** | `clash` **65★** 居首 | 文件级已有直接竞争 |
| 4 | `parallel agents file conflict detection` | **1** | `claude-foreman` **1★** | 文件级几乎无人做深 |
| 5 | `symbol lock multi agent file` | **0** | —（但 `wit` 已口头占位） | 检索为空，不代表无人 |

**关键事实（✅ 原话已核对）**：`amaar-mc/wit` 的 README 已声明 **"Lock symbols. Detect conflicts before code is written"**——符号级 + 写前检测**已被口头占位**。虽然该仓库 46★ 且一天就停更，本题**不得宣称首创**。

**判定**：不是空白，是"**低星混战中的符号级缝隙**"。低星普遍说明**需求存在、但付费/star 意愿未验证**——这是本题最大风险，题面 §1.4 与 plan/00 决策记录已显著记录。

### 1.3 品牌隔离声明

本题文档只描述"多 agent 并行写入冲突"问题域；同系列其他项目的名称与业务领域**不在本题文档、README、代码注释中出现**，也不复用其代码。

---

## 二、数据源可获取性记录（本机当场实测）

**⚠️ 路径自适应声明**：以下路径为**本机实测**。用户本机路径因用户名、安装方式、agent 版本而异——工具**必须自适应发现**（`--repo` / `--claude-root` / `--codex-root` / 环境变量 / 常见位置探测），**不得硬编码用户名或绝对路径**；找不到源时显式报错，**不得伪造空结果**（不得退化为 exit 0）。

### 2.1 会话源（✅ 本机实测，2026-10-17）

| 项 | 实测结果 |
|---|---|
| Claude Code 会话 | `~/.claude/projects/**/*.jsonl`，**94 个会话**全部带 `cwd` + `gitBranch` |
| Codex 会话 | `~/.codex/sessions/**/*.jsonl`，**220 个会话**，`session_meta.payload.cwd` **全覆盖** |
| 时间窗可得性 | 两边会话行均带时间戳 → 可按时间窗求交集 |
| 独立会话 vs subagent | 会话内 parent/child 关系可识别：309 对时间重叠中 **63 个是独立会话**，其余为 subagent |

### 2.2 并行冲突实况（✅ 本机实测；**样本为 0，这是本题最重要的诚实披露**）

| 项 | 实测结果 |
|---|---|
| 按 `cwd` + 时间段求交集 | **309 对**时间重叠会话 |
| 独立会话重叠 | **22 对** |
| **同文件重叠** | **0 对** |
| 唯一 3 例"同文件重叠" | 全部来自同一 parent 派生的 subagent（某本机 Codex 项目下的 service / web / judge 三个 thread_spawn；**项目绝对路径不入仓**）——**本质是自己和自己并行** |
| worktree 现状 | `git worktree list` 只有 **1 个 worktree** |
| git 关联 | 会改文件的 **37 个会话中只有 7 个位于 git 仓库内** |

> **结论（必须原样保留）**：真实单机并行冲突样本**几乎为零**。本题的**验收主体是合成冲突矩阵 + 植入真值**；真实数据只作可行性说明与演示。**不得**用真实样本数包装"检出率"或"需求已验证"。

### 2.3 git 命令与技术路径可用性（✅ 已核对命令形态）

| 能力 | 命令 | 用途 | 只读性 |
|---|---|---|---|
| worktree 枚举 | `git worktree list --porcelain` | 取主工作区与各 worktree 路径/HEAD/分支 | 只读 |
| 无副作用试合并 | `git merge-tree --write-tree <base> <other>` | 取冲突路径与冲突块 | 只读（写对象库临时树，不改工作区/索引） |
| 未提交变更 | `git status --porcelain`、`git diff`、`git diff --cached` | 意图提取与磁盘核对 | 只读 |
| 符号区间 | Python 标准库 `ast`（`FunctionDef` / `AsyncFunctionDef` / `ClassDef` 的 `lineno` / `end_lineno` / 限定名） | 符号级冲突比对 | 只读 |

> **边界**：`merge-tree` 的 `--write-tree` 会在对象库写入临时 tree 对象（不改索引、不改工作区）；首期需在报告中说明这一点，**不得**声称"零任何写入"。无法试合并（缺共同祖先等）时降级为文件级并标 `degraded`。

### 2.4 渠道坑与实测教训（预登记，M1 复核）

- **Windows 路径两套写法**：Git Bash 下 `~` 展开为 `/c/Users/...`，Windows Python 不认 → 脚本内一律 `os.path.expanduser` + `pathlib`，**不得把 shell 展开结果传给 Python**；
- **worktree 路径可能是相对路径或含空格**：`--porcelain` 输出需按行解析，不得用空格切分；
- **同一 parent 的 subagent 不算独立 agent**：必须用 `derived_from` 去重，否则会把"自己和自己"误报为冲突（本机 3 例即为该形态）；
- **git 仓库外会话占多数**（37 中 30 个不在 git 内）：检测器必须显式处理"非 git 工作区"，不得崩溃或伪造冲突；
- **JSONL 可能含超长单行**：逐行读取设行长上限并显式报错。

---

## 三、合成数据纪律

**总则**：基准与演示一律使用**合成的 git 仓库 + 合成会话日志**；**零真实项目、零真实路径、零真实用户名、零真实 session id**。

1. **白名单登记**（假值统一登记，禁止真实值入库）：
   - 假项目名：`demo-radar-alpha` / `demo-radar-beta`（禁真实项目名、真实仓库名）；
   - 假包名：`demo_radar_alpha` / `demo_radar_beta`（禁真实包名、真实域名反写）；
   - 假文件路径：`demo-radar-alpha/src/alpha.py`、`demo-radar-beta/pkg/beta.py`；
   - **合成仓库内的相对路径（M1 追加）**：`src/alpha.py`（主场景文件）、`src/beta.py`（负样本里"另一侧改的文件"）、
     `src/filler.py`（rng 生成的**噪声**文件，两个会话都不碰它——让"不误报无关文件"有实物可打）；
   - **会话根占位符（M1 追加）**：`{{REPO_ROOT}}`，冻结产物里代表"被物化的合成仓库根"，物化时替换为本机路径
     （冻结产物**不得**登记本机绝对路径：那会让"在别人电脑上 `--check` 必红"，属环境依赖事实）；
   - **假 author（M1 追加）**：`radar-user` / `radar-user@example.invalid`（git 提交的固定署名，保 sha 可复算）；
   - 假 session id：`sess-radar-0001` 起的固定序列（M1 用到 `sess-radar-0001`–`0015`，跨场景连续分配；**禁**真实 UUID）；
   - 假用户名：`radar-user`（禁真实用户名）；
   - 假分支：`feat/agent-a`、`feat/agent-b`；
   - 假时间戳：固定基准 `2026-01-01T00:00:00Z` 起的确定偏移（禁真实会话时间）。
2. **植入真值（程序化标注）**：场景生成器在造样例时**同步写出**真值文件（`*.truth.json`）——每组场景声明"应检出的粒度 `level`、对象（文件/符号）、涉及会话对、不应报出的对象"。**真值不得事后人工补**。
3. **冲突矩阵覆盖（首期最低覆盖项，口径写进 `bench/manifest.json` 的 `coverage.min_count_by_type`）**：
   - `same_file_diff_symbol`：同文件不同函数 → 期望文件级冲突，符号级不报同一符号；
   - `same_symbol_diff_lines`：同函数不同行 → 期望符号级冲突 + 行区间；
   - `whole_file_overwrite`：一侧整文件 `Write`、一侧局部 `Edit` → 期望文件级 + 符号级（被覆盖符号）；
   - `subagent_derived`：同一 parent 的 subagent 并行 → 默认不报跨 agent 冲突（标注 `derived_from`）；
   - `negative_no_overlap`：不同文件 / 时间窗不重叠 → **空检出**（防误报）；
   - `threshold_adjacent`：同文件改动间隔大于阈值 → 按配置判定（测阈值口径）。
4. **合成日志形态**：Claude 侧仿 `cwd` / `gitBranch` / `message.content[]` + `tool_use`；Codex 侧仿 `session_meta.payload.cwd` / `payload.type` + `*** Begin Patch`；**字段名与本机实测一致**，值全部为白名单假值。
5. **冻结与可审计**：生成器与真值标注入仓；样例可一条命令重建（`--check` 位级一致）；样例体积控制在仓库友好范围。
6. **不落真实日志**：`.gitignore` 已屏蔽 `sessions/` / `exports/` / `_real_logs/`；任何从本机日志导出的中间件不得入库。

---

## 四、数值口径纪律

- **唯一权威位置**：`config/radar.toml`（M1 落定文件名；若改名，全仓只改这一处并记入决策记录）；
- **活跃时间窗**：会话被判定为"活跃"的时间跨度（口径在配置文件；题面不复制数值）；
- **严重度权重与排序**：同一符号被两侧修改 > 同文件不同符号 > 行区间相邻 > 仅文件级同改；
- **符号重叠阈值**：判定"重叠/相邻"的行数口径与阈值；
- **禁止第二份数值表**：README、技术报告、基准输出、题面一律**引用**，不得复制一份数值列表；报告里的展示值必须从配置读取后渲染；
- **题面不写会漂移的硬数字**（测试数 / 检出率分母 / 文件数 / 体积）；数据源条数为**本机实测快照**（附基准日 2026-10-17）。

---

## 五、待核对项闭环表

> **M1 只读探针实测（2026-10-17）**：R1 / R2 / R3 已闭环，明细见下方 §六。探针为只读脚本，
> 只打印**字段名与计数**，未打印任何 prompt 正文或真实路径；探针脚本本身不入仓（避免携带本机绝对路径）。

| # | 项 | 状态 | 闭环里程碑 |
|---|---|---|---|
| R1 | `git merge-tree --write-tree` 在"无共同祖先 / 单 commit 仓库"下的输出形态与退出码 | ✅ **已闭环**（见 §六 6.1） | M1 |
| R2 | Codex `apply_patch` 载荷内文件路径字段形态 | ✅ **已闭环**（见 §六 6.2） | M1 |
| R3 | Claude `MultiEdit` 字段形态（本机是否出现？`edits[]` 结构？） | ✅ **已闭环**：本机 **0 次**出现（见 §六 6.3） | M1 |
| R4 | 非 Python 文件的符号级降级口径（行区间近似） | ⬜ 待核对 | M2 |
| R5 | 冲突矩阵覆盖度门槛具体数值 | ✅ **已闭环**：门槛值落在 `bench/manifest.json` 的 `coverage.min_count_by_type`（六类各 ≥1），并附 `count_by_type` / `missing_types` / 阈值成对样例声明；`--check` 断言三者自洽 | M1 |
| R6 | 本机并行样本快照是否随复核变化 | 🔶 **M1 复核**：Claude 125 个会话文件 / Codex 220 个，与题面基准日快照一致（题面 94 为"带 cwd 的会话数"，本次按文件数计，口径不同不矛盾）。**追加发现**：3 个 Claude journal 文件只有元信息行 → 落 `undetermined(no_message_line)` 而不是静默丢弃 | M1 |

> **纪律**：R4 未闭环前，非 Python 文件的符号级一律落 `approximate=True` 且**不给符号名**，
> 不得作为"已支持"对外宣称。R1–R3 的闭环结论已三处同步：`versions.py` / `plan/04` / `plan/07` 决策记录。
>
> **R1–R3 在 M1 收尾新增的落点**：三条结论都**钉进了合成矩阵**——冻结的会话日志复现了实测形态
> （Claude 首行不带 `message`、Codex 首行恒为 `session_meta`、Codex 子会话无 `session_id`），
> 每条场景的 `git_expected_merge_exit` 由 `--check` **现场真跑 `merge-tree`** 复核。
> 即："我们按实测形态解析"这句话现在有可复跑的实物支撑（`tests/test_bench_matrix.py`）。

---

## 六、M1 只读探针实测记录（2026-10-17）

> 本节是**会话解析与冲突检测的全部字段依据**。凡进入检测路径的字段都在这里登记过
> （对应"未核对字段语义不得落库、不得进入检测路径"的上游纪律）。

### 6.1 R1：`git merge-tree --write-tree` 的形态矩阵（✅ 已闭环）

在临时仓库里实测（未触碰本仓库），git `2.54.0.windows.1`：

| 构造 | 退出码 | stdout 形态 | 只读性 |
|---|---|---|---|
| 两侧改同文件同一行（真冲突） | **1** | 第 1 行 = 合并后 tree sha；随后 `100644 <sha> <stage> <path>` 三元组（stage 1=base / 2=ours / 3=theirs）；空行；`Auto-merging <path>` 与 `CONFLICT (content): Merge conflict in <path>` | 工作区与索引**未变**（`status --porcelain` 为空、当前分支不变） |
| 单 commit 仓库、两侧同一 ref | 0 | 只有 tree sha 一行 | 只读 |
| 两侧改同文件**不同函数** | 0 | 只有 tree sha（git 自动合并成功，**不报冲突**） | 只读 |
| 两侧改同文件**同一函数内相隔 3~5 行** | **0** | 只有 tree sha（**git 静默自动合并**） | 只读 |
| 两侧改同文件**相邻行** | 1 | 同"真冲突"形态 | 只读 |
| 整文件覆盖 vs 局部 Edit（同区域） | 1 | 同"真冲突"形态 | 只读 |
| 无共同祖先（孤儿分支） | **128** | `fatal: refusing to merge unrelated histories` | 只读 |
| 非 git 目录 | **128** | `fatal: not a git repository (or any of the parent directories): .git` | 只读 |

**三条对设计的硬约束**：

1. **exit 1 = 有冲突 / exit 0 = 自动合并成功 / exit 128 = 环境或仓库形态问题**。128 一律落
   `degraded`（区块级降级为文件级），**绝不**当成"无冲突"。
2. **区块级只在 git 自动合并失败时才报**。于是"同文件不同函数"和"同一函数内相隔数行"这两种形态
   **git 是绿的**——这正是本题的价值窗口：**符号级必须把 git 认为没问题的形态也标出来**。
   合成基准场景 1/2 的期望据此确定（见 `plan/05` §4.2 与 `bench/` 真值）。
3. 只读性已实测：跑完 `status --porcelain` 为空、当前分支未变。`--write-tree` 只写对象库临时对象，
   **不改索引、不改工作区**（报告中不得声称"零任何写入"，这条边界已在 `plan/03` 记录）。

### 6.2 R2：Codex `apply_patch` 形态（✅ 已闭环）

* 承载位置：`response_item` 行的 `payload`，`payload.type == "custom_tool_call"`、`payload.name == "apply_patch"`。
* `payload.input` 是**字符串**（不是结构化对象），以 `*** Begin Patch` 开头，内含
  `*** Update File: <path>` / `*** Add File: <path>` / `*** Delete File: <path>` 指令行。
* 实测计数（全量 220 文件）：`apply_patch` 出现 2020 处、`*** Begin Patch` 1486、`*** Update File:` 1119、
  `*** Add File:` 478、`*** Delete File:` 95。
* **同族第二形态**：大量 patch 经 `custom_tool_call/exec`（1560 次）以 shell 文本下发，标记同形。
  M2 按"只认结构位"处理：优先认 `name == "apply_patch"` 的专用调用，`exec` 内嵌 patch 作第二种形态，
  **两种形态都要有正例与反例**；认不出的落 `unknown` 并计注记。

### 6.3 R3：Claude `MultiEdit`（✅ 已闭环：本机 0 次出现）

* 实测写类工具调用：`Edit` 263 次、`Write` 128 次、**`MultiEdit` 0 次**。
* `Edit` 的 `input` 键：`file_path` / `old_string` / `new_string` / `replace_all`（263/263 齐）。
* `Write` 的 `input` 键：`file_path` / `content`。
* 处置：按"本机 0 次出现的字段形态同样不编造"纪律，M2 对 `MultiEdit` 走**保守降级**——
  known-name 占位、出现即落 `unknown` 并计注记，**不得**假装支持。
* 旁证（M2 可用但**不作主依据**）：`toolUseResult` 带 `filePath`(299) / `structuredPatch`(299) /
  `originalFile`(299)，但这些在**工具结果行**上、不在调用行上。

### 6.4 会话文件与派生关系（G-1 / G-2 / G-3 / G-7 实测）

| 项 | Claude Code（125 文件） | Codex（220 文件） |
|---|---|---|
| 判别键（顶层） | `message` | `payload` |
| **首行是否消息行** | **否**：首行 `type` 实测为 `last-prompt`(58) / `queue-operation`(36) / `user`(28) / `started`(3) → **必须向下找第一条带判别键的行** | **是**：首行恒为 `session_meta`（220/220） |
| 工作目录 | 逐行顶层 `cwd`（承载于 assistant / user / attachment / system 行） | `session_meta.payload.cwd`（**220/220 全覆盖**） |
| 分支 | 逐行顶层 `gitBranch` | 无该字段 |
| 会话标识 | `sessionId`（每文件恒 1 值，122/125 满足） | `payload.session_id`（仅主会话，63/220）→ 子会话取 `payload.id`(220/220) |
| 时间戳 | 逐行顶层 `timestamp` | 逐行顶层 `timestamp`（末行 50/50 抽样可得） |
| **subagent 标记** | `isSidechain` 布尔、**按文件一致**（94 全 False / 28 全 True / 3 无该键且无消息行） | 含 `payload.parent_thread_id` 即为子会话（157 个文件） |
| **派生关系** | 28 个 sidechain 文件**全部**与某主文件共享 `sessionId` → 父 = 同 sessionId 下 `isSidechain=False` 的那只文件 | `payload.parent_thread_id`；157/157 **全部**指向本机另一文件的 `session_id` |
| 其它可用键 | `uuid` / `parentUuid` / `version` / `type` / `toolUseResult` | `agent_nickname` / `agent_path` / `forked_from_id`(152) / `multi_agent_version` / `runtime_workspace_roots`(6) |

**由实测推出的两条设计决定**（已写入 `plan/04` 与 `plan/07` 决策记录）：

1. **归属判别不能只看首行**（Claude 首行多为元信息行）：判别 = 向下找第一条含判别键的行，
   并把该行的**源行号**作为 `seq`。
2. **会话唯一标识不能用 `sessionId`**：Claude 主/子文件共享同一 `sessionId`，Codex 子会话干脆
   没有 `session_id`。改用 `session_key = "<source>:<相对路径>"`（由输入唯一确定、可复算），
   `derived_from` 指向父会话的 `session_key`。

### 6.5 合成矩阵的落盘形态（M1 收尾，2026-10-17）

`bench/` 是**冻结数据**（生成物，禁手改），台账在 `bench/manifest.json`。三条落盘决定都来自实测：

| 决定 | 内容 | 依据 |
|---|---|---|
| **只冻基线文本，不冻 `.git`** | `scenarios/<id>/repo/` 放合成仓库的基线源码；`.git` 不入仓 | `.git` 内部字节随 zlib/git 版本与随机化临时名漂，纳入"逐字节比对"会让 CI 四腿同点全红 |
| **提交可复现改用 sha 复算** | 真值里记 `repo_shas`（base + 各分支）；`--check` 重新物化并复算 sha | sha 只由内容 + 固定元数据决定，跨平台稳定（比"比对 .git 字节"更强也更可靠） |
| **机器无关** | 会话日志里的会话根写占位符 `{{REPO_ROOT}}`；`--check` 常驻断言冻结产物里零绝对路径 | 冻进本机路径 = 登记环境依赖事实 → 别人电脑上 `--check` 必红 |

**每条场景的 git 行为（现场真跑复核，不是抄来的）**：

| 场景 | merge-tree exit | 含义 |
|---|---|---|
| `same_file_diff_symbol` | 0 | 不同函数 → git 自动合并成功；**区块级不得报**，价值在符号级 |
| `same_symbol_diff_lines` | 0 | 同函数相隔 6 行 → git 静默合并；**这正是符号级的价值窗口** |
| `whole_file_overwrite` | 1 | 同区域真冲突 → 区块级必须报 |
| `subagent_derived` | 0 | 几何同场景 2，但两侧同一 parent 派生 → 一条都不报（靠 `derived_from` 认定，不是靠几何） |
| `negative_no_overlap` | 0 | 不同文件 → 空检出（防误报主力用例；仓库里另有 rng 生成的噪声文件 `src/filler.py`） |
| `threshold_exact` | 0 | 不同符号、间距**恰等于** `symbol.adjacent_tolerance` → 命中相邻符号 |
| `threshold_near_miss` | 0 | 间距 = 容差 + 1 → **不命中**（与上一条成对卡在边界两侧） |

> 复跑命令：`py -X utf8 -m agent_conflict_radar.bench.gen --check`
> （两层断言 + 提交 sha 复算 + 上表的 merge-tree exit 现场复核）。
