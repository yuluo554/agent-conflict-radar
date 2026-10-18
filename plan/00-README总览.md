# 10-18-agent-conflict-radar 项目计划总览

**项目**：多 agent 并行开发冲突雷达（按 worktree/会话/文件/函数符号四级粒度，在写入发生前预判并行冲突；纯本地 Python CLI）
**方法论**：数据先行 + 合成冲突矩阵植入真值 + 确定性规则（零模型）+ 只读分析 + 数值口径一处定义 + 纯本地零上传
**项目系列**：同系列新题（**不参赛**，发布 GitHub **公开仓库**，署名 `yuluo554`）。**品牌隔离**：与同系列其他项目不共享代码、不互相提及业务领域；公开文档只描述本题问题域
**命名约定**：本地目录 `10-18-agent-conflict-radar`（`10-18` = 日期标签）；**GitHub 仓库名 = `agent-conflict-radar`（纯净名）**，沿用惯例 `yuluo554/<kebab-name>`；LICENSE / pyproject 署名一致
**定位宣言（v1）**：**多个 agent 并行改同一个仓库时，冲突往往在合并那一刻才暴露——而那时一个 agent 已经悄悄覆盖了另一个的工作。本工具在写入发生前预警：按 worktree/会话/文件/函数符号四个粒度比对"谁正在改什么"，给出即将冲突的清单。差异化只能押符号级：文件级冲突已有一堆低星工具，函数级与"会话正在进行中"的实时比对仍是空的。**

---

## 一、文档索引

| 文档 | 内容 | 状态 |
|---|---|---|
| [01-题目文档.md](01-题目文档.md) | 项目题全文 v1（十段式：头部/介绍/任务/材料/评分/锚点/边界） | ✅ v1 定稿 2026-10-17 |
| [00-README总览.md](00-README总览.md) | 本文件：文档索引 / 决策记录 / 承诺-证据台账 / 里程碑 / 招牌动词表 / 开工预检 | ✅ 定稿 2026-10-17 |
| [../data/README.md](../data/README.md) | 依据查证记录（HN id + 检索式 + 基准日 + 反方观点）、数据源可获取性（本机实测 + 样本为 0 的证据）、合成数据纪律、数值口径纪律 | ✅ 定稿 2026-10-17 |
| [02-需求解读.md](02-需求解读.md) | 痛点 → 能力转译、FR 清单（P0/P1/P2）、用户旅程、边界与非目标、三态判定语义、反假绿口径 | ✅ M0 定稿 2026-10-17 |
| [03-架构与技术选型.md](03-架构与技术选型.md) | 五层架构、数据流、模块接口签名、目录结构（标落盘里程碑）、技术选型理由、风险对策、确定性与隐私设计 | ✅ M0 定稿 2026-10-17 |
| [04-模块详设.md](04-模块详设.md) | M1–M5 逐模块输入/输出/算法/证据/确定性纪律/降级路径 | ✅ M0 定稿 2026-10-17 |
| [05-数据计划.md](05-数据计划.md) | 合成矩阵目录与格式、植入真值语义、覆盖度门槛、生成与冻结纪律、真实数据使用边界、R1–R6 闭环表 | ✅ M0 定稿 2026-10-17 |
| [06-里程碑.md](06-里程碑.md) | M0–M6 逐里程碑目标 / 任务 / DoD / 降级策略 / 状态回写纪律 | ✅ M0 定稿 2026-10-17 |
| [07-交付对标与决策记录.md](07-交付对标与决策记录.md) | 材料与评分逐项对标、M0 起新增决策、**既定口径 K 清单（K1–K20）**、M0 猜测待勘误表、诚实口径尾注（M1 / M2 / M3 各一节） | ✅ M0 定稿 2026-10-17，M1·M2·M3 收尾各追加勘误与决策 |
| [HANDOFF-M1.md](HANDOFF-M1.md) | 上一棒交接（M0→M1）：进度+证据 / 待办 / K 口径 / 环境坑 / DoD / 命令速查 | ✅ 已落盘 2026-10-17（M1 已按它完成，留作过程留档） |
| [HANDOFF-M2.md](HANDOFF-M2.md) | 上一棒交接（M1→M2）：进度+证据 / 待办 / K 口径 / 环境坑 / DoD / 命令速查 | ✅ 已落盘 2026-10-17（M2 已按它完成，留作过程留档） |
| [HANDOFF-M3.md](HANDOFF-M3.md) | 上一棒交接（M2→M3）：进度+证据 / 待办 / K 口径 / 环境坑 / DoD / 命令速查 | ✅ 已落盘 2026-10-18（M3 已按它完成，留作过程留档） |
| [HANDOFF-M4.md](HANDOFF-M4.md) | 上一棒交接（M3→M4）：进度+证据 / 待办 / K 口径 / 环境坑 / DoD / 命令速查 | ✅ 已落盘 2026-10-18（M4 已按它完成，留作过程留档） |
| [HANDOFF-M5.md](HANDOFF-M5.md) | 上一棒交接（M4→M5）：进度+证据 / 待办 / K 口径 / 环境坑 / DoD / 命令速查 | ✅ 已落盘 2026-10-18（M5 已按它完成，留作过程留档） |
| [HANDOFF-M6.md](HANDOFF-M6.md) | 下一棒交接（M5→M6）：进度+证据 / 待办 / K 口径 / 环境坑 / DoD / 命令速查 | ✅ M5 收尾时落盘 2026-10-18 |
| [../docs/技术报告.md](../docs/技术报告.md) | 技术报告（归集口径 / 试合并边界 / AST 方法 / 严重度口径 / 隐私设计 / 基准可复现性） | ✅ M5 落盘 2026-10-18（M6 定稿） |

