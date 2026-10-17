# HANDOFF-M1：从 M0 骨架续接到 M1（数据先行）

**项目**：`agent-conflict-radar`（本地目录 `10-18-agent-conflict-radar`）
**上一棒**：M0 骨架 —— ✅ 完成（2026-10-17）
**当前状态**：M0 已交付；**M1 已启动并冻结在中途**（用户要求只交付 M0，M1 进度固化后交给新对话）——
详见 §五 进度快照。
**本文件用途**：下一棒开工前**只需读本文件 + `plan/00`·`04`·`05`·`07` + `data/README.md` §六**，
不依赖对话记忆
**启动方式（用户侧，绝对路径）**：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务`

---

## 一、当前进度与证据

### 1.1 已完成

| 项 | 产物 | 证据（可复跑） |
|---|---|---|
| 计划文档 02–07 | `plan/02`–`07` 六份 | `plan/00` §一 索引表状态 ✅；出题定稿门 `check_topic.py` 0 FAIL |
| 可安装骨架 | `pyproject.toml`（`src` 布局 / 零运行时依赖 / dev extra=`pytest`）、`src/agent_conflict_radar/`（11 个模块） | `py -3.8` 与 `py -3.12` 各 `pip install -e . --no-build-isolation --no-deps` 成功；`radar --version` / `python -m agent_conflict_radar --version` 均 exit 0 |
| 数值口径单点 | `config/radar.toml`（7 节）+ 自写受限 TOML 子集解析器 | `radar config` 打印生效值 + `source_path`；`tests/test_config_single_source.py` |
| 退出码契约 | `exit_codes.py` + `stages.py` 阶段表 | `tests/test_cli_contract.py`（含 0/1/2/3/4 各语义 + 阶段守卫） |
| 冻结序列化契约 | `serialize.py` 唯一写盘点 + 零外链断言 | `tests/test_serialize_frozen.py` |
| 编码守卫 | `cli._ensure_utf8_stdio`（入口第一件事） | `tests/test_encoding_guard.py`（cp1252 本机复现 + cp936 保持不动 + 子进程端到端） |
| 门禁与工具 | 8 个测试文件（122 passed / 1 skipped）、`tools/verify_offline.py`、`tools/verify_mutation.py` | 见下方命令速查 |
| CI 预置 | `.github/workflows/ci.yml` 四矩阵（ubuntu/windows × 3.8/3.12） | **未跑过**：无远端，待首推验证 |

### 1.2 本棒实测数字（不要照抄，下一棒收尾要**复测**）

| 项 | 值 |
|---|---|
| 测试数 | `py -3.8` 122 passed / 1 skipped；`py -3.12` 122 passed / 1 skipped |
| 跳过项 | `tests/test_paths_adaptive.py` 符号链接用例——当前文件系统不支持创建目录符号链接（声明式跳过，附原因） |
| 离线冒烟用例数 | 23（模块通路 14 + console 通路 9，含 `--strict`） |
| 变异验证 | 10 组全部被对应守门抓到，仓库按字节还原 |
| 包版本 | `0.0.1`（`__init__.__version__` 单点，pyproject 走 `dynamic = attr`） |

### 1.3 未做（明确不在 M0 范围）

* `discover` / `intent` / `detect` / `report` / `bench` 五个模块文件**刻意没有创建**——桩会静默混过里程碑；
  未交付命令由 `stages.STAGE_NOT_READY` 显式拦截（exit 4，消息含计划里程碑）。
* `bench/` 场景数据（M1 生成器产出）、`scripts/check_release.py`（M6）、`docs/技术报告.md`（M5）、`MANIFEST.in`（M6）。

---

## 二、下一棒（M1）待办

> M1 DoD 全文见 `plan/06-里程碑.md` M1 节。这里只列**执行顺序与依赖**。

1. **`versions.py` 实测勘误（最高优先，其余都依赖它）**：拿本机真实会话日志做**只读探针**，
   核对 `plan/07` §六 的 G-1…G-3、G-7（Claude 行顶层键、Codex `session_meta.payload.cwd`、
   parent/child 关系表达、写操作时间戳可得性）。结论三处同步：`versions.py` 枚举 /
   `plan/04` M1 范围 / `plan/07` 决策记录（**保留原措辞 + 追加勘误注**，不回填美化）。
2. **R1/R2/R3 闭环**（`plan/05` §八）：`git merge-tree --write-tree` 在"无共同祖先 / 单 commit 仓库"
   下的输出形态与退出码；Codex `apply_patch` 路径字段形态；Claude `MultiEdit` 是否出现。
   结论写进 `data/README.md` §五。**未闭环的路径只允许落 `unknown`/`degraded`，不进判定。**
3. **`discover.py` 实现**：worktree 解析（按行，不按空格切分）→ 会话文件发现 → **按首行文件形态判别归属**
   → 版本指纹 → 派生关系 → 活跃 cell 组装。`seq` 必须是**源文件行号**。
4. **`radar scan` 交付**：同一次提交里按 **K15 四步**退役它的 exit 4 断言
   （`stages.py` 挪表 → CLI/测试同步（含 `not hasattr` 防复活）→ README 退出码表与状态表 → `plan/07` 决策记录），
   并补离线冒烟：`tools/verify_offline.py` 的期望值从 `EXIT_NOT_READY` 改为真实契约、
   `tests/test_stage_guard.py` 的两条期望值断言会自动跟着变红提醒你。
5. **`bench/gen.py`（包内）+ `bench/rng.py`**：确定性 RNG（**禁 stdlib `random`、禁系统时钟、禁 set 迭代序**），
   场景 1–6 + `truth.json`（**同步产出，禁手补**，无 `observed_*` 字段，带 `objects_forbidden` 反向样例）
   + `bench/manifest.json`（覆盖度门槛 = 每类 ≥1 且集合覆盖，`missing_types` 显式）。
   git 提交固定 `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` 与作者名，保提交 sha 可复算。
6. **生成器 `--check` 两层断言**：① 冻结产物形态；② 重跑生成器到临时目录 → 与冻结产物**逐字节比对**。
   生成侧与生产侧的规范序**各写一份独立实现**，一致性靠逐字节测试（**别顺手统一成一个 import**）。
7. **`radar scan` 的双跑逐字节一致**（端到端也锁一次）。
   > ⚠️ 更正（本棒实测后修）：**`radar bench` 评分命令属 M5，不在 M1**——`stages.py` 里
   > `bench` 的计划里程碑就是 M5。M1 只交付**生成器 + 真值 + manifest + `--check`**；
   > 评分与"检出集合精确匹配"的断言是 M5 的主体（`plan/06` M5 节）。
8. **门禁补充**：生成器 `--check` 加进 CI 步骤；`tools/verify_offline.py` 的 `bench` 用例期望值随交付更新。
9. **收尾**：M1 DoD 验证 → 回写 `plan/00`（索引 / 台账 / 里程碑）、`plan/05`（R1–R6）、`plan/06` → 写 `HANDOFF-M2.md` → commit。

### M1 必须遵守的降级纪律

| 情形 | 允许的行为 | 禁止的行为 |
|---|---|---|
| 会话字段与 M0 建模不符 | 以实测为准勘误，三处同步 | 让解析器"猜"或静默产出空表 |
| 未知会话版本 | `unsupported_format` + 列出缺失键 + 点名文件 | 按最宽松规则解析 |
| 找不到会话源 | exit 3 并提示如何显式指定 | 返回空结果 exit 0 |
| `merge-tree` 边缘形态未闭环 | 该路径降级为文件级 + `degraded` | 抛"无冲突" |
| 非 Python 文件 | 行区间近似 + `approximate=True` | 假装做了符号级 |

---

## 三、既定口径清单（K 编号，"动了会打挂测试"）

> 全文见 `plan/07-交付对标与决策记录.md` §四。**改任何一条都要五处同步**：代码 → 测试 → README → K 表 → 决策记录。

| K | 一句话 |
|---|---|
| K1 | 退出码 `0/1/2/3/4`；`4` 是骨架期专用，退役走**四步**（删常量 → 改 CLI/测试含 `not hasattr` 防复活 → 改 README 退出码表 → 改决策记录） |
| K2 | 序列化冻结：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写；**唯一写盘点 `serialize.write_atomic`** |
| K3 | 数值唯一权威 `config/radar.toml`；代码**零内联默认值**，缺失/未知/类型不符一律报错（exit 3） |
| K4 | 只读：不 merge/rebase、不写索引、不改工作区；`merge-tree` 只允许 `--write-tree`（对象库临时 tree **如实披露**，不得声称"零任何写入"） |
| K5 | 零内联阈值字面量门禁（`0`/`1` 之外必须登记 `ALLOWED_LITERALS` 并写理由）+ 下层禁止 import 上层 |
| K6 | 底线解释器（3.8）缺能力 → 自写受限子集 + 超集形态**显式报错**，不静默跳过、不引运行时依赖 |
| K7 | 会话格式版本 = 显式指纹集合；未知版本 `unsupported_format` + 缺失键 + 点名文件 |
| K8 | 编码三加固：入口 `_ensure_utf8_stdio` + 子进程显式 `encoding=` + CI `PYTHONUTF8=1` |
| K9 | 真值只存"输入与期望"；出现 `observed_*` 即红；期望值必须可由输入独立复算；生成器与真值同步产出 |
| K10 | 生成器 `--check` 两层断言（产物形态 + 重生成逐字节）；规范序生成侧/生产侧各一份独立实现 |
| K11 | 合成数据白名单：`demo-radar-alpha`/`demo-radar-beta`、`sess-radar-NNNN`、`radar-user`、`feat/agent-a`·`feat/agent-b`、`2026-01-01T00:00:00Z` 起的确定偏移 |
| K12 | 计数口径先声明"条目数 vs 命中记录数"；`sum(by_level) == len(conflicts)` 写成集合划分恒等式；`undetermined` 独立分区 |
| K13 | 报告渲染三律：零判定 + 零外链（断言常驻渲染出口）+ 双跑逐字节一致 |
| K14 | 对外声称逐条有实物（许可/命令/extras/名字四向一致），由 `tests/test_readme_gate.py` 五面对账 |
| K15 | 每交付一条命令 → 同一次提交退役其旧断言 + 补离线冒烟；`python -m` 与裸 `radar` 两条通路都冒烟 |
| K16 | 路径自适应；`expanduser` 解不出主目录时**按哨兵比对**报错——不写盘、不抛系统异常、不回落 CWD |

---

## 四、本机环境坑（**只写实测过的**）

1. **`py` 的标志顺序**：`py -3.8 -X utf8 -m ...` 正确；写成 `py -X utf8 -3.8 -m ...` 会报
   `Unknown option: -3`（本棒踩过）。一律：**先版本选择器，再 `-X utf8`**。
2. **`Path.write_text(newline=)` 是 Python 3.10+ 参数**：底线 3.8 上 `TypeError`。本棒实测命中
   （8 个测试同时红）。写法一律 `open(path, "w", encoding="utf-8", newline="\n")`；
   `tests/conftest.py` 已提供 `write_lf` 夹具与 `write_lf_text()` 供复用。
3. **本机两条解释器通道**：`py -0p` → `3.8.8-64` 与 `3.12.10-64`。两者**已各装一份 editable 包**；
   但 **PATH 上的 `radar` 是 3.12 那一份**（3.8 的 `Scripts` 目录不在 PATH，安装时 pip 有 warning）。
   所以"3.8 通道下的 console 冒烟"实际由 3.12 的脚本执行——**不要**把这条写成"两版本各自验了两条通路"。
4. **`O` 型坑：`grep` 中文与 Git Bash 显示**：`git status --short` 显示中文文件名为八进制转义
   （`\351\234\200...`），只是显示问题，`git add .` 不受影响。
5. **临时目录**：本棒一律用 `tempfile.mkdtemp()`（Windows 侧路径），**不要**用 Git Bash 的 `/tmp`
   （与 Windows Python 不互通）。
6. **零写盘纪律的实测方式**：`tests/test_paths_adaptive.py::test_expanduser_sentinel_raises_and_writes_nothing`
   在临时 CWD 里断言"零文件产生"——下一棒做会话扫描时，同类断言要覆盖"扫描不落任何中间产物"。

---

## 五、DoD 逐项 checklist（M0，已逐项验证）

* [x] `plan/00`–`07` 齐备且索引状态一致；出题定稿门 `check_topic.py` 0 FAIL
* [x] 可安装：两个解释器 `pip install -e .` 成功；`radar` 与 `python -m agent_conflict_radar` 双通路 exit 0
* [x] 退出码契约：0/1/2/3/4 各有测试；未交付命令 exit 4 且**stdout 为空**（不伪造空结果）
* [x] 数值单点：零内联默认值 + 缺键/未知键/类型不符/版本不符/TOML 超集形态全部显式报错
* [x] 零内联阈值门禁：扫描面非空 + 探针自证 + 阴性对照
* [x] 冻结序列化：契约参数断言 + 期望字节断言 + 双跑逐字节一致 + 无临时文件残留
* [x] 编码守卫：cp1252 重配生效、cp936 保持不动、无 `reconfigure` 不崩、子进程端到端不崩
* [x] 路径自适应：无硬编码用户名/主目录（探针 + 阴性对照）+ expanduser 哨兵不写盘不回落
* [x] README 指令面五面对账（含"抽取面非空"与"抽取器不空转"自证）
* [x] 阶段守卫三方并排（parser 注册面 / stages 两表 / 冒烟覆盖）+ 断言过期的先行告警
* [x] 双解释器全量 pytest：各 122 passed / 1 skipped（跳项附原因）
* [x] 离线冒烟 `--strict`：23 用例全过（两条通路）
* [x] 变异验证：10 组全部被对应守门抓到，仓库按字节还原
* [x] **CI：本地等价校验（未接远端，CI 待首推验证）** —— 缺口已列在 `plan/00` §七
* [x] `HANDOFF-M1.md`（本文件）六节齐、库内相对路径、无本机绝对路径

**偏差说明**：无未达成项。唯一"未做"是 CI 实跑（无远端，属已知约束，非偏差）；
以 `plan/00` §七 的等价物清单与缺口清单替代，并已在该处明写措辞纪律。

---

## 六、关键命令速查（**每条都在 M0 收尾时实跑过**）

```bash
# 安装（两个解释器各一次；--no-build-isolation 因本机 pip 代理易被污染）
py -3.12 -m pip install -e . --no-build-isolation --no-deps
py -3.8  -m pip install -e . --no-build-isolation --no-deps

