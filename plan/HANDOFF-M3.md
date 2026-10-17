# HANDOFF-M3：从 M2 续接到 M3（三级冲突检测）

**项目**：`agent-conflict-radar`（本地目录 `10-18-agent-conflict-radar`）
**上一棒**：M2 —— ✅ **完成**（2026-10-18）：`radar intent` 交付 + 意图矩阵入仓（7 条场景 / 三分法 / 降级纪律 / 两层 `--check` 含脏改动现场复核）+ R4 闭环
**当前状态**：M0 + M1 + M2 全部门禁在本机复核全绿（见 §五）
**本文件用途**：下一棒开工前**只需读本文件 + `plan/00`·`04`·`05`·`07` + `data/README.md` §6.6**，不依赖对话记忆
**启动方式（用户侧，绝对路径）**：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务`

---

## 一、当前进度与证据

### 1.1 已完成（M2 本体）

| 项 | 产物 | 证据（可复跑） |
|---|---|---|
| `radar intent` 交付（K15 四步走完） | `intent.py` + `cli._cmd_intent` | `tests/test_intent.py`（30 条）+ `tests/test_intent_parse.py`（41 条）+ 冒烟两条通路各 1 条 intent 用例 |
| 端到端确定性 | `--now` 显式传 → 双跑逐字节一致；`--out-dir` 落 `intent.json` 与 stdout 同内容 | `test_intent_is_byte_identical_across_two_real_processes` / `test_intent_out_dir_writes_intent_json_with_identical_bytes` |
| 意图矩阵（7 条场景） | `bench/intents/<id>/{repo,sessions,truth.json}` + `bench/intents/manifest.json` | `py -X utf8 -m agent_conflict_radar.bench.gen --check` |
| **与冲突矩阵分开冻结**（改松门禁的替代方案） | 意图真值判据（三分法 / `unknown_expected` / 脏改动）与 M1 的"恰好两个改动侧"判据互不牵制 | `plan/05` §九 + `plan/07` 决策记录（2026-10-18） |
| 真值可脱离引擎独立复算 | `geometry.ops[].anchor_hits` + 由基线推出的区间；真值里没有 `observed_*` | `test_intent_truth_has_no_observed_fields_and_counts_partition`（**不 import `intent.py`**） |
| 降级纪律逐条有 reason 码 | `replace_all` / `anchor_ambiguous#N` / `multi_edit_unsupported` / `missing_file_path` / `patch_without_file_instruction` / `not_in_worktree` / `disk_and_session_disagree` … | 场景 `intent_replace_all_coarse` / `intent_ambiguous_anchor_coarse` / `intent_multi_edit_unknown` / `intent_codex_exec_patch` / `intent_disk_wins` |
| **R4 闭环** | 非 Python → `approximate=True` 且产物里没有符号字段 | `test_non_python_files_are_approximate_and_carry_no_symbol_field`（断言整份产物不含 `"symbol"`）+ 变异组 M21 |
| 门禁补充 | 2 个新测试文件（71 条用例）+ 冒烟 27 用例 + 变异组 M17–M22 + 既有断言的两处退役 | 见 §六 命令速查 |
| 文档回写 | `plan/00`（索引/台账/里程碑/§九）、`plan/04`（M2 勘误注 + 完整输出样例 + 降级表）、`plan/05`（§二·§三·§八 R4·§九 意图矩阵）、`plan/06`（M2 收尾结论）、`plan/07`（10 条决策记录 + K19 + §八）、`data/README` §三/§五/§6.6、README | 本文件 §五 逐项 |

### 1.2 本棒实测数字（不要照抄，下一棒收尾要**复测**）