> 里程碑收尾纪律沿用系列惯例：**DoD 达成后必须在本对话内写完下一棒的 `HANDOFF-M<next>.md` 才允许结束**。

---

## 二、决策记录（出题阶段）

> **弃选四项（出题阶段定案，理由见下表"弃"行）**：①自动合并 / 自动解决冲突（风险与定位冲突）；②编排器形态（已饱和）；③真实场景演示作验收（本机样本为 0）；④全 agent 工具适配入首期（会形成"名义支持"）。
> **本题风险必须显著记录，不得粉饰**：①同类多且低星（10+ 个同类，头部 clash 65★ / wit 46★ / relayBrain 31★）；②`wit` 已口头占位符号级（README 原文 "Lock symbols. Detect conflicts before code is written"）；③本机真实并行冲突样本为 0。因此**全文不写"需求已验证"**，只写"需求存在但付费/star 意愿未验证"。

| 日期 | 决策 | 结论与理由 |
|---|---|---|
| 2026-10-17 | 选题 | **多 agent 并行开发冲突雷达 v1**（不参赛，GitHub 公开仓库）：按四级粒度在写入前预判并行冲突 |
| 2026-10-17 | **风险：同类低星混战** | GitHub API（基准日 2026-10-17）`AI coding agent conflict` → 130，`clash` 65★（2026-02 建、07 最后推送）、`wit` 46★（一天停更）、`relayBrain` 31★；`worktree merge conflict` → 28（clash 居首）；`parallel agents file conflict detection` → 1（claude-foreman 1★）→ **需求存在，但用户不愿给星/付费；这是本题最大风险** |
| 2026-10-17 | **风险：符号级已被占位** | `amaar-mc/wit` README 原文："Lock symbols. Detect conflicts before code is written"（✅ 已核对）→ **不得宣称首创**；差异化只押"会话进行中的实时符号区间比对 + worktree 拓扑 + 可复现冲突矩阵" |
| 2026-10-17 | **风险：本机真实冲突样本为 0** | 本机实测（2026-10-17）：309 对时间重叠、63 个独立会话、独立重叠 22 对、**同文件重叠 0 对**；唯一 3 例同文件重叠均为同一 parent 的 subagent；`git worktree list` 仅 1 个 → **验收以合成基准为准，不承诺真实痛点已验证** |
| 2026-10-17 | 需求验证表述 | HN 四条原话（47324913 `[dead]` / 48238822 / 47289444 / **反方 47626971**）✅ 已核对 → 只支撑"存在公开抱怨"，**不支撑**"普遍痛点"或任何数值结论；反方观点一并写入题面 |
| 2026-10-17 | **弃"自动合并 / 自动解决冲突"** | 自动处置会引入正确性责任与破坏用户工作区的风险，且与"预警而非裁决"的定位冲突；只读 + 只报告 |
| 2026-10-17 | **弃"编排器"** | `claude code worktree parallel agents` → 250，头部 pro-workflow 2917★ / genie 345★ / vibe-tree 268★，编排方向已饱和；本题只做检测，不做任务分配/启停/锁服务 |
| 2026-10-17 | **弃"真实场景演示作验收"** | 本机同文件重叠 0 对，真实样本无法支撑验收 → 改为**程序化合成冲突矩阵 + 植入真值**；真实数据只作演示与人工抽验 |
| 2026-10-17 | **弃"全工具适配入首期"** | 会话格式随 harness 演进且差异大（Claude `message.content[]` vs Codex `payload.type`），首期只覆盖 Claude Code + Codex + git 工作区，其他显式列为扩展，避免"名义支持" |
| 2026-10-17 | 交付形态 | **纯本地 Python CLI**（唯一形态，无 GUI、无 exe、无服务器）；`pip install .` 后 `python -m` / console_scripts 调用；退出码四语义锁进测试 |
| 2026-10-17 | 检测技术路径 | `git worktree list --porcelain` 取 worktree；会话 `file_path` 取交集；`git merge-tree --write-tree` 做无副作用试合并；Python `ast` 解析新旧文件函数/类行区间 → **不修改工作区、不写索引** |
| 2026-10-17 | 数值口径 | 活跃时间窗、严重度权重、符号重叠行数阈值**只在 `config/radar.toml` 一处定义**；报告 / 基准 / README 一律引用 |
| 2026-10-17 | 隐私红线 | 会话含 prompt 与代码 → **纯本地零上传零遥测**；真实日志 / 真实路径清单 / 真实 session id 不入仓；公开仓库只含合成场景 |
| 2026-10-17 | 路径自适应 | `--repo` / `--claude-root` / `--codex-root` / 环境变量 / 常见位置探测；**不得硬编码用户名**；找不到源显式报错，不伪造空结果 |
| 2026-10-17 | 品牌隔离 | 不复制系列其他项目代码；公开文档不提及任何其他项目名称与业务领域；本题文档只描述"并行写入冲突"问题域 |

