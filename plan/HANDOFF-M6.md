# HANDOFF-M6：从 M5 续接到 M6（GitHub 发布）

**项目**：`agent-conflict-radar`（本地目录 `10-18-agent-conflict-radar`）
**上一棒**：M5 —— ✅ **完成**（2026-10-18）：`radar bench` 评分交付（15/15 场景 + 174 项检查）；
`EXIT_NOT_READY` 整条退役；`docs/技术报告.md` 落盘
**当前状态**：M0–M5 全部门禁在本机复核全绿（见 §五）
**本文件用途**：下一棒开工前**只需读本文件 + `plan/06` M6 节 + `plan/07` §四（K 清单）+ `docs/技术报告.md` §九**，
不依赖对话记忆
**启动方式（用户侧，绝对路径）**：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务`

---

## 一、当前进度与证据

### 1.1 已完成（M5 本体）

| 项 | 产物 | 证据（可复跑） |
|---|---|---|
| `radar bench` 评分 | `bench/score.py`（`run_bench` / `render_summary` / `write_last_run`）+ `cli._cmd_bench` | 整矩阵 **15/15 场景、174 项检查 0 失败**，exit 0；`tests/test_bench.py` 26 条 |
| 评分落点（与计划的偏差） | 计划 `bench.py` → 实际 `bench/score.py` | `agent_conflict_radar.bench` 已是包，同名模块被静默遮蔽（本机实测）。命令面仍是 `radar bench` |
| 逐场景 `期望 / 实际 / 判定` | `render_summary` 三列 | `test_human_readable_summary_shows_all_three_columns` |
| 集合精确匹配（多报/漏报均失败） | `_set_check` 输出 `missing` / `extra` | 5 条**消费处**探针（`test_bench_fails_when_*`） |
| 覆盖度门槛（消费侧复核） | `_check_manifest` / `_threshold_pair_check` | `test_coverage_gate_is_enforced_on_the_consumption_side` + `test_coverage_counts_the_whole_matrix_even_under_only` |
| `last_run.json`（K2/K17） | `write_last_run` → `serialize.write_atomic` | 冻结契约 / 双跑逐字节 / 机器无关 三条断言 |
| `--only` 抽检不覆盖整矩阵记录 | `cli._cmd_bench` 只在整矩阵跑时默认写盘 | `test_only_run_does_not_clobber_the_full_run_record`（覆盖前后逐字节比对） |
| `--only` 用法错误（exit 2） | 未知 id / 过滤后为空 | `test_unknown_only_id_is_a_usage_error` / `test_only_comma_on_the_cli_is_a_usage_error` |
| `bench` 退出码 0/1/2/3 | 全过 0、任一失败 1、用法 2、依赖 3 | 四条独立用例 + 三条冒烟 |
| **K1 退役四步** | 删 `EXIT_NOT_READY` / `StageNotReady` / `STAGE_NOT_READY` / `milestone_for` | `not hasattr` 三连 + 变异组 **M34** |
| 冒烟"未就绪"段整段退役 | `tools/verify_offline.py` 两段循环删除 | `test_smoke_tool_has_no_stage_not_ready_cases`（反向断言"一条都不许留"） |
| `last_run.json` 与 `--check` 的关系 | `gen.RUNTIME_PRODUCTS` 单名放行 | `test_check_tolerates_the_runtime_product_but_not_generator_products`（双向） |
| 技术报告 | `docs/技术报告.md` 十节 | 落盘；README 文档索引已收录 |
| `symbol.min_overlap_lines` 定论 | **遗留键，不消费** | `docs/技术报告.md` §九 + `report.py` 参数块已写明"不是判定阈值" |
| 文档回写 | `plan/00`（§十二）、`plan/04` 注⑨、`plan/05` §十、`plan/06` M5 收尾、`plan/07` §十一 + K1/K15 修订、README | 见 §五 逐项 |

### 1.2 本棒实测数字（不要照抄，下一棒收尾要**复测**）

| 项 | 值 |
|---|---|
| 测试数 | `py -3.8` 365 passed / 1 skipped；`py -3.12` 365 passed / 1 skipped |
| 跳过项 | `tests/test_paths_adaptive.py` 符号链接用例——文件系统不支持创建目录符号链接（声明式跳过，附原因） |
| 离线冒烟 | `--strict` 下 **38 用例全过**（模块 27 + 生成器自检 1 + console 10） |
| 变异验证 | **36 组**全部被对应守门抓到，仓库按字节还原 |
| 评分 | 15/15 场景、174 项检查、覆盖度达标、exit 0；整矩阵约 20s |
| 合成矩阵 | **M5 未新增场景、未改冻结产物**（`--check` 全过） |
| 包版本 | `0.0.1`（未变） |
| 命令面 | **7/7 全部交付**（`config` / `selftest` / `scan` / `intent` / `detect` / `report` / `bench`）；不再存在 exit 4 |

### 1.3 未做（明确不在 M5 范围，就是 M6 的活）

* `scripts/check_release.py`（离线 + `--online` 两模）**未写**。
* `MANIFEST.in` **未落**（`bench/` 白名单要进源码包）。
* `plan/RELEASE-M6.md` **未写**（按 DoD 必须在 tag **之前**写好并进 tag 树）。
* 远端动作**一次都没跑**：建仓 / push / CI 首跑 / tag / Release 全部属 M6，且**执行前要问用户**。
* `docs/技术报告.md` 标注"M6 定稿"——M6 只做定稿校对，**不得**凭空补未实测的结论。

---

## 二、下一棒（M6）待办

> M6 DoD 全文见 `plan/06-里程碑.md` M6 节。这里只列**执行顺序与依赖**。

1. **历史 = 工作树核对**：`git status --porcelain -z`（**一定加 `-z`**）/ `git log --oneline | head` /
   `git rev-list --count HEAD`。先在本地确认历史干净、没有把 `out/`、`.venv`、真实日志带进来。
2. **脱敏四步 + 产物扫描**：
   * 全仓扫描真实盘符路径 / `/Users/` / `/home/` / Real-UUID / 真实用户名 / 真实邮箱；
   * **提交元数据邮箱检查**（`git log --format='%ae %ce'`）——这是 M6 独有的漏点（代码干净不等于提交面干净）；
   * `bench/` 与 `docs/` 一并扫（M5 已扫过一遍，M6 再扫是为"提交面"兜底）。
3. **`MANIFEST.in`**：白名单覆盖 `bench/`（`recursive-include bench *.json *.py *.jsonl *.md` 之类的**精确**清单，
   不要 `graft` 整个目录——`bench/last_run.json` 是运行产物，是否入包要显式决定并写明）。
4. **`scripts/check_release.py`（离线 + `--online` 两模）**：
   * **刻意不进 CI**（它要在发布时手跑）；
   * **门自身要做变异验证**：检查项数 == 变异组数（否则"门看起来很多项，其实没在查"）；
   * `--online` 要有：仓库公开 / tag 指向 / CI 逐 job 全 success / 附件集合与登记一致 +
     **逐个下载复算 sha256**。
5. **`plan/RELEASE-M6.md`**：在 **tag 之前**写好并提交；tag 之后的事实单独分栏追加（"tag 后追加事实"），
   **不覆盖** tag 时刻的内容。
6. **建仓 → push → CI 首跑**：`gh repo create yuluo554/agent-conflict-radar --public`。
   **首跑失败照录不抹除**——这是 DoD 明写的一条。
7. **tag + Release**：
   * annotated tag 打在 **CI 绿的收尾提交**上；
   * **源码 zip 手工上传为附件**（不得以"仓库 zipball 即产物"替代），本地留同名副本 + sha256；
   * 真下载复核 → 中立目录解压跑 `selftest`（"解压即用"实证）。
8. **M6 DoD 验证 → 回写 `plan/00` / `plan/06` / `plan/07`（诚实口径尾注 §十二）→ commit**。
   M6 是最后一棒，**不写 HANDOFF-M7**。

### M6 必须遵守的口径（逐条对应既有 K）

| K | M6 的落点 |
|---|---|
| K1 | 退出码四语义**不再变**：M6 不得引入任何新码；`bench` 的 `1` 与 `detect` 的 `1` 语义区分靠措辞 |
| K2 | 发布脚本里的写盘同样走 `serialize.write_atomic`（不得另写一份 `open()+json.dump`） |
| K3 | 发布脚本若需要数值（阈值 / 超时），**只从 config 读**；脚本自身零策略数值字面量 |
| K7 | 发布留档里的时间戳必须是**真实 UTC 时刻**（这是唯一允许读系统时钟的地方——它是事件记录，不是产物判定） |
| K11 | 入库内容扫描的白名单口径不变（假 session id / 假用户名 / 固定基准时间） |
| K14 | 名字四向一致（README H1 / 仓库名 / `pyproject.name` / 包名）——发布前再并排读一遍 |
| K17 | 发布附件与 tag 树**逐字节同源**；zip 内不写自身 sha256（自指必过期） |

---

## 三、既定口径清单（K 编号，"动了会打挂测试"）

> 全文见 `plan/07-交付对标与决策记录.md` §四。**改任何一条都要五处同步**：代码 → 测试 → README → K 表 → 决策记录。
> M5 修订了两条：**K1**（`4` 整条退役，只剩四语义；`bench` 复用 `1` 但语义不同）、
> **K15**（最后一条命令交付后，"未就绪"的冒烟循环与参数化断言**整段删除**，不留空循环）。

| K | 一句话 |
|---|---|
| K1 | 退出码 **只有 `0/1/2/3`**；`4` 已于 M5 整条退役（含 `not hasattr` 防复活）；`bench` 的 `1` = 基准未达标，`detect`/`report` 的 `1` = 检出冲突 |
| K2 | 序列化冻结：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写；**唯一写盘点 `serialize.write_atomic`** |
| K3 | 数值唯一权威 `config/radar.toml`；代码**零内联默认值**，缺失/未知/类型不符一律报错（exit 3）；覆盖只走 `Config.with_override` |
| K4 | 只读：不 merge/rebase、不写索引、不改工作区；`merge-tree` 只允许 `--write-tree`（对象库临时对象**如实披露**） |
| K5 | 零内联阈值字面量门禁（`0`/`1` 之外必须登记 `ALLOWED_LITERALS` 或整文件豁免并写理由）+ 下层禁止 import 上层 |
| K6 | 底线解释器（3.8）缺能力 → 自写受限子集 + 超集形态**显式报错**，不静默跳过、不引运行时依赖 |
| K7 | 会话格式版本 = 显式指纹集合；未知版本 `unsupported_format` + 缺失键 + 点名文件 |
| K8 | 编码三加固：入口 `_ensure_utf8_stdio` + 子进程显式 `encoding=` + CI `PYTHONUTF8=1` |
| K9 | 真值只存"输入与期望"；出现 `observed_*` 即红；期望值必须可由输入独立复算 |
| K10 | 生成器 `--check` 两层断言（产物形态 + 重生成逐字节）；生成侧/生产侧规范序**各一份独立实现** |
| K11 | 合成数据白名单（M1 追加 `src/beta.py` / `src/filler.py` / `{{REPO_ROOT}}` / 假 author；M2 追加 `src/dup.py` / `docs/notes.md` / `sess-radar-0020`–`0026`）|
| K12 | 计数口径先声明：`by_max_level` 是**划分**（`sum == len(conflicts)`）+ `by_level_membership` 是**成员数**；报告里**分开呈现** |
| K13 | 报告渲染三律：零判定（AST）+ 零外链（常驻出口）+ 双跑逐字节；**单一渲染源** = payload 是事实面、Markdown 是纯函数 |
| K14 | 对外声称逐条有实物（许可/命令/extras/名字四向一致），由 `tests/test_readme_gate.py` 五面对账 |
| K15 | 每交付一条命令 → 同一次提交退役旧断言 + 补离线冒烟；**M5 起"未就绪"段整段删除，不留空循环** |
| K16 | 路径自适应；`expanduser` 解不出主目录时**按哨兵比对**报错——不写盘、不抛系统异常、不回落 CWD |
| K17 | **冻结产物机器无关**：`bench/` 一切文本不得含本机绝对路径；`last_run.json` 同样受此约束 |
| K18 | **真值里的阈值一律 config 符号引用**（`config_ref` / `const`），由 `--check` 现场求值 |
| K19 | **M2 落点三分法**（`exact`/`coarse`/`unknown`）+ 计数两口径 + 磁盘优先 + 定位基线恒为 `HEAD` |
| K20 | **M3 检出口径**：① 一条记录 = 一个 `(workspace_a, workspace_b, path)`；`levels` 是集合（必含 `file`）、`level` 只用于排序；真值按 `levels`/`symbols` **集合精确匹配**。② 三级判据。③ `degraded`/`approximate` 只降粒度、不改判定、不改码，都落 `undetermined`。④ 符号字段只在 `approximate=False` 时出现。⑤ 两侧 `derived_from` 相同 ⇒ 默认不产出且留痕。⑥ `A` 与 `A.f` 同时命中只报 `A.f` |

---

## 四、本机环境坑（**只写实测过的**；M5 新增四条）

1. **`py` 的标志顺序**：`py -3.8 -X utf8 -m ...` 正确；写成 `py -X utf8 -3.8 -m ...` 会报 `Unknown option: -3`。
2. **`Path.write_text(newline=)` 是 Python 3.10+ 参数**：底线 3.8 上 `TypeError`。写法一律
   `open(path, "w", encoding="utf-8", newline="\n")`。
3. **本机两条解释器通道**：`py -0p` → `3.8.8-64` 与 `3.12.10-64`（各装一份 editable 包）；
   PATH 上的 `radar` 是 **3.12** 那一份。
4. **`grep` 中文与 Git Bash 显示**：`git status --short` 显示八进制转义只是显示问题，用 `-c core.quotepath=false` 可读。
   ⚠️ `git status -c ...` 是**错的**（`-c` 要放在 `git` 后、子命令前）；且行模式下中文路径会被转义。
5. **临时目录**：一律 `tempfile.mkdtemp()`（Windows 侧路径），**不要**用 Git Bash 的 `/tmp`。
6. **⚠️ 只传一侧会话根 = 会去读真实用户日志**：凡"自动发现本机数据"的参数，测试与冒烟**一律两侧都显式传**
   （缺失的一侧传空目录）。`scan` / `intent` / `detect` / `report` 同一套规则。`bench` **不读用户会话根**——
   它只物化自己的合成场景。
7. **Windows 上 `shutil.rmtree` 会被 git 的只读对象文件挡住**：先 `chmod 0o700` 再删（`bench/gen.py` 的 `_rmtree`；
   `bench/score.py` 复用它，不复制常量）。
8. **同一份夹具别物化两次**：冒烟里 `_SCAN_FIXTURES` / `_INTENT_FIXTURES` / `_DETECT_FIXTURES` / `_REPORT_FIXTURES`
   四个缓存 **key 空间分开**——合成一个 dict 会互相覆盖。
9. **中文注释/字符串里别用 ASCII 双引号**：写文档脚本时用 `「」`；在双引号字符串里写 `"输入数据"` 直接 `SyntaxError`。
10. **门禁与实现冲突时，先问"是不是实现写得比判据更糙"**：M2/M3/M4 三次实例都走"扩词表 + 写理由"通道。
11. **零写盘纪律的实测方式**：新命令照抄既有测试形态——给一个**空的沙箱目录**当 CWD，跑完断言 `os.listdir` 为空。
    ⚠️ `bench` 是**唯一默认写盘**的命令（`last_run.json` 落矩阵目录），它的零污染判据是"**CWD 不落文件**"。
12. **`-U0` 的 hunk 头要按"第二个 `@@` 之前"解析**：`parts[1]` 才是范围。
13. **⚠️ `git status` 一定加 `-z`**：行模式下中文/特殊字符路径会被转义；rename/copy 会多跟一条原始路径记录。
14. **⚠️ 变异脚本的锚点要带上下文**：新增代码里出现与旧门禁**同形**的一行时，只锚那一行的变异会改到新代码上。
15. **⚠️ `git merge-tree --write-tree` 的冲突信息在 stdout，不在 stderr**（M3 实测）。
16. **⚠️ 冲突路径有两条来源，只认一条会漏**（M3）：三元组行 + `CONFLICT` 文案。
17. **⚠️ 只读断言别把 `.git/objects` 算进去**（M3）。
18. **⚠️"是不是同一个仓库"要用 `git rev-parse --git-common-dir`**（M3）：**别用路径前缀判**。
19. **⚠️ 一条判据可能有多道门**（M3）：变异要打"整段语义"。
20. **⚠️ 测试里比 stdout 与落盘产物要先归一 CRLF**（M3）：`raw.replace(b"\r\n", b"\n") == out.replace(...)`。
21. **⚠️ AST 门禁的 `ImportFrom` 有两条通路**（M4）：`from . import detect` 的 `node.module` 是 `None`，
    模块名在 `alias.name` 里。**文本/结构类门禁第一轮必须配注入探针**。
22. **⚠️ Windows 没有零依赖的桌面通知通道**（M4）：本机 `report.notify=true` 的真实结果是 `notify_unavailable`
    ——**如实登记**，不是缺陷。
23. **⚠️ 报告的证据截断要留痕**（M4）：`report.max_evidence_items` 生效时写明"…另有 N 条"。
24. **⚠️ `agent_conflict_radar.bench` 是包**（M5）：**不能**再放 `bench.py`——同目录同名模块会被包静默遮蔽
    （本机实测：`import pkg.bench` 拿到 `pkg/bench/__init__.py`）。评分在 `bench/score.py`。
25. **⚠️ 覆盖度必须按整棵矩阵算**（M5）：`--only` 只该影响"跑哪些场景"。用过滤后的子集算覆盖度，
    会让单跑一条报"缺类"——那是把"只跑一条"误判成"矩阵坏了"。
26. **⚠️ `bench --only ","` 的解析**（M5）：CLI 侧 `split(",")` 得到 `["", ""]`；API 侧要能识别
    "过滤后为空"并抛 `UsageError`（exit 2），不能当成"零条通过"。
27. **⚠️ 干净 venv 里 `pip install -e . --no-build-isolation` 会失败**（M5 实测）：
    新 venv 没有 setuptools → `BackendUnavailable: Cannot import 'setuptools.build_meta'`。
    干净环境用**默认构建隔离**（`pip install -e ".[dev]"`）即可；`--no-build-isolation` 只适用于
    本机已装 setuptools 的老环境。

---

## 五、DoD 逐项 checklist（M5，已逐项验证）

* [x] **全场景通过**：`radar bench` → 15/15、174 项检查 0 失败、exit 0；逐场景 `期望/实际/判定`
* [x] **双边门**：`missing` / `extra` 分别成项、均计失败；反向样例单列；覆盖度在消费侧复核
* [x] **可证伪探活（打消费处）**：5 条探针全部走 `run_bench()`；变异组 M35 把 `missing` 恒置空 → 探针必红
* [x] **覆盖度**：两棵树 `missing_types` 空；`min_count_by_type` 全达标；`sampling_notice` 声明非穷举
* [x] **K1 退役四步**：删常量/错误类/表/`milestone_for` → CLI + 测试 + `not hasattr` 三连 → README → 决策记录；
      变异组 M34 专打复活
* [x] **K15 冒烟退役**：`verify_offline.py` 两段"未就绪"循环整段删除；反向断言"一条都不许留"
* [x] **`last_run.json`**：冻结序列化 + 双跑逐字节 + 机器无关；`--check` 单名放行（双向测试）
* [x] **退出码 0/1/2/3 各有实物**：全过 0 / 任一失败 1 / 用法 2 / 依赖 3；失败路径 `stdout == b""`
* [x] **矩阵补全结论**：不需要补（逐类核对达标）；**未改冻结产物**
* [x] **`min_overlap_lines` 定论**：遗留键，文档与报告都写明"不是判定阈值"
* [x] **干净 venv + 干净 clone（`--no-local`）**：`pip install -e ".[dev]"` → `--version` / `config` /
      `selftest` / `bench` / `bench --only` / `bench --out-dir` / 生成器 `--check` 全过；
      冒烟 38/38；整矩阵跑完 `git status` 干净（`last_run.json` **逐字节复现**）
* [x] **隐私审计**：真实盘符路径 / `/Users/` / `/home/` / Real-UUID / 真实用户名 零命中；零网络导入面通过
* [x] **桩哨兵**：0 命中（唯一 `NotImplementedError` 是测试里的捕获分支，已解释）
* [x] **双解释器全量 pytest**：各 365 passed / 1 skipped
* [x] **变异验证**：36 组全检出（M4 为 33）
* [x] **技术报告**：`docs/技术报告.md` 十节落盘
* [x] **`HANDOFF-M6.md`（本文件）**：六节 + 起点快照，库内相对路径、无本机绝对路径

**偏差说明**（如实记录，不做美化）：见 `plan/06-里程碑.md` M5 收尾结论 +
`plan/07` §十一 的 8 条决策与 5 条"等价缺口"。**摘要**：

1. 评分落点是 `bench/score.py`，不是计划写的 `bench.py`（包名冲突，本机实测）。
2. `bench` 与 `detect` 共用退出码 `1`，语义区别靠人读输出措辞与 README（K1 四语义的约束）。
3. 覆盖度按整棵矩阵算，不受 `--only` 影响（否则单跑一条会误报缺类）。
4. `last_run.json` 是运行产物，`--check` 单名放行；另有双向测试防"整个比对面被关掉"。
5. `symbol.min_overlap_lines` 定为遗留键（不消费），`derived_from` 提示开关仍未落地。

---

## 六、关键命令速查（**每条都在 M5 收尾时实跑过**）

```bash
# 安装（两个解释器各一次；本机老环境用 --no-build-isolation，新 venv 不要加）
py -3.12 -m pip install -e . --no-build-isolation --no-deps
py -3.8  -m pip install -e . --no-build-isolation --no-deps