| 项 | 值 |
|---|---|
| 测试数 | `py -3.8` 248 passed / 1 skipped；`py -3.12` 248 passed / 1 skipped |
| 跳过项 | `tests/test_paths_adaptive.py` 符号链接用例——当前文件系统不支持创建目录符号链接（声明式跳过，附原因） |
| 离线冒烟 | `--strict` 下 **27 用例全过**（模块通路 12 + 生成器自检 1 + console 通路 8 + 其余 6 为用法/环境类） |
| 变异验证 | **22 组**全部被对应守门抓到，仓库按字节还原 |
| 合成矩阵 | 冲突 7 条（6 个覆盖类型）+ **意图 8 条**（2 个覆盖类型），两棵树的 `missing_types` 均为空、提交 sha 可复算 |
| 包版本 | `0.0.1`（未变） |
| 生成器物化入口 | 冲突：`--materialize <id>`；意图：`--materialize-intent <id>`（都需 `--dest`） |

### 1.3 未做（明确不在 M2 范围，就是 M3 的活）

* `detect` / `report` / `bench` 三条命令**仍 exit 4**（`stages.STAGE_NOT_READY` 里）。
* 三级冲突检测（文件 / 区块 / 符号）、`gitio.merge_tree` 只读封装、`derived_from` 去重：**全未开始**。
* `radar bench` 的**评分**属 M5；`docs/技术报告.md`（M5）、`scripts/check_release.py`（M6）、`MANIFEST.in`（M6）仍未落。

---

## 二、下一棒（M3）待办

> M3 DoD 全文见 `plan/06-里程碑.md` M3 节。这里只列**执行顺序与依赖**。

1. **`detect.py` 三级实现**（`plan/04` M3 节）：
   * **文件级**：`(path)` 出现在两个**不同且活跃**的 `(workspace, session)` 组中 → `level="file"`，附各会话 `last_write_ts`；
   * **区块级**：`git merge-tree --write-tree <base> <other>`（**只读**）解析冲突路径与冲突块；
   * **符号级**：`ast` 取新旧两版的 `FunctionDef`/`AsyncFunctionDef`/`ClassDef`（含限定名 `A.f`）区间，
     把 M2 的 `changed_ranges` 映射到符号（同符号 / 相邻符号 / 同文件不同符号）。
2. **一条记录 = 一个 `(workspace_a, workspace_b, path)` 组合**（`plan/07` 决策记录已定稿）：
   `levels` 是命中的粒度**集合**，`level` 是其中最高的一档；`symbols` 是命中的限定名集合；
   真值按 `levels` / `symbols` **集合精确匹配**（多报、漏报均失败）。
3. **计数两栏**（K12）：`counts.by_max_level` 是**划分**（`sum == len(conflicts)`），
   `counts.by_level_membership` 是**成员数**（可大于条数，一条可同时命中多级）；`undetermined` 独立分区不计入。
4. **`derived_from` 去重**：两侧 `derived_from` 相同（同一 parent 派生的 subagent）→ 默认不产出冲突（场景 4）。
5. **只读断言**：跑完 `merge-tree` 后工作区与索引 hash 前后一致（测试断言，K4）。
6. **降级**：缺共同祖先 / 单 commit / 超时 / git 不可用 → `degraded=True` + `undetermined(degraded)`，
   **不得抛"无冲突"**；`merge-tree --write-tree` 会在对象库写临时 tree 对象——**如实披露**，不声称"零任何写入"。
7. **`radar detect` 交付**：K15 四步（`stages.py` 挪表 → CLI 接线 + 测试同步（含"逐条已交付命令不得残留在未就绪表"）→
   冒烟期望值改真实契约 + 补一条 → README 状态表/退出码表）；产物 `detect.json`（或 `conflicts.json`）经 `serialize.write_atomic`。
   **⚠️ 检查清单**：交付时**必须**复盘本棒踩到的两类"交付即失效"：① 硬编码"某命令仍未交付"的测试样本
   （本棒是 `test_selftest_detects_stage_table_overlap`）→ 改成从**当前** `STAGE_NOT_READY` 动态取；
   ② 变异脚本里指向该命令名的锚点（本棒是 M4）→ 改锚到仍在未就绪表里的命令。