---

## 三、承诺-证据台账（全项目唯一一份）

> 状态列必须与里程碑同步翻转；其他文档只可引用本表，**不得复制**。

| 承诺项 | 素材来源 | 交付物内可达性 | 核验方式 | 状态 |
|---|---|---|---|---|
| M0 骨架（可安装包 + 退出码契约 + 数值单点 + 编码守卫 + 门禁与变异验证） | 纯标准库；`py -3.8` / `py -3.12` 本机实测 | 随包，零网络；`pip install -e .` 秒装 | 双解释器全量 pytest + `tools/verify_offline.py --strict`（两条通路 23 用例）+ `tools/verify_mutation.py`（10 组变异全部被检出） | ✅ M0 完成（本地等价校验；未接远端，CI 待首推验证） |
| M1 工作区与会话发现（worktree + 双 harness 会话归集） | `git worktree list --porcelain` ✅ 命令可用；Claude 125 个会话文件全带 `cwd`+`gitBranch` ✅；Codex 220 个 `session_meta.payload.cwd` 全覆盖 ✅ | 随包，零网络；路径可覆盖 | 合成场景逐字段对账 + 同输入双跑逐字节一致 + 未知格式显式报错 + `--check` 的 merge-tree 现场复核 | ✅ **M1 完成**（2026-10-17）：`radar scan` 交付（K15 四步走完）；双解释器 179 passed / 1 skipped；冒烟 25 用例；变异 16 组全检出 |
| M1 合成矩阵起步（生成器 + 植入真值 + 覆盖度台账 + 两层 `--check`） | 程序化构造七条场景（同文件异符号 / 同符号异行 / 整文件覆盖 / subagent 派生 / 负样本 / 阈值成对） | 随包零外部依赖；`bench/` 为冻结数据 | `bench/gen.py --check`：冻结产物形态 + 重生成逐字节 + 提交 sha 复算 + 七条场景的 merge-tree exit 现场复核 | ✅ **M1 完成**（2026-10-17）：`missing_types` 为空；真值可脱离引擎独立复算 |
| M2 变更意图提取（Edit/Write/apply_patch + git status/diff） | 会话内 `file_path` / `old_string` / `new_string` / `apply_patch` 文本；`git status --porcelain` + `git diff` + `git diff --cached`；`git show HEAD:<path>` 作定位基线 | 随包 | 合成会话解析对账（八条意图场景逐条一致）；无法定位时 `coarse`/`unknown` 而非猜测；同输入同输出 | ✅ **M2 完成**（2026-10-18）：`radar intent` 交付（K15 四步走完）；双解释器 248 passed / 1 skipped；冒烟 27 用例；变异 22 组全检出；R4 闭环 |
| M3 三级检测（文件 / 区块 / 符号） | `git merge-tree --write-tree` ✅；Python `ast` ✅ | 随包；git 为运行期必需（缺失 exit 3） | 合成冲突矩阵检出集合精确匹配；负样本零误报；只读断言（工作区 hash 前后一致） | ✅ **M3 完成**（2026-10-18）：`radar detect` 交付（K15 四步走完，**退出码 1 首次真正上岗**）；七条冻结场景的检出集合逐条精确匹配 + 三态各有合成用例；双解释器 299 passed / 1 skipped；冒烟 29 用例；变异 29 组全检出 |
| M4 预警报告（Markdown + JSON + 可选通知） | M3 冲突清单 | 随包 | 报告排序稳定；退出码四语义测试；通知不可用时 `notify_unavailable` 不影响主流程 | ✅ **M4 完成**（2026-10-18）：`radar report` 交付（K15 四步走完）；单一渲染源（Markdown = JSON payload 的纯函数）+ 渲染三律（零判定 AST 门禁 / 零外链常驻出口 / 双跑逐字节）+ 退出码 0/1/2/3 各有实物；双解释器 336 passed / 1 skipped；冒烟 35 用例；变异 33 组全检出 |
| M5 合成冲突矩阵 + 植入真值 + **一条命令评分** | 程序化构造场景（同文件异函数 / 同函数异行 / 整文件覆盖 / subagent 派生 / 负样本 / 阈值成对）+ 意图矩阵八条 | 随包零外部依赖 | 生成器同步标注真值；`radar bench` 逐场景物化 → 跑链路 → 集合精确匹配；覆盖度口径写 manifest 并在消费侧复核 | ✅ **M5 完成**（2026-10-18）：`radar bench` 交付（K15 四步 + K1 退役 exit 4）；整矩阵 **15/15 场景、174 项检查 0 失败**；`bench/last_run.json` 落盘（K2 + K17）；双解释器 365 passed / 1 skipped；冒烟 38 用例；变异 36 组全检出 |
| 隐私设计（纯本地零上传） | 无网络依赖 | 全链路本地 | 依赖扫描 + 断网运行 + 入库内容扫描（真实路径 / session id 零命中） | ✅ **M5 复核通过**（2026-10-18）：零网络导入面审计通过；`bench/`、`docs/`、`plan/`、README 扫描无真实盘符路径 / `/Users/` / `/home/` / Real-UUID / 真实用户名；`last_run.json` 机器无关 |
| 发布闭环（tag + Release 附产物 + 留档） | GitHub 公开仓库 | Release 附源码 zip + sha256 留档 | 仓库内耐久副本 + sha256 可复验；tag 树内含发布留档 | ⬜ 待 M6 |
| 文件监听实时模式 | 扩展项 | 不入首期 | — | ⬜ 扩展 |
| CI 前置检查 | 扩展项 | 不入首期 | — | ⬜ 扩展 |
| 更多 agent 工具适配 | 扩展项 | 不入首期 | — | ⬜ 扩展 |