# 干净环境（M6 复核用；默认构建隔离）
py -3.12 -m venv <venv 路径>
<venv 路径>/Scripts/python.exe -m pip install -e ".[dev]"

# 全量测试（双解释器；先版本选择器再 -X utf8）
py -3.8  -X utf8 -m pytest -q
py -3.12 -X utf8 -m pytest -q

# 只跑 M5 的测试（改 bench 时先跑这个；全矩阵约 3 分钟）
py -3.12 -X utf8 -m pytest tests/test_bench.py -q

# 离线冒烟（CI 与本地同一条通路；--strict 要求 console script 存在）
py -3.12 -X utf8 tools/verify_offline.py --strict

# 合成矩阵自检（CI 步骤；last_run.json 作为运行产物单名放行）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check

# 重建整棵矩阵（改生成器/体例后必须走这条）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --out bench

# 物化（人工复核用）：冲突场景 / 意图场景
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize whole_file_overwrite --dest out/scene
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize-intent intent_disk_wins --dest out/intent

# 守门变异验证（新增/改写守门后必跑；可 --only M34,M35 单跑）
py -3.12 -X utf8 tools/verify_mutation.py

# 评分（整矩阵 / 单场景 / 落产物）
radar bench
radar bench --only same_symbol_diff_lines
radar bench --bench-dir bench --out-dir out