8. **退出码**：`detect` 有冲突 → `1`、无冲突 → `0`（**这是第一条真的会用 1 的命令**，README 退出码表的措辞要跟着改）；
   `undetermined` 不改变"有冲突/无冲突"的判定，但报告里要显式列出。
9. **过渡形态的真实性（M3 相对于 M2 的关键差异）**：M2 的意图矩阵把场景控制在"单个工作区 + 未提交改动"，
   而 M3 的冲突检测要**两条分支**——`bench/scenarios/` 的七条冲突场景正是为此准备的（每条都已冻结
   `git_expected_merge_exit`，并由 `--check` **现场真跑 merge-tree** 复核）。**优先复用它们，别另造一套夹具**。
10. **收尾**：M3 DoD 验证 → 回写 `plan/00` / `plan/04` / `plan/05` / `plan/06` / `plan/07`（决策记录 + K 表）→
    写 `HANDOFF-M4.md` → commit。

### M3 必须遵守的降级纪律

| 情形 | 允许的行为 | 禁止的行为 |
|---|---|---|
| `merge-tree` exit 128（无共同祖先 / 非 git） | 落 `degraded` + `undetermined`，只给文件级 | 当成"无冲突" |
| 单 commit 仓库（无共同祖先可用） | 同上（降级到文件级） | 编一个区块级结论 |
| `ast` 失败（语法错误 / 非 Python） | 该文件 `approximate=True` 或 `undetermined`，**不影响同批其他文件** | 静默当"无冲突"；假装做了符号级 |
| 两侧 `derived_from` 相同 | 默认不产出该对（可配置产出最低档并标注） | 把"自己和自己"报成跨 agent 冲突 |
| `merge-tree` 写对象库临时 tree | 报告与 README **如实披露**这条边界 | 声称"零任何写入" |
| 只有一侧有改动 / 文件在另一个 worktree | 维持文件级、严格按 `(workspace_a, workspace_b, path)` 归属 | 张冠李戴（把不同 workspace 的改动混成一对） |

---

## 三、既定口径清单（K 编号，"动了会打挂测试"）

> 全文见 `plan/07-交付对标与决策记录.md` §四。**改任何一条都要五处同步**：代码 → 测试 → README → K 表 → 决策记录。
> M2 新增一条：**K19**（M2 落点三分法 + 计数两口径 + 磁盘优先 + `HEAD` 定位基线）。