---

## 四、招牌动词表（能力名词 → 交付命令 → 断言基准）

> 填不出的词不得进标题、定位宣言、README 首段或输出 schema。

| 能力名词 | 哪条交付态命令产出它 | 哪条基准/测试断言它 |
|---|---|---|
| 工作区与会话发现 | `radar scan <repo>` 输出的 `workspaces[*]` / `sessions[*]` | 合成场景对账：worktree 集合、会话 cwd/branch、subagent `derived_from` |
| 变更意图集合 | `radar intent <repo>` 输出的 `entries[*].changed_ranges` / `last_write_ts` / `writes[*]` | 意图矩阵七条场景逐条对账（含 `coarse` / `unknown` 分支）+ 三分法计数恒等式 + `tests/test_intent_parse.py` 的纯函数级用例 |
| 文件级冲突 | `radar detect <repo>` 输出 `conflicts[levels 含 file]` | 矩阵七条场景的 `levels`/`symbols` **集合精确匹配** + 负样本空检出（`tests/test_detect.py::test_scenario_detects_to_the_frozen_truth`） |
| 区块级冲突（试合并） | `radar detect` 输出 `conflicts[levels 含 block]` | 矩阵场景 3（唯一 exit 1 的那条）+ 断言 `git merge-tree` 只读（工作区/索引/HEAD 指纹前后一致） |
| 符号级冲突 | `radar detect` 输出 `conflicts[levels 含 symbol]` 的 `symbols` + `line_ranges` | 矩阵场景 2 / 3 / 6a 精确匹配（含容差边界成对用例）；负样本零误报；R4 口径另有非 Python 用例 |
| subagent 去重 | `radar detect` 对 `derived_from` 的处理 | 矩阵场景 4：默认不报跨 agent 冲突，且 `derived_sibling_pairs_skipped` 留痕 |
| 处置建议 | `radar report <repo>` 的 `report.md` | 报告按 `severity` 降序的稳定排序断言 + 建议模板按 `severity_key` 分派（`test_suggestions_are_rule_templates_keyed_by_engine_severity`）+ 单一渲染源（Markdown = payload 纯函数） |

---

## 五、里程碑（初稿）

> **数值口径**：活跃窗口 / 严重度权重 / 重叠阈值 / 超时只在 `config/radar.toml` 一处定义；题面与文档只引用。