# 全量测试（双解释器；先版本选择器再 -X utf8）
py -3.8  -X utf8 -m pytest -q
py -3.12 -X utf8 -m pytest -q

# 离线冒烟（CI 与本地同一条通路；--strict 要求 console script 存在）
py -3.12 -X utf8 tools/verify_offline.py --strict

# 守门变异验证（新增/改写守门后必跑；可 --only M3,M5 单跑）
py -3.12 -X utf8 tools/verify_mutation.py

# 看生效配置（确认数值只有一个来源）
radar config

# 自检
radar selftest

# 未交付命令（当前应 exit 4）
radar scan --repo .
```

> **提示**：`radar` 与 `python -m agent_conflict_radar` 是两条通路（`sys.path` 来源不同）。
> 在源码态未安装时，用 `PYTHONPATH=src py -3.12 -X utf8 -m agent_conflict_radar <命令>`。

---

## 七、M1 进度快照（2026-10-17 冻结，交接给新对话）

> **M1 出口判据未达成 → 不写 `HANDOFF-M2.md`**（纪律：里程碑中断/阻塞时只更新当前 HANDOFF 的
> 待办区与续接指针，不写虚构的下一棒）。M1 达成后按 §二 的顺序收尾。

### 7.1 已完成并**有证据**的部分

| 项 | 状态 | 证据落点 |
|---|---|---|
| **只读探针：会话字段形态**（G-1 / G-2 / G-3 / G-7） | ✅ 完成 | `data/README.md` §6.4（两侧逐字段实测值）+ `versions.py` 模块文档 |
| **R1 闭环：`merge-tree --write-tree` 形态矩阵** | ✅ 完成（8 种形态 + 只读性实测） | `data/README.md` §6.1 + `plan/07` 决策记录 |
| **R2 闭环：Codex `apply_patch` 形态** | ✅ 完成（含 `exec` 变体与计数） | `data/README.md` §6.2 |
| **R3 闭环：Claude `MultiEdit`** | ✅ 完成（**本机 0 次出现** → 不编造，保守降级） | `data/README.md` §6.3 |
| **`versions.py` 按实测重写** | ✅ 完成（显式版本集合 `claude-jsonl-v1` / `codex-jsonl-v1`） | 源码 + `plan/07` §六 勘误表逐条打勾 |
| **`discover.py` 实现** | 🔶 **已写、已在合成夹具上跑通一次，但无测试** | 见 7.2 |
| **`config/radar.toml` 新增 `[scan] max_line_bytes`** | ✅ 完成（`config.py` 模式已同步） | 源码 + `radar config` 输出 |
| **口径定稿：`conflicts[]` 用 `levels`/`symbols` 集合** | ✅ 定稿并三处同步（原"只报一条最高粒度"与题面场景 3 冲突） | `plan/04` M3 / `plan/05` §4.2 / `plan/07` 决策记录 |
| **口径定稿：活跃判定用显式 `--now`** | ✅ 定稿（缺省取观测到的最大时间戳） | `plan/07` 决策记录 / `plan/04` M1 |

### 7.2 `discover.py` 的唯一一次实跑证据（合成夹具，只读）

夹具：临时 git 仓库（1 commit）+ 一份仿 Claude 会话（**首行故意放 `last-prompt`**，消息行在第 3 行）
+ 一份仿 Codex 会话（首行 `session_meta`，`payload.cwd` 指向该仓库）。实跑输出：

```
worktrees: 1
sessions: 2 ['claude:sess-a.jsonl', 'codex:rollout-1.jsonl']
cells: 2 [('claude', True), ('codex', True)]        # in_worktree 均为 True
undetermined: 0
reference_time: 2026-01-01T00:10:00Z
双跑逐字节一致: True
```

**这条证据只说明"能在合成夹具上跑通一次"，不说明"归集正确"**——M1 DoD 要的是
"对合成日志产出稳定表 + 逐字段对账 + 与真值台账互证"，这些都还没做。

### 7.3 未完成（下一棒的起点，按序）

1. **`discover.py` 的测试**（当前 0 个测试文件覆盖它）：
   worktree porcelain 逐字段解析（路径含空格 / `detached` / 裸仓库）；首行非消息行的 Claude 文件
   （`seq` 必须是消息行行号而非 1）；未知格式 → `undetermined(unsupported_format)` + 缺失键 + 点名文件
   且**不产出空表**；源根不存在 → **exit 3**（不是 exit 0 空结果）；父会话不在扫描范围 →
   `undetermined(parent_not_found)` 且 `derived_from` 保持 `null`；`cwd` 匹配不到 worktree →
   `in_worktree=false` 且保留原始 cwd；超长行 → `undetermined(line_too_long)` **不静默截断**；
   **双跑逐字节一致**（显式传 `--now`）+ 端到端再锁一次。
2. **`radar scan` 交付（K15 四步，缺一步即幽灵语义）**：
   * `stages.py` 把 `scan` 挪进 `DELIVERED_COMMANDS`（**当前仍在 `STAGE_NOT_READY`**）；
   * CLI 接线：`--now`（全局选项）→ `discover.build_workspace_table` → stdout 打 JSON；
     `--out-dir` 落 `scan.json`（经 `serialize.write_atomic`）；`--window` 覆盖 `window.scan_days`
     时**需要先给 `Config` 加一个只读覆盖方法**——当前 `Config` **没有** `with_override`，
     上一版接线因此不可用（已撤回）；
   * `tools/verify_offline.py` 的 `scan` 用例期望值由 `EXIT_NOT_READY` 改为 `EXIT_OK`，
     并显式传 `--claude-root` / `--codex-root`（临时目录）与 `--now`；
   * README 状态表把 `radar scan` 标 ✅、补 `--now` 用法与"`scan` 成功恒为 0，`undetermined` 只提示不改码"。
3. **`bench/rng.py` + `bench/gen.py`（完全未开始）**：确定性 RNG（**禁 stdlib `random`、禁时钟、禁 set 序**）、
   场景 1/2/3/4/5/6a/6b（构造几何见 `plan/05` §4.2）、真值 `truth.json` 同步产出（**无 `observed_*` 字段**、
   带 `geometry` 让期望可独立复算、带反向样例）、`manifest.json` 覆盖度门槛（每类 ≥1 + 集合覆盖）。
4. **生成器 `--check` 两层断言**（产物形态 + 重跑生成器到临时目录逐字节比对），并把 `--check` 加进 CI 步骤。
5. **收尾**：M1 DoD 验证 → `plan/00`（索引 / 台账 / 里程碑）、`plan/05`（R4/R5/R6）、`plan/06`（M1 DoD 打勾）
   → 写 **`HANDOFF-M2.md`** → commit。

### 7.4 冻结时的工作树状态

* `git status` 干净；**M0 全部门禁重新全绿**（见 7.5）。
* `discover.py` / `versions.py` 已在树里，但 `scan` **仍被阶段表拦截（exit 4）**——**有意为之**：
  按 K15，没有测试与冒烟的交付不算交付。
* `cli.py` 的 `_cmd_scan` 接线与全局 `--now` **已按 7.3 的说明撤回**（撤回未验证的接线）；
  `--now` 的口径决定已落 `plan/07` 决策记录，不会丢。

### 7.5 冻结时的验证记录（实跑）

| 门 | 结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 122 passed / 1 skipped（exit 0） |
| `py -3.12 -X utf8 -m pytest -q` | 122 passed / 1 skipped（exit 0） |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | 23 用例全过（exit 0） |
| `py -3.12 -X utf8 tools/verify_mutation.py` | 10 组变异全部被检出，仓库按字节还原（exit 0） |
| 出题定稿门 `check_topic.py` | 0 FAIL / 0 WARN / 21 PASS |
| `discover.py` 合成夹具单跑 | 见 7.2（**仅一次，非门禁**） |

> **本棒新增的一条维护纪律**：`discover.py` 里的 `[:400]`（错误详情截断长度）触发了 K5 零内联阈值门禁，
> 已按"扩词表是正常维护动作"在 `tests/test_config_literals.py` 的 `ALLOWED_LITERALS` 登记并写明理由
> ——下次遇到同类告警**照此办理**（登记 + 理由），**不要**改判据去放行。