| K | 一句话 |
|---|---|
| K1 | 退出码 `0/1/2/3/4`；`4` 随命令交付逐项退役，四步同步（`scan` M1 退役、`intent` M2 退役） |
| K2 | 序列化冻结：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写；**唯一写盘点 `serialize.write_atomic`** |
| K3 | 数值唯一权威 `config/radar.toml`；代码**零内联默认值**，缺失/未知/类型不符一律报错（exit 3）；覆盖只走 `Config.with_override`（内存视图，不写盘） |
| K4 | 只读：不 merge/rebase、不写索引、不改工作区；`merge-tree` 只允许 `--write-tree`（对象库临时 tree **如实披露**）。**生成器例外**：它只造**自己临时目录里的合成仓库**，故直接调 `git init/add/commit`（见 `bench/gen.py` 模块文档） |
| K5 | 零内联阈值字面量门禁（`0`/`1` 之外必须登记 `ALLOWED_LITERALS` 或整文件豁免并写理由）+ 下层禁止 import 上层 |
| K6 | 底线解释器（3.8）缺能力 → 自写受限子集 + 超集形态**显式报错**，不静默跳过、不引运行时依赖 |
| K7 | 会话格式版本 = 显式指纹集合；未知版本 `unsupported_format` + 缺失键 + 点名文件 |
| K8 | 编码三加固：入口 `_ensure_utf8_stdio` + 子进程显式 `encoding=` + CI `PYTHONUTF8=1` |
| K9 | 真值只存"输入与期望"；出现 `observed_*` 即红；期望值必须可由输入独立复算；生成器与真值同步产出 |
| K10 | 生成器 `--check` 两层断言（产物形态 + 重生成逐字节）；生成侧/生产侧规范序**各一份独立实现** |
| K11 | 合成数据白名单（M1 追加 `src/beta.py` / `src/filler.py` / `{{REPO_ROOT}}` / 假 author；**M2 追加 `src/dup.py` / `docs/notes.md` / `sess-radar-0020`–`0026`**） |
| K12 | 计数口径先声明"条目数 vs 命中记录数"；`sum(by_level) == len(conflicts)` 写成集合划分恒等式 |
| K13 | 报告渲染三律：零判定 + 零外链（断言常驻渲染出口）+ 双跑逐字节一致 |
| K14 | 对外声称逐条有实物（许可/命令/extras/名字四向一致），由 `tests/test_readme_gate.py` 五面对账 |
| K15 | 每交付一条命令 → 同一次提交退役其旧断言 + 补离线冒烟；`python -m` 与裸 `radar` 两条通路都冒烟 |
| K16 | 路径自适应；`expanduser` 解不出主目录时**按哨兵比对**报错——不写盘、不抛系统异常、不回落 CWD |
| K17 | **冻结产物机器无关**：`bench/` 一切文本不得含本机绝对路径（会话根写 `{{REPO_ROOT}}`）；`.git` **不入**冻结产物；提交可复现靠**复算 sha** |
| K18 | **真值里的阈值一律 config 符号引用**（`config_ref` / `const`），由 `--check` 现场求值；真值里不得出现策略数值键名 |
| K19 | **M2 落点三分法**：`exact`（磁盘 hunk **或**会话锚点在 `HEAD` 里唯一命中）/ `coarse`（文件在、区间不可断言）/ `unknown`（连文件都不知道）；`exact+coarse+unknown == entries`（条目数）+ `unknown_write_ops`（**写操作条数**）两口径分开登记；**磁盘优先**（`ranges_source="disk"` + `disk_and_session_disagree`，会话原值留在 `writes[]`）；**定位基线恒为 `HEAD`**（零工作区读取、零仓库外读取） |

---

## 四、本机环境坑（**只写实测过的**；M2 新增四条）

1. **`py` 的标志顺序**：`py -3.8 -X utf8 -m ...` 正确；写成 `py -X utf8 -3.8 -m ...` 会报 `Unknown option: -3`。
   一律：**先版本选择器，再 `-X utf8`**。
2. **`Path.write_text(newline=)` 是 Python 3.10+ 参数**：底线 3.8 上 `TypeError`。
   写法一律 `open(path, "w", encoding="utf-8", newline="\n")`；`tests/conftest.py` 有 `write_lf` 夹具与 `write_lf_text()`。
3. **本机两条解释器通道**：`py -0p` → `3.8.8-64` 与 `3.12.10-64`。两者**已各装一份 editable 包**；
   PATH 上的 `radar` 是 **3.12** 那一份（3.8 的 `Scripts` 不在 PATH）。不要把"3.8 通道的 console 冒烟"写成
   "两版本各自验了两条通路"——它实际由 3.12 的脚本执行。
4. **`grep` 中文与 Git Bash 显示**：`git status --short` 显示中文文件名为八进制转义，只是显示问题
   （`git diff --stat` 一样；用 `git -c core.quotepath=false status` 可读）。
5. **临时目录**：一律用 `tempfile.mkdtemp()`（Windows 侧路径），**不要**用 Git Bash 的 `/tmp`
   （与 Windows Python 不互通）。
