# HANDOFF-M2：从 M1 续接到 M2（意图提取）

**项目**：`agent-conflict-radar`（本地目录 `10-18-agent-conflict-radar`）
**上一棒**：M1 —— ✅ **完成**（2026-10-17）：`radar scan` 交付 + 合成冲突矩阵入仓（生成器 / 真值 / 覆盖度台账 / 两层 `--check`）
**当前状态**：M1 已交付，工作树干净，M0 + M1 全部门禁在本机复核全绿（见 §五）
**本文件用途**：下一棒开工前**只需读本文件 + `plan/00`·`04`·`05`·`07` + `data/README.md` §六**，不依赖对话记忆
**启动方式（用户侧，绝对路径）**：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务`

---

## 一、当前进度与证据

### 1.1 已完成

| 项 | 产物 | 证据（可复跑） |
|---|---|---|
| `radar scan` 交付（K15 四步走完） | `discover.py` + `cli._cmd_scan` + `config.Config.with_override` | `tests/test_discover.py`（16 条）+ `tests/test_scan_cli.py`（12 条）+ 冒烟两条通路各 1 条 scan 用例 |
| 端到端确定性 | `--now` 显式传 → 双跑逐字节一致；`--out-dir` 落 `scan.json` 与 stdout 同字节 | `test_scan_is_byte_identical_across_two_real_processes` / `test_scan_out_dir_writes_scan_json_with_identical_bytes` |
| 合成冲突矩阵（7 条场景） | `bench/`（manifest + scenarios/*/{repo,sessions,truth.json}） | `py -X utf8 -m agent_conflict_radar.bench.gen --check` |
| 生成器两层 `--check` + 提交 sha 复算 + merge-tree 现场复核 | `bench/gen.py`（+ `bench/rng.py` 确定性 RNG） | 同上；`tests/test_bench_matrix.py`（26 条） |
| 真值可脱离引擎独立复算 | `truth.json` 的 `geometry` + `levels_expected`/`symbols_expected` + `objects_forbidden` | `test_expectations_are_recomputable_without_the_detection_engine`（**不 import 引擎**） |
| 门禁补充 | 3 个新测试文件（54 条用例）+ 冒烟 25 用例 + CI 新增"矩阵自检"步骤 + 变异组 M11–M16 | 见 §六 命令速查 |
| 文档回写 | `plan/00`（索引/台账/里程碑/§八）、`plan/04`（M1 勘误注）、`plan/05`（布局修正/白名单/§八）、`plan/06`（M1 收尾结论）、`plan/07`（12 条决策记录 + K17/K18）、`data/README` §三/§五/§6.5、README | 本文件 §五 逐项 |

### 1.2 本棒实测数字（不要照抄，下一棒收尾要**复测**）

| 项 | 值 |
|---|---|
| 测试数 | `py -3.8` 179 passed / 1 skipped；`py -3.12` 179 passed / 1 skipped |
| 跳过项 | `tests/test_paths_adaptive.py` 符号链接用例——当前文件系统不支持创建目录符号链接（声明式跳过，附原因） |
| 离线冒烟 | `--strict` 下 **25 用例全过**（模块通路 10 + 生成器自检 1 + console 通路 8 + 其余 6 为用法/环境类） |
| 变异验证 | **16 组**全部被对应守门抓到，仓库按字节还原 |
| 合成矩阵 | 7 条场景 / 6 个覆盖类型（`missing_types` 为空）/ 真值 sha256 与台账一致 |
| 包版本 | `0.0.1`（未变） |

### 1.3 未做（明确不在 M1 范围，就是 M2 的活）

* `intent` / `detect` / `report` / `bench` 四条命令**仍 exit 4**（`stages.STAGE_NOT_READY` 里）。
* `radar bench` 的**评分**属 M5；M1 只交付了矩阵本体。
* R4（非 Python 文件的符号级近似口径）**未闭环**——M2 的活。
* `docs/技术报告.md`（M5）、`scripts/check_release.py`（M6）、`MANIFEST.in`（M6）。

---

## 二、下一棒（M2）待办

> M2 DoD 全文见 `plan/06-里程碑.md` M2 节。这里只列**执行顺序与依赖**。

1. **`intent.py` 实现**（`plan/04` M2 节）：把会话里的写操作解析成"文件集合 + 改动行区间"。
   * Claude 侧：`message.content[]` 中 `type == "tool_use"` 的项，`name ∈ {Edit, Write, MultiEdit}`；
     `Edit` 用 `old_string` **在基线里定位**行区间（注意：`old_string` 可能多处命中 → 必须显式降级，不许挑第一个）；
   * Codex 侧：`response_item.payload` 的 `type == "custom_tool_call"` 且 `name == "apply_patch"`，
     `input` 是**字符串**，按 `*** Update File:` / `*** Add File:` / `*** Delete File:` 指令行解析；
     另有经 `exec` 下发的同形变体（R2 已闭环）——**两种形态都要正例与反例**；
   * `MultiEdit`：本机 **0 次出现**（R3）→ 落 `unknown` + 计注记，**不得假装支持**。
2. **三分法落点**：`exact` / `coarse` / `unknown`。`replace_all=True` → `coarse`（没有"看起来精确"的区间）；
   `file_path` 缺失 → `unknown` + 计数。**计数恒等式**要写成测试。
3. **与 `git status` / `git diff` / `git diff --cached` 对账**：改动以磁盘为准（会话是意图，磁盘是事实）。
4. **R4 闭环**：非 Python 文件的符号级一律 `approximate=True` + `symbol=None`，不进符号级判定。
5. **非 git 工作区**：会话 `cwd` 落在任何 worktree 之外是**正常情形**（本机 37 个改文件的会话里只有 7 个在 git 内）——
   显式处理，不崩、不伪造冲突。
6. **`radar intent` 交付**：K15 四步（`stages.py` 挪表 → CLI 接线 + 测试同步（含"逐条已交付命令不得残留在未就绪表"）→
   冒烟期望值改真实契约 + 补一条 → README 状态表/退出码表）；产物 `intent.json` 经 `serialize.write_atomic`。
7. **确定性**：`--now` 语义沿用 scan（intent 也吃 `--now`，旗标已在 `add_repo_options` 里注册）；双跑逐字节一致。
8. **收尾**：M2 DoD 验证 → 回写 `plan/00` / `plan/05`（R4）/ `plan/06` / `plan/07`（决策记录 + K 表）→
   写 `HANDOFF-M3.md` → commit。

### M2 必须遵守的降级纪律

| 情形 | 允许的行为 | 禁止的行为 |
|---|---|---|
| `old_string` 在基线里多处命中 | 落 `unknown`/`coarse` 并在产物里点名 | 挑第一个命中当真值 |
| `replace_all=True` | `coarse` + 明确"无精确区间" | 编一个"看起来精确"的区间 |
| `MultiEdit`（本机 0 次出现） | `unknown` + 计注记（known-name 占位） | 假装支持、或静默丢弃不计 |
| 非 Python 文件 | 行区间近似 + `approximate=True` + `symbol=None` | 假装做了符号级 |
| 会话 `cwd` 不在任何 worktree | 显式处理（保留原值 + 标记） | 崩溃、或丢弃该会话 |
| 磁盘与会话不一致 | 以磁盘为准 + 在产物里说明 | 以会话为准覆盖磁盘事实 |

---

## 三、既定口径清单（K 编号，"动了会打挂测试"）

> 全文见 `plan/07-交付对标与决策记录.md` §四。**改任何一条都要五处同步**：代码 → 测试 → README → K 表 → 决策记录。
> M1 新增两条：**K17**（冻结产物机器无关：占位符 `{{REPO_ROOT}}`、不冻 `.git`、复算提交 sha）、
> **K18**（真值里的阈值一律 config 符号引用，`--check` 现场求值）。

| K | 一句话 |
|---|---|
| K1 | 退出码 `0/1/2/3/4`；`4` 随命令交付逐项退役，四步同步（`scan` 已在 M1 退役） |
| K2 | 序列化冻结：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写；**唯一写盘点 `serialize.write_atomic`** |
| K3 | 数值唯一权威 `config/radar.toml`；代码**零内联默认值**，缺失/未知/类型不符一律报错（exit 3）；覆盖只走 `Config.with_override`（内存视图，不写盘） |
| K4 | 只读：不 merge/rebase、不写索引、不改工作区；`merge-tree` 只允许 `--write-tree`（对象库临时 tree **如实披露**）。**生成器例外**：它只造**自己临时目录里的合成仓库**，故直接调 `git init/add/commit`（见 `bench/gen.py` 模块文档） |
| K5 | 零内联阈值字面量门禁（`0`/`1` 之外必须登记 `ALLOWED_LITERALS` 或整文件豁免并写理由）+ 下层禁止 import 上层 |
| K6 | 底线解释器（3.8）缺能力 → 自写受限子集 + 超集形态**显式报错**，不静默跳过、不引运行时依赖 |
| K7 | 会话格式版本 = 显式指纹集合；未知版本 `unsupported_format` + 缺失键 + 点名文件 |
| K8 | 编码三加固：入口 `_ensure_utf8_stdio` + 子进程显式 `encoding=` + CI `PYTHONUTF8=1` |
| K9 | 真值只存"输入与期望"；出现 `observed_*` 即红；期望值必须可由输入独立复算；生成器与真值同步产出 |
| K10 | 生成器 `--check` 两层断言（产物形态 + 重生成逐字节）；规范序生成侧/生产侧**各一份独立实现** |
| K11 | 合成数据白名单（M1 追加 `src/beta.py` / `src/filler.py` / `{{REPO_ROOT}}` / 假 author） |
| K12 | 计数口径先声明"条目数 vs 命中记录数"；`sum(by_level) == len(conflicts)` 写成集合划分恒等式 |
| K13 | 报告渲染三律：零判定 + 零外链（断言常驻渲染出口）+ 双跑逐字节一致 |
| K14 | 对外声称逐条有实物（许可/命令/extras/名字四向一致），由 `tests/test_readme_gate.py` 五面对账 |
| K15 | 每交付一条命令 → 同一次提交退役其旧断言 + 补离线冒烟；`python -m` 与裸 `radar` 两条通路都冒烟 |
| K16 | 路径自适应；`expanduser` 解不出主目录时**按哨兵比对**报错——不写盘、不抛系统异常、不回落 CWD |
| K17 | **冻结产物机器无关**：`bench/` 一切文本不得含本机绝对路径（会话根写 `{{REPO_ROOT}}`）；`.git` **不入**冻结产物；提交可复现靠**复算 sha** |
| K18 | **真值里的阈值一律 config 符号引用**（`config_ref` / `const`），由 `--check` 现场求值；真值里不得出现策略数值键名 |

---

## 四、本机环境坑（**只写实测过的**）

1. **`py` 的标志顺序**：`py -3.8 -X utf8 -m ...` 正确；写成 `py -X utf8 -3.8 -m ...` 会报 `Unknown option: -3`。
   一律：**先版本选择器，再 `-X utf8`**。
2. **`Path.write_text(newline=)` 是 Python 3.10+ 参数**：底线 3.8 上 `TypeError`。
   写法一律 `open(path, "w", encoding="utf-8", newline="\n")`；`tests/conftest.py` 有 `write_lf` 夹具与 `write_lf_text()`。
3. **本机两条解释器通道**：`py -0p` → `3.8.8-64` 与 `3.12.10-64`。两者**已各装一份 editable 包**；
   PATH 上的 `radar` 是 **3.12** 那一份（3.8 的 `Scripts` 不在 PATH）。不要把"3.8 通道的 console 冒烟"写成
   "两版本各自验了两条通路"——它实际由 3.12 的脚本执行。
4. **`O` 型坑：`grep` 中文与 Git Bash 显示**：`git status --short` 显示中文文件名为八进制转义，只是显示问题。
5. **临时目录**：一律用 `tempfile.mkdtemp()`（Windows 侧路径），**不要**用 Git Bash 的 `/tmp`
   （与 Windows Python 不互通）。
6. **⚠️ 只传一侧会话根 = 会去读真实用户日志**（M1 实测踩到）：`scan --claude-root X` 时另一侧的
   `codex` 会走"常见位置探测"落到 `~/.codex/sessions`，本机实测读进 **125 个真实会话文件**。
   处置：**测试与冒烟一律两侧都显式传**（场景里没有该源时传一个空目录）。
   凡是"自动发现本机数据"的参数，测试必须把探测面钉死。
7. **Windows 上 `shutil.rmtree` 会被 git 的只读对象文件挡住**：git 落在 `.git/objects` 里的文件带只读位，
   直接 `rmtree` 报 `PermissionError: [WinError 5]`（重跑物化到同一目录时必现）。
   `bench/gen.py` 的 `_rmtree()` 先 `chmod 0o700` 再删——写自己的工具时照此办理。
8. **同一份夹具别物化两次**：`tools/verify_offline.py` 的 `build_cases` 与 `console_script_cases` 共用
   `_SCAN_FIXTURES` 缓存（都拿 `repo_dir` 当 key）。不缓存会互相删目录（叠加第 7 条 → 偶发失败）。
9. **中文注释/字符串里别用 ASCII 双引号**：`"...「输入数据」..."` 用 `「」`；
   在双引号字符串里写 `"输入数据"` 会直接 `SyntaxError`（本棒在测试与变异脚本里各踩一次）。
10. **门禁与实现冲突时，先问"是不是实现写得比判据更糙"**：本棒实测——`--check` 的"本机路径片段"模式表
    写成 `"/home/"` 这类成品片段，与 K16 门禁（"源码里不得出现该片段"）冲突。**正解不是给门禁开例外**，
    而是把模式表拆成 `目录名 × 分隔符`（判据反而更全）。同类：README 里 `python -m agent_conflict_radar.bench.gen`
    会被 `test_readme_gate.py` 的抽取器当成"没有可识别子命令"——因为它**不是** `radar` 子命令，
    所以那条命令写在**正文行内代码**里，不进围栏代码块（抽取器只看围栏块）。
11. **零写盘纪律的实测方式**：`tests/test_scan_cli.py::test_scan_creates_no_intermediate_files_without_out_dir`
    在临时 CWD 里断言"零文件产生"（含临时文件）。做 `intent` 时照抄这条形态。

---

## 五、DoD 逐项 checklist（M1，已逐项验证）

* [x] **归集正确**：`radar scan` 对合成矩阵物化出的仓库/会话产出稳定表；worktree 集合 / 会话 `cwd`·`branch`·`seq` /
  subagent `derived_from` / `in_worktree` 逐字段对账（`tests/test_scan_cli.py` + `tests/test_discover.py`）
* [x] **未知格式不静默**：缺键日志 → `unsupported_format` + 列出缺失键 + 点名文件，且该文件**不进** `sessions`
* [x] **源缺失不伪造**：显式会话根不存在 → exit 3 且 **stdout 为空**；`--repo` 不在 git 仓库内 → exit 3
* [x] **确定性**：同输入双跑逐字节一致（进程内 + 真子进程端到端）；落盘 `scan.json` 与 stdout 同字节
* [x] **矩阵可重建**：`bench/gen.py --check` 两层断言全过（冻结产物形态 + 重生成逐字节）+ 提交 sha 复算 +
  七条场景的 merge-tree exit 现场复核
* [x] **真值可复算**：无 `observed_*`（两侧断言）；`test_expectations_are_recomputable_without_the_detection_engine`
  **不 import 引擎**，只用 `repo/` 原文 + 几何 + config 重新推出期望
* [x] **退出码退役**：K1 四步走完（stages / CLI / 测试含反幽灵断言 / 冒烟期望值 / README / 决策记录）
* [x] **白名单与隐私**：冻结产物零真实 UUID / 零本机绝对路径 / 时间戳全部 `2026-01-01T` 起（测试断言）
* [x] **双解释器全量 pytest**：各 **179 passed / 1 skipped**（跳项附原因）
* [x] **离线冒烟 `--strict`**：**25 用例**全过（两条通路 + 生成器自检 + 零网络导入面审计）
* [x] **变异验证**：**16 组**全部被对应守门抓到，仓库按字节还原
* [x] **既有门禁修正（修门不是放宽门）**：冒烟的"命令覆盖自检"原判据恒真 → 改为真判据 + 可证伪断言 + 变异组 M14
* [x] **CI：本地等价校验（未接远端，CI 待首推验证）**——新增"矩阵自检"步骤只在本地按同一条命令复跑过
* [x] **`HANDOFF-M2.md`（本文件）**：六节 + 起点快照，库内相对路径、无本机绝对路径

**偏差说明**（如实记录，不做美化）：

1. `plan/05` §二 初稿的 `repo.git/` 改为 `repo/`（`.git` 字节跨平台不可复现）→ 改用"复算提交 sha"；落 K17。
2. M0 决策记录里的"`--now` 全局选项"措辞修正为**子命令选项**（口径不变）。
3. 冒烟的覆盖自检判据原为恒真（假门）→ 一次性修正 + 加可证伪断言。
4. 第 7/8/9/10 条环境坑都是本棒实测踩出来的，已写进 §四。
5. **一次"隐私近失"已如实记录**（§四 第 6 条）：它没有造成任何入库（真实路径只出现在终端输出里，
   未写入任何产物），但属于"测试必须钉死探测面"的硬教训，故留档。

---

## 六、关键命令速查（**每条都在 M1 收尾时实跑过**）

```bash
# 安装（两个解释器各一次；--no-build-isolation 因本机 pip 代理易被污染）
py -3.12 -m pip install -e . --no-build-isolation --no-deps
py -3.8  -m pip install -e . --no-build-isolation --no-deps