| 里程碑 | 内容 | DoD |
|---|---|---|
| **M0 骨架**（2026-10-17 完成） | ①计划文档 02–07 落盘；②可安装骨架（`src` 布局 + 零运行时依赖 + `radar` / `python -m` 双通路）；③数值口径单点 `config/radar.toml` + 自写受限 TOML 子集解析器；④**四件前置工程**（退出码契约锁进测试 / 双解释器全量 pytest / 冻结序列化契约 / 编码守卫进入口）；⑤八组骨架门禁 + `tools/verify_offline.py` + `tools/verify_mutation.py`；⑥CI 四矩阵预置；⑦`plan/HANDOFF-M1.md` | 见 [06-里程碑.md](06-里程碑.md) M0 节。**本地等价校验结果**：`py -3.8`/`py -3.12` 各 **122 passed / 1 skipped**（跳项为"当前文件系统不支持目录符号链接"，声明式跳过并说明原因）；离线冒烟 `--strict` 两条通路 **23 用例全过**；**变异验证 10 组全部被对应守门抓到**（仓库按字节还原）。未接远端 → CI 待首推验证 |
| **M1 数据先行**（2026-10-17 完成） | ①worktree + 双 harness 会话归集（`radar scan`）；②**合成冲突场景矩阵 + 植入真值台账**（七条场景 / 六个覆盖类型）；③格式版本检测口径（显式指纹集合）；④会话字段核对记录进 `data/README` §六 | 见 [06-里程碑.md](06-里程碑.md) M1 节"收尾结论"。**本地等价校验结果**：`py -3.8`/`py -3.12` 各 **179 passed / 1 skipped**；离线冒烟 `--strict` **25 用例全过**；**变异验证 16 组**全部被对应守门抓到；`bench/gen.py --check` 两层断言 + 提交 sha 复算 + merge-tree exit 现场复核全过。未接远端 → CI 待首推验证 |
| **M2 意图提取**（2026-10-18 完成） | ①`intent.py`：Claude `Edit`/`Write`/`MultiEdit` + Codex `apply_patch`（含 `exec` 同形变体）；②三分法 `exact`/`coarse`/`unknown` + 计数恒等式；③磁盘对账（`git diff` / `git diff --cached`，磁盘是事实）；④R4 闭环（非 Python 行区间近似） | 见 [06-里程碑.md](06-里程碑.md) M2 节"收尾结论"。**本地等价校验结果**：`py -3.8`/`py -3.12` 各 **248 passed / 1 skipped**；离线冒烟 `--strict` **27 用例全过**；**变异验证 22 组**全部被对应守门抓到；`bench/gen.py --check` 两层断言 + 提交 sha 复算 + 意图矩阵脏改动现场复核全过。未接远端 → CI 待首推验证 |
| **M3 三级检测**（2026-10-18 完成） | ①`detect.py` 三级实现（文件级 = 两个活跃 `(workspace, session)` 组同改同一文件；②区块级 = 两侧分支 `git merge-tree --write-tree` 的冲突路径；③符号级 = `HEAD` 版本 AST 的同一 / 相邻符号）；④`gitio.merge_tree` 只读封装（白名单 / 超时 / 输出解析）；⑤`derived_from` 去重（场景 4）；⑥只读断言测试 | 见 [06-里程碑.md](06-里程碑.md) M3 节「收尾结论」。**本地等价校验结果**：`py -3.8`/`py -3.12` 各 **299 passed / 1 skipped**；离线冒烟 `--strict` **29 用例全过**；**变异验证 29 组**全部被对应守门抓到；七条冻结场景的 `levels` / `symbols` 集合精确匹配（多报漏报均失败），三态（`degraded` / `approximate` / `unsupported_format`）各有合成用例。**M3 未新增冻结场景、未改冻结产物**（检出对账复用 M1 冲突矩阵）。未接远端 → CI 待首推验证 |
| **M4 预警报告**（2026-10-18 完成） | ①`report.py`：Markdown + JSON **单一渲染源**（JSON = `detect` 的 `conflicts.json`，Markdown 是它的纯函数）；②严重度降序 + `(level, path, symbols)` 稳定排序；③建议是**规则模板**（按 `severity_key` 分派）；④`undetermined` 独立小节逐条列出；⑤参数来源块只引用键名（不复制数值）；⑥可选通知 + `notify_unavailable` | 见 [06-里程碑.md](06-里程碑.md) M4 节「收尾结论」。**本地等价校验结果**：`py -3.8`/`py -3.12` 各 **336 passed / 1 skipped**；离线冒烟 `--strict` **35 用例全过**（report 模块通路 5 条 + console 通路 3 条）；**变异验证 33 组**全部被对应守门抓到。渲染三律各有实物：AST 零判定门禁（含可证伪探针）/ 零外链常驻渲染出口（带 URL 的 payload 当场抛错）/ 双跑逐字节一致（真子进程）。**M4 未新增冻结场景、未改冻结产物**。未接远端 → CI 待首推验证 |
| **M5 基准与自检** | 完整冲突矩阵、覆盖度门槛、`radar bench` 一条命令评分 | 全部场景通过；`pip install .` 干净环境实跑；断网运行 |
| **M6 发布** | 发布 GitHub **公开**仓库 | **DoD 三件套**：①`git tag`；②**GitHub Release 附产物**（源码 zip，本地留副本 + **sha256 留档可复验**）；③**发布留档文件**（`plan/RELEASE-M6.md`，**在 tag 之前写好并进 tag 树**）。另：发布前跑 `scripts/check_release.py` 无 FAIL；提交面脱敏全 0（含 tag tagger 邮箱）；tag 后事实（附件 sha256 / 下载复核）作为**追加提交**分栏记录 |

**M6 DoD 口径锁定**：采用 **A) "Release 附产物"**——源码 zip 为手工上传附件，本地必须存在同名副本与 sha256 留档，**不得**以"仓库 zipball 即产物"替代。三件套缺任一项即视为发布未达成。

---

## 六、开工前预检结论（对应出题技能验收门）