6. **⚠️ 只传一侧会话根 = 会去读真实用户日志**：`scan --claude-root X` 时另一侧的 `codex` 会走
   "常见位置探测"落到 `~/.codex/sessions`（本机实测读进 **125 个真实会话文件**）。
   处置：**测试与冒烟一律两侧都显式传**（场景里没有该源时传一个空目录）。凡"自动发现本机数据"的参数，
   测试必须把探测面钉死。**M2 的 `intent` 同样吃这个坑**（`_resolve_session_roots` 与 `scan` 同一套规则）。
7. **Windows 上 `shutil.rmtree` 会被 git 的只读对象文件挡住**：git 落在 `.git/objects` 里的文件带只读位，
   直接 `rmtree` 报 `PermissionError: [WinError 5]`。`bench/gen.py` 的 `_rmtree()` 先 `chmod 0o700` 再删
   ——写自己的工具时照此办理（**M2 的意图场景物化重跑同一目录时必然触发**，`_clear_own_products` 已改走 `_rmtree`）。
8. **同一份夹具别物化两次**：`tools/verify_offline.py` 的 `build_cases` 与 `console_script_cases` 共用
   `_SCAN_FIXTURES` / `_INTENT_FIXTURES` 缓存（都拿 `scratch` 当 key）。不缓存会互相删目录（叠加第 7 条 → 偶发失败）。
   **注意两套夹具的 key 空间要分开**（本棒用两个 dict，避免 scan/intent 互相覆盖）。
9. **中文注释/字符串里别用 ASCII 双引号**：`"...「输入数据」..."` 用 `「」`；
   在双引号字符串里写 `"输入数据"` 会直接 `SyntaxError`。
10. **门禁与实现冲突时，先问"是不是实现写得比判据更糙"**：本棒实例——`--check` 的"本机路径片段"模式表
    写成 `"/home/"` 这类成品片段，与 K16 门禁冲突。**正解不是给门禁开例外**，而是把模式表拆成
    `目录名 × 分隔符`（判据反而更全）。
11. **零写盘纪律的实测方式**：`test_scan_cli.py` / `test_intent.py` 各有一条在临时 CWD 里断言
    "零文件产生"（含临时文件）的用例——新命令照抄这条形态。
12. **⚠️ `-U0` 的 hunk 头要按"第二个 `@@` 之前"解析**（M2 实测踩中）：`@@ -9 +9 @@ def f():` 里，
    `raw.split("@@")` 的 **`parts[1]`** 才是范围，`parts[2]` 是上下文文本。按 `parts[2]` 解析会得到
    **0 个区间**、整块改动静默消失——而且 `git status` 那边明明报了"文件已改"（两个信号互相矛盾时才最容易发现）。
    同理 `Binary files ... differ` 的行**没有** `+++` 头，路径只能从 `diff --git a/x b/x` 那一行取。
13. **⚠️ `git status` 一定加 `-z`**：行模式下中文/特殊字符路径会被 C 风格转义（八进制），
    `-z` 给出原样路径且 rename/copy 会**多跟一条原始路径**记录（必须按协议消费，否则那条路径会被当成新文件）。
14. **⚠️ 变异脚本的锚点要带上下文**（M2 实测踩中）：新增代码里出现与旧门禁**同形**的一行时，
    只锚那一行的变异会改到**新代码**上，目标守门照常绿。变异脚本的"未检出（假门！）"当场把它报了出来——
    这是三重断言的对照组，**别把它当噪音忽略**。

---

## 五、DoD 逐项 checklist（M2，已逐项验证）

* [x] **解析对账**：八条意图场景逐条一致（`(path, session_id, precision)` 集合精确匹配，多报/漏报均失败），
  含 `coarse`（`replace_all` / `anchor_ambiguous#2`）与 `unknown`（`multi_edit_unsupported` / `missing_file_path`）分支
* [x] **不猜测**：`MultiEdit` → `unknown` + `counts.multi_edit_ops`；`file_path` 缺失 → `unknown`；
  `replace_all` → `coarse` 且 `changed_ranges == []`；锚点两处命中 → `coarse` + 点名命中次数