# 全量测试（双解释器；先版本选择器再 -X utf8）
py -3.8  -X utf8 -m pytest -q
py -3.12 -X utf8 -m pytest -q

# 离线冒烟（CI 与本地同一条通路；--strict 要求 console script 存在）
py -3.12 -X utf8 tools/verify_offline.py --strict

# 合成矩阵自检（CI 步骤；两层断言 + 提交 sha 复算 + merge-tree exit 现场复核）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check

# 重建整棵矩阵（改生成器/体例后必须走这条）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --out bench

# 把某条场景物化成真 git 仓库 + 真会话（M2/M3 与人工复核用）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize same_symbol_diff_lines --dest out/scene

# 守门变异验证（新增/改写守门后必跑；可 --only M3,M5 单跑）
py -3.12 -X utf8 tools/verify_mutation.py

# 看生效配置 / 自检 / 已交付命令
radar config
radar selftest
radar scan --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z

# 未交付命令（当前应 exit 4）
radar intent --repo .
```

> **提示**：`radar` 与 `python -m agent_conflict_radar` 是两条通路（`sys.path` 来源不同）。
> 源码态未安装时用 `PYTHONPATH=src py -3.12 -X utf8 -m agent_conflict_radar <命令>`。
> 跑 `scan` 时**务必**两侧都传 `--*-root`（见 §四 第 6 条）。

---

## 七、M2 起点快照（2026-10-17，M1 收尾时冻结）

| 项 | 状态 |
|---|---|
| 命令面 | 已交付 3 条（`config` / `selftest` / `scan`）；未交付 4 条（`intent` M2 / `detect` M3 / `report` M4 / `bench` M5） |
| 可直接复用的资产 | `bench/gen.py` 的 `materialize_scenario()`（造真仓库 + 真会话，M2 解析的输入就靠它）；`discover.Session`（含 `file`/`seq`/`session_key`）；`versions.py` 的实测字段表；`serialize.write_atomic` |
| 需要新造 | `intent.py`、`tests/test_intent*.py`、CLI 接线 `_cmd_intent`、冒烟 intent 用例、README 状态表再退一项 |
| 真值的下一步 | M2 的合成用例期望（`exact`/`coarse`/`unknown` 三分法与行区间）应在 `bench/` 里同步产出（K9：生成器与真值同步产出，禁手补）。**别在测试里手写一份期望** |
| 已知会被 M2 打中的形态 | `Edit` 的 `old_string` 可能**多处命中**（基线里重复行）；`Write` 是整文件；Codex `apply_patch` 的路径在 `*** Update File:` 指令行里；`exec` 变体同形 |
| 风险 | 三条风险（同类低星混战 / 符号级已被 `wit` 口头占位 / 本机真实并行样本为 0）**一条都没变**，M2 不改变其中任何一条；不得用真实样本数包装检出率 |