- **素材可用性**：技术路径全部为本机可执行命令（`git worktree` / `git merge-tree --write-tree` / Python `ast`）；会话字段实测 ✅；**符号级已被 wit 口头占位**，题面已如实写，不称首创。
- **数据底座可获取性**：双源本机会话实测 ✅；但**真实并行冲突样本为 0**（同文件重叠 0 对），题面 §1.3/§六 与 data/README 均明写；验收主体为合成冲突矩阵。
- **交付物可达性**：纯本地 Python CLI，零网络、零随包大文件；输出只写报告与 JSON。
- **口径一致性**：所有数值只在 `config/radar.toml` 一处定义；题面不列第二份数值表。
- **交付路径 == 验收路径**：评分与 DoD 全部打在 CLI 命令（`scan` / `intent` / `detect` / `report` / `bench`）上；基准也从 CLI 入口跑。
- **招牌能力真算过**：见 §四 招牌动词表，七个能力名词均有"命令 + 断言"两格。
- **形态收敛**：唯一形态 = 纯本地 Python CLI；无 GUI / exe / Skill 多形态选项。
- **数字承诺为口径式**：不写会漂移的测试数 / 文件数 / 检出率分母；数据源条数为本机实测快照（基准日 2026-10-17），非交付承诺。
- **隐私**：真实日志、真实路径清单、真实 session id 不入仓；公开仓库只含合成场景（白名单见 data/README）。
- **风险披露**：低星混战 / wit 占位 / 本机样本为 0 三项已在 §二 决策记录与题面 §1.4 显著记录。

---

## 七、M0 收尾：诚实口径与本地等价校验

**措辞纪律（硬约束）**：本仓**没有远端**，`git push` 一次都没跑过，因此**从未出现"CI 绿"字样**，
一切 CI 类结论只写"**本地等价校验（未接远端，CI 待首推验证）**"。

**可指认的替代证据**（本机实跑，2026-10-17）：

| 等价物 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 122 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 -m pytest -q` | 122 passed / 1 skipped（退出码 0） |
| `py -3.12 tools/verify_offline.py --strict` | 23 用例全过（模块通路 + 裸 console script 通路 + 零网络导入面审计），退出码 0 |
| `py -3.8 tools/verify_offline.py --strict` | 同上，退出码 0 |
| `py -3.12 tools/verify_mutation.py` | 基线绿 + 10 组变异全部被对应守门抓到，仓库按字节还原，退出码 0 |
| `pip install -e . --no-build-isolation --no-deps`（两个解释器） | 成功；`radar` 与 `python -m agent_conflict_radar` 两条通路均可调用；安装元数据版本 `0.0.1` 与包内 `__version__` 一致 |

**"等价"的缺口（必须写清，不能笼统一句"本地等价校验通过"）**：

1. **CI 环境差异未验**：ubuntu 矩阵、runner 上的 cp1252/locale 差异、`actions/setup-python` 的
   extras 装配——本机模拟不了，**待首推验证**。已经用代码侧加固（入口编码守卫 + 子进程显式
   `encoding=` + CI `PYTHONUTF8=1`）把已知缺口堵住，但按纪律仍标注为未验。
2. **`Path.write_text(newline=)` 这类 3.10+ 陷阱本机已实测命中并被双解释器抓出**（见 HANDOFF 环境坑节），
   说明"双解释器跑一遍"确实有效；但 3.8 之外的版本（3.9/3.10/3.11）不在矩阵里，不做承诺。
3. **console script 通路的解释器归属**：本机 PATH 上的 `radar` 是 3.12 那一份（3.8 的脚本目录不在 PATH），
   所以"3.8 通道下 console 冒烟"实际由 3.12 的 console script 执行。这条差异在 HANDOFF 环境坑节
   明确记录，不假装"两版本各自验了两条通路"。

---

## 八、M1 收尾：诚实口径与本地等价校验

**措辞纪律沿用 §七（硬约束）**：本仓**仍无远端**，`git push` 一次都没跑过，因此 M1 **同样从未出现"CI 绿"字样**；
一切 CI 类结论只写"**本地等价校验（未接远端，CI 待首推验证）**"。

**可指认的替代证据**（本机实跑，2026-10-17）：

| 等价物 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 179 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 -m pytest -q` | 179 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | 25 用例全过（模块通路 + 生成器自检 + 裸 console script 通路 + 零网络导入面审计），退出码 0 |
| `py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check` | 两层断言 + 提交 sha 复算 + merge-tree exit 现场复核全过，退出码 0 |
| `py -3.12 -X utf8 tools/verify_mutation.py` | 基线绿 + **16 组**变异全部被对应守门抓到，仓库按字节还原，退出码 0 |

**M1 新增的"等价"缺口（写清，不笼统一句"本地等价校验通过"）**：

1. **CI 上的 git 差异未验**：合成矩阵的 sha 复算依赖 git 的提交对象语义（内容 + 元数据），
   理论上跨平台稳定；但 ubuntu 的 git 版本、`init.defaultBranch` 默认值等差异**未在真 CI 上验过**
   （代码侧已用 `-c` 固定 `core.autocrlf/core.filemode/gpgsign/init.defaultBranch` 并隔离
   `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM`）。待首推验证。