* [x] **幂等合并**：按 `(workspace, path)` 聚合、逐会话 `writes[]` 保留归属；`last_write_ts` 取组内最大值（有实物：一条会话两条写操作）
* [x] **确定性**：真子进程双跑 stdout 逐字节一致；`intent.json` 与 stdout 同内容 / LF 行尾 / 结尾一个换行；**零中间产物**
* [x] **退役（K15 四步）**：`stages` → CLI + 测试 → 冒烟两条通路 → README；**顺带修掉两处"交付即失效"的既有断言**
  （`test_selftest_detects_stage_table_overlap` 的硬编码样本、变异组 M4 的漂移锚点）
* [x] **R4 闭环**：非 Python → `approximate=True` 且产物里**没有符号字段**；实物 + 可证伪（变异组 M21）
* [x] **磁盘对账**：`git diff` 与 `git diff --cached` 两条通路各真跑一次；磁盘优先 + 点名分歧 + 保留会话原值
* [x] **非 git / worktree 之外**：`coarse` + `not_in_worktree`，保留原 cwd、不读盘、不崩、不丢会话；`--repo` 非 git 仓库 → exit 3
* [x] **双解释器全量 pytest**：各 **248 passed / 1 skipped**（跳项附原因）
* [x] **离线冒烟 `--strict`**：**27 用例**全过（两条通路 + 生成器自检 + 零网络导入面审计）
* [x] **变异验证**：**22 组**全部被对应守门抓到，仓库按字节还原
* [x] **CI：本地等价校验（未接远端，CI 待首推验证）**——`--check` 与冒烟只在本地按同一条命令复跑过
* [x] **`HANDOFF-M3.md`（本文件）**：六节 + 起点快照，库内相对路径、无本机绝对路径

**偏差说明**（如实记录，不做美化）：

1. `plan/04` M2 原措辞只写"在基线里定位"，**没有定死"基线"是哪个版本**。本棒定死为 `HEAD`
   （`git show HEAD:<path>`）：语义更对（agent 的改动相对它开始时的已提交版本），且零工作区读取。落勘误注①。
2. `plan/04` M2 原措辞的"能从 diff hunk 得到 → exact"只覆盖了 `exact` 的一条来源；
   完整判据（含 `coarse` / `unknown` 的分支表）落勘误注②。
3. 产物**新增 `writes[]` 逐会话数组**（M3 的符号级要用；只给并集会让归属丢失）。
4. **意图矩阵独立成树**（`bench/intents/`）：合进 `bench/scenarios/` 就得放宽 M1 的"恰好两个改动侧"判据——
   那是"改松门禁换便利"，不做。
5. `unknown_write_ops` 与 `unknown` 是**两个口径**（写操作条数 vs 条目数），分开登记（K12）。
6. **`-U0` 的 hunk 头解析**在首版写成按第三个 `@@` 之后取范围 → 得到 0 个区间（`git status` 与 `git diff` 互相矛盾时才暴露）；
   同时发现二进制 diff 没有 `+++` 头。两条都写进 §四 第 12 条。
7. **`gitignore` 的隐私例外**原本只放行 `bench/scenarios/*/sessions/`，M2 的意图矩阵会话日志被 `sessions/` 规则吃掉
   → 追加 `!bench/intents/*/sessions/`（**同一套白名单纪律、同一套 `--check` 断言**，不是放松）。
8. **变异组 M15 的锚点与 M2 新代码同形**（`if key_path.startswith("observed")`），首跑报"未检出（假门！）"
   → 锚点补上下文。已写入 §四 第 14 条。

---

## 六、关键命令速查（**每条都在 M2 收尾时实跑过**）