# 看生效配置 / 自检 / 已交付命令
radar config
radar selftest
radar scan   --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar intent --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar detect --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z   # 有冲突 → exit 1
radar report --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z   # 有冲突 → exit 1
radar report --repo . --out-dir out --format both     # out/report.md + out/conflicts.json
```

> **提示**：`radar` 与 `python -m agent_conflict_radar` 是两条通路（`sys.path` 来源不同）。
> 源码态未安装时用 `PYTHONPATH=src py -3.12 -X utf8 -m agent_conflict_radar <命令>`。
> 跑 `scan` / `intent` / `detect` / `report` 时**务必**两侧都传 `--*-root`（见 §四 第 6 条）。
> 全局选项（`--config`）写在**子命令之前**：`radar --config path report ...`。
> **退出码提示**：`detect` / `report` 返回 1 是**成功检出**；`bench` 返回 1 是**基准未达标**——
> 两者都是"非 0 不等于跑挂"，但语义不同（`set -e` 的脚本里要分别接住）。

---

## 七、M6 起点快照（2026-10-18，M5 收尾时冻结）

| 项 | 状态 |
|---|---|
| 命令面 | **7/7 全部交付**；退出码只有 `0/1/2/3` |
| 评分 | `radar bench` 整矩阵 15/15、174 项检查、exit 0；`bench/last_run.json` 已生成（约 60KB） |
| 可直接复用的资产 | `bench.score.run_bench()` / `render_summary()` / `write_last_run()`；`bench.gen.{scenario_ids,scenario_by_id,materialize_scenario,intent_scenario_by_id,materialize_intent_scenario,check}`；`detect.build_conflict_set()`；`report.ReportSurface`；`serialize.*`；`config.Config.get` / `with_override`；`RUNTIME_PRODUCTS` |
| 需新造（M6） | `scripts/check_release.py`（离线 + `--online`）、`MANIFEST.in`、`plan/RELEASE-M6.md`、tag / Release / 附件 / sha256 留档 |
| 硬约束（别踩） | 远端动作**先问用户**；首跑失败**照录不抹除**；源码 zip 必须**手工上传为附件**，不得用 zipball 替代；留档写在 tag **之前**；zip 内不写自身 sha256 |
| 风险 | 三条风险（同类低星混战 / 符号级已被 `wit` 口头占位 / 本机真实并行样本为 0）**一条都没变**；M5 不改变其中任何一条；不得用真实样本数包装检出率 |