2. **平台换行差异只在 Windows 侧实测**：`scan.json` 的 LF 断言、冻结产物 LF 断言都在本机验过；
   ubuntu 侧预期一致但未实跑。
3. 3.8 之外的版本（3.9/3.10/3.11）不在矩阵里，不做承诺。

---

## 九、M2 收尾：诚实口径与本地等价校验

**措辞纪律沿用 §七·§八（硬约束）**：本仓**仍无远端**，`git push` 一次都没跑过，因此 M2 **同样从未出现"CI 绿"字样**；
一切 CI 类结论只写"**本地等价校验（未接远端，CI 待首推验证）**"。

**可指认的替代证据**（本机实跑，2026-10-18）：

| 等价物 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 248 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 -m pytest -q` | 248 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | **27 用例全过**（模块通路 + 生成器自检 + 裸 console script 通路 + 零网络导入面审计），退出码 0 |
| `py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check` | 两层断言 + 提交 sha 复算 + merge-tree 现场复核 + **意图矩阵的脏改动现场复核**全过，退出码 0 |
| `py -3.12 -X utf8 tools/verify_mutation.py` | 基线绿 + **22 组**变异全部被对应守门抓到，仓库按字节还原，退出码 0 |

**M2 新增的"等价"缺口（写清，不笼统一句"本地等价校验通过"）**：

1. **git 版本差异未在真 CI 上验过**：M2 新依赖 `git diff -U0` 的 hunk 头形态与 `git status --porcelain -z`
   的记录协议，本机 git `2.54.0.windows.1` 实测通过；ubuntu 侧版本与 locale 差异**未实跑**。
2. **`-z` 协议里的中文路径**只有纯函数级用例（`decode_status_records`），本机没有真实中文路径的合成夹具
   → 端到端未覆盖。**如实登记为缺口**。
3. **`function_call` 形态的 `arguments`**（JSON 字符串里的 `input`）有纯函数级用例，端到端只在
   `custom_tool_call` 与 `exec` 上跑过（本机实测里前者出现频次远高）。
4. 3.8 之外的版本（3.9/3.10/3.11）不在矩阵里，不做承诺。

**详细版（含 DoD 逐项证据与偏差说明）在 [06-里程碑.md](06-里程碑.md) M2 节与
[07-交付对标与决策记录.md](07-交付对标与决策记录.md) §八**——这里只列可指认的替代证据与缺口。

---

## 十、M3 收尾：诚实口径与本地等价校验

**措辞纪律沿用 §七–§九（硬约束）**：本仓**仍无远端**，`git push` 一次都没跑过，因此 M3 **同样从未出现"CI 绿"字样**；
一切 CI 类结论只写"**本地等价校验（未接远端，CI 待首推验证）**"。

**可指认的替代证据**（本机实跑，2026-10-18）：

| 等价物 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 299 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 -m pytest -q` | 299 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | **29 用例全过**（模块通路 + 生成器自检 + 裸 console script 通路 + 零网络导入面审计），退出码 0 |
| `py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check` | 两层断言 + 提交 sha 复算 + merge-tree exit 现场复核 + 意图矩阵脏改动现场复核全过，退出码 0（**M3 未改冻结产物**，故与 M2 收尾同源） |
| `py -3.12 -X utf8 tools/verify_mutation.py` | 基线绿 + **29 组**变异全部被对应守门抓到，仓库按字节还原，退出码 0 |

**M3 新增的"等价"缺口（写清，不笼统一句"本地等价校验通过"）**：

1. **`git merge-tree --write-tree` 的输出形态只在单机上验过**（本机 git `2.54.0.windows.1`：三元组行与
   `CONFLICT` 文案都在 stdout）。其它版本若换通道/文案，表现为"少一个 `block` 命中"而非悄悄错判
   （`--check` 与 `test_git_merge_expectations_match_a_real_merge_tree_run` 会现场真跑复核 exit 码）。待首推验证。
2. **`modify/delete` 形态只有纯函数级用例**（冻结矩阵里没有"删除方 vs 修改方"的场景，造它要动冻结树）→ 端到端未覆盖。
3. **两个独立仓库（非 worktree）的跨仓库情形没有真夹具**：只有"不同仓库 common dir 不同"的纯函数级断言。
4. **`derived_from` 的"提示开关"未落地**（config 无该键）；本棒只实现默认行为，文档里不出现"可配置"字样。
5. 3.8 之外的版本（3.9/3.10/3.11）不在矩阵里，不做承诺。

**详细版（含 DoD 逐项证据与偏差说明）在 [06-里程碑.md](06-里程碑.md) M3 节与
[07-交付对标与决策记录.md](07-交付对标与决策记录.md) §九**——这里只列可指认的替代证据与缺口。

---

## 十一、M4 收尾：诚实口径与本地等价校验

**措辞纪律沿用 §七–§十（硬约束）**：本仓**仍无远端**，`git push` 一次都没跑过，因此 M4 **同样从未出现"CI 绿"字样**；
一切 CI 类结论只写"**本地等价校验（未接远端，CI 待首推验证）**"。