```bash
# 安装（两个解释器各一次；--no-build-isolation 因本机 pip 代理易被污染）
py -3.12 -m pip install -e . --no-build-isolation --no-deps
py -3.8  -m pip install -e . --no-build-isolation --no-deps

# 全量测试（双解释器；先版本选择器再 -X utf8）
py -3.8  -X utf8 -m pytest -q
py -3.12 -X utf8 -m pytest -q

# 只跑 M2 的两组测试（改 intent 时先跑这个）
py -3.12 -X utf8 -m pytest tests/test_intent.py tests/test_intent_parse.py -q

# 离线冒烟（CI 与本地同一条通路；--strict 要求 console script 存在）
py -3.12 -X utf8 tools/verify_offline.py --strict

# 合成矩阵自检（CI 步骤；冲突矩阵 + 意图矩阵两层断言 + 提交 sha 复算 + 脏改动现场复核）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check

# 重建整棵矩阵（改生成器/体例后必须走这条）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --out bench

# 物化（M3 与人工复核用）：冲突场景 / 意图场景
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize same_symbol_diff_lines --dest out/scene
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize-intent intent_disk_wins --dest out/intent

# 守门变异验证（新增/改写守门后必跑；可 --only M17,M20 单跑）
py -3.12 -X utf8 tools/verify_mutation.py

# 看生效配置 / 自检 / 已交付命令
radar config
radar selftest
radar scan --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar intent --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z

# 未交付命令（当前应 exit 4）
radar detect --repo .
```

> **提示**：`radar` 与 `python -m agent_conflict_radar` 是两条通路（`sys.path` 来源不同）。
> 源码态未安装时用 `PYTHONPATH=src py -3.12 -X utf8 -m agent_conflict_radar <命令>`。
> 跑 `scan` / `intent` 时**务必**两侧都传 `--*-root`（见 §四 第 6 条）。
> 全局选项（`--config`）写在**子命令之前**：`radar --config path intent ...`。

---

## 七、M3 起点快照（2026-10-18，M2 收尾时冻结）

| 项 | 状态 |
|---|---|
| 命令面 | 已交付 4 条（`config` / `selftest` / `scan` / `intent`）；未交付 3 条（`detect` M3 / `report` M4 / `bench` M5） |
| 可直接复用的资产 | **`bench/scenarios/` 的七条冲突场景**（含两条已提交分支 + `git_expected_merge_exit`，`--check` 现场真跑 merge-tree 复核）——**M3 的矩阵对账就该用它们，别另造夹具**；`intent.IntentSet` 的 `entries[].writes[]`（逐会话区间 = 符号级比对的输入）；`gitio.run_readonly`（只读白名单已含 `merge-tree`）；`discover.Session.derived_from`（场景 4 的去重依据）；`serialize.write_atomic` |
| 需要新造 | `detect.py`、`tests/test_detect*.py`、CLI 接线 `_cmd_detect`、冒烟 detect 用例、README 状态表再退一项（**并注意退出码 1 第一次被真正使用**） |
| 真值的下一步 | M3 的检出对账**直接用 `bench/scenarios/*/truth.json` 的 `levels_expected` / `symbols_expected` / `objects_forbidden`**（已冻结、可独立复算）；**别在测试里手写一份期望** |
| 已知会被 M3 打中的形态 | `same_file_diff_symbol`（不同符号 → 只文件级）/ `same_symbol_diff_lines`（同符号 → 符号级，**git 自动合并成功**）/ `whole_file_overwrite`（三粒度齐全，merge-tree exit 1）/ `subagent_derived`（`derived_from` 去重 → 一条都不报）/ `negative_no_overlap`（空检出）/ `threshold_exact`+`threshold_near_miss`（相邻容差两侧） |
| 风险 | 三条风险（同类低星混战 / 符号级已被 `wit` 口头占位 / 本机真实并行样本为 0）**一条都没变**，M2 不改变其中任何一条；不得用真实样本数包装检出率 |