**可指认的替代证据**（本机实跑，2026-10-18）：

| 等价物 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 336 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 -m pytest -q` | 336 passed / 1 skipped（退出码 0） |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | **35 用例全过**（模块通路 + 生成器自检 + 裸 console script 通路 + 零网络导入面审计），退出码 0 |
| `py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check` | 两层断言 + 提交 sha 复算 + merge-tree exit 现场复核 + 意图矩阵脏改动现场复核全过，退出码 0（**M4 未改冻结产物**，故与 M3 收尾同源） |
| `py -3.12 -X utf8 tools/verify_mutation.py` | 基线绿 + **33 组**变异全部被对应守门抓到，仓库按字节还原，退出码 0 |

**M4 新增的"等价"缺口（写清，不笼统一句"本地等价校验通过"）**：

1. **桌面通知通道只在"不可用"这一侧有实物**：本机（Windows）零依赖通道本来就不存在，报告如实落
   `notify_unavailable`；"已发送"那一侧只有 `monkeypatch` 的合成用例（`test_notify_available_path_is_reported`
   断言通知命令**真的被调用**），**没有在真 macOS / Linux 桌面上跑过**。不写成"通知已支持"。
2. **`report` 不新增冻结场景**：报告对"`degraded` + `approximate` + `unsupported_format` 三态同屏"的渲染
   用的是手造 payload（`test_undetermined_entries_are_rendered_with_all_three_codes`），不是矩阵产物——
   冻结矩阵里没有这样一条场景，硬塞需要改真值与台账。
3. **"双跑逐字节一致"只覆盖同一台机器同一解释器**：跨平台（Windows CRLF / Linux LF）没有实跑，
   行尾契约靠 `write_atomic` 的 LF 固定 + `report.md` 的 `\r\n` 零命中断言守住。
4. **GitHub 风格的 Markdown 渲染未做视觉验收**：报告是纯文本 + 表格，本棒只断言结构（章节、键名、排序），
   没有在渲染器里看过效果。
5. 3.8 之外的版本（3.9/3.10/3.11）不在矩阵里，不做承诺。

**详细版（含 DoD 逐项证据与偏差说明）在 [06-里程碑.md](06-里程碑.md) M4 节与
[07-交付对标与决策记录.md](07-交付对标与决策记录.md) §十**——这里只列可指认的替代证据与缺口。

---

## 十二、M5 收尾：诚实口径与本地等价校验

**措辞纪律沿用 §七–§十一（硬约束）**：本仓**仍无远端**，`git push` 一次都没跑过，因此 M5 **同样从未出现
"CI 绿"字样**；一切 CI 类结论只写"**本地等价校验（未接远端，CI 待首推验证）**"。

**可指认的替代证据**（本机实跑，2026-10-18）：

| 等价物 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | **365 passed / 1 skipped**（退出码 0） |
| `py -3.12 -X utf8 -m pytest -q` | **365 passed / 1 skipped**（退出码 0） |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | **38 用例全过**（M4 为 35：新增 `bench` 模块 3 条 + console 1 条，退役「未就绪」2 条），退出码 0 |
| `py -3.12 -X utf8 -m agent_conflict_radar bench` | **15/15 场景通过、174 项检查 0 失败**，覆盖度门槛达标，退出码 0；`bench/last_run.json` 落盘 |
| `py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check` | 两层断言 + 提交 sha 复算全过（`last_run.json` 作为运行产物被**单名放行**），退出码 0 |
| `py -3.12 -X utf8 tools/verify_mutation.py` | 基线绿 + **36 组**变异全部被对应守门抓到（M4 为 33），仓库按字节还原，退出码 0 |
| 干净 venv（`py -3.12 -m venv` + `pip install -e ".[dev]"`） | `radar --version` / `config` / `selftest` / `bench --only` / `bench --bench-dir bench --out-dir out` / `python -m agent_conflict_radar.bench.gen --check` 全过；`out/last_run.json` 生成 |
| 隐私审计 | 入库内容扫描：真实盘符路径 / `/Users/` / `/home/` / Real-UUID / 真实用户名 **零命中**；零网络导入面审计通过 |

**M5 新增的"等价"缺口（写清）**：

1. **干净环境只在本机 Windows / Python 3.12 上做过**；干净 clone（`--no-local`）已建但未逐条跑 README（M6 做）。
2. **`bench` 全矩阵约 20s**：冒烟只跑 `--only` 子集，全量在测试与独立步骤里跑。
3. **跨平台逐字节一致没有实跑**：`last_run.json` 双跑一致只验同机同解释器。
4. **`bench` 与 `detect` 共用退出码 1**：语义区分靠人读输出措辞与 README，没有第二套码（K1 四语义的约束）。

**详细版在 [06-里程碑.md](06-里程碑.md) M5 节与 [07-交付对标与决策记录.md](07-交付对标与决策记录.md) §十一。**

