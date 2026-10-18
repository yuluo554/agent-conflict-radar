# HANDOFF-M4：从 M3 续接到 M4（预警报告）

**项目**：`agent-conflict-radar`（本地目录 `10-18-agent-conflict-radar`）
**上一棒**：M3 —— ✅ **完成**（2026-10-18）：`radar detect` 交付（三级检出对冻结真值精确匹配 + `derived_from` 去重 + 只读指纹断言）+ 退出码 **1 首次真正上岗**
**当前状态**：M0 + M1 + M2 + M3 全部门禁在本机复核全绿（见 §五）
**本文件用途**：下一棒开工前**只需读本文件 + `plan/00`·`04`·`05`·`07` + `data/README.md` §6.7**，不依赖对话记忆
**启动方式（用户侧，绝对路径）**：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务`

---

## 一、当前进度与证据

### 1.1 已完成（M3 本体）

| 项 | 产物 | 证据（可复跑） |
|---|---|---|
| `radar detect` 交付（K15 四步走完） | `detect.py` + `gitio.merge_tree` / `parse_merge_tree_conflicts` / `git_common_dir` + `cli._cmd_detect` | `tests/test_detect.py`（32 条）+ `tests/test_detect_parse.py`（21 条）+ 冒烟两条通路各 1 条 |
| 三级检出**精确匹配**（多报/漏报均失败） | 七条冻结场景逐条对账 | `test_detect.py::test_scenario_detects_to_the_frozen_truth`（7 条参数化）：`levels`/`symbols` **集合相等** + 与 `levels_forbidden`/`symbols_forbidden` 不交 + `objects_forbidden` 零命中 + `objects_expected` 全在场 |
| 符号级 AST（限定名 / 嵌套 / 相邻容差 `<=`） | `detect.symbol_spans` / `pair_symbol_hit` / `range_gap` | 场景 2/3/6a 命中、6b 不命中；`threshold_exact` 与 `threshold_near_miss` **成对**卡在容差两侧（`plan/05` §4.2） |
| `derived_from` 去重（场景 4） | 两侧 `derived_from` 相同 ⇒ 不产出该对 | 场景 4 空检出 + `counts.derived_sibling_pairs_skipped == 1`（**留痕**）；端到端合成用例（Claude `isSidechain`） |
| 只读断言（K4 加固） | 跑完工作区每文件 + `.git/index` + `.git/HEAD` 的 sha256 指纹不变、分支不变 | `test_detect_is_read_only_for_worktree_and_index`；对象库临时对象的边界由 `test_readonly_boundary_is_disclosed_in_the_product` 断言"如实披露" |
| 计数两栏（K12） | `by_max_level` 是**划分**（`sum == len(conflicts)`，`_counts()` 内即断言）、`by_level_membership` 是**成员数** | `test_counts_are_a_set_partition_and_a_membership_count` + `test_membership_count_exceeds_entry_count_when_one_record_hits_two_levels` |
| 三态各有合成用例 | `degraded` / `approximate` / `unsupported_format` | `test_detect_parse.py` 手造最小夹具（**不动冻结矩阵**）：配置关闭试合并 / 孤儿分支 exit 128 / 无 `gitBranch` / 非 Python / 基线语法错 / 跨 worktree / 坏会话文件 |
| 退出码 **1** 首次真正上岗 | `detect` 有冲突 → 1、无冲突 → 0 | `test_cli_exit_codes_track_conflicts_and_undetermined_never_changes_them` + 冒烟 `module:detect` 期望值 1 |
| 门禁补充 | 2 个新测试文件（53 条用例）+ 冒烟 29 用例 + 变异组 M23–M29（并改锚 M4） | 见 §六 命令速查 |
| 文档回写 | `plan/00`（索引/台账/里程碑/§十）、`plan/02`（FR 表状态翻正 + 勘误）、`plan/04`（M3 九条勘误注）、`plan/05`（§十 检出对账）、`plan/06`（M3 收尾结论）、`plan/07`（8 条决策记录 + K1/K4/K12 修订 + **K20** + §九）、`data/README` §6.7、README | 本文件 §五 逐项 |

### 1.2 本棒实测数字（不要照抄，下一棒收尾要**复测**）

| 项 | 值 |
|---|---|
| 测试数 | `py -3.8` 299 passed / 1 skipped；`py -3.12` 299 passed / 1 skipped |
| 跳过项 | `tests/test_paths_adaptive.py` 符号链接用例——当前文件系统不支持创建目录符号链接（声明式跳过，附原因） |
| 离线冒烟 | `--strict` 下 **29 用例全过**（模块通路 19 + 生成器自检 1 + console 通路 8 + 其余 1 为 `--gen-check--` 类） |
| 变异验证 | **29 组**全部被对应守门抓到，仓库按字节还原 |
| 合成矩阵 | **M3 未新增场景、未改冻结产物**：冲突 7 条 + 意图 8 条，两棵树的 `missing_types` 均为空、提交 sha 可复算 |
| 包版本 | `0.0.1`（未变） |
| 命令面 | 已交付 5 条（`config`/`selftest`/`scan`/`intent`/`detect`）；未交付 2 条（`report` M4 / `bench` M5） |

### 1.3 未做（明确不在 M3 范围，就是 M4 的活）

* `report` / `bench` 两条命令**仍 exit 4**（`stages.STAGE_NOT_READY` 里）。
* `report.py`（Markdown + JSON 双轨、严重度排序、建议模板、`undetermined` 独立小节、参数来源块、
  可选通知 + `notify_unavailable`）：**全未开始**。
* `radar bench` 的**评分**属 M5；`docs/技术报告.md`（M5）、`scripts/check_release.py`（M6）、
  `MANIFEST.in`（M6）仍未落。
* `derived_from` 的"提示开关"（产出最低档并标注）未落地——`config/radar.toml` 里**没有**该键，
  加键属数值口径变更（需五处同步）。**别在本棒顺手加键**，除非用户明确要求（那要按 K3 走五处同步）。

---

## 二、下一棒（M4）待办

> M4 DoD 全文见 `plan/06-里程碑.md` M4 节。这里只列**执行顺序与依赖**。

1. **输入是 M3 的 `ConflictSet`**（`detect.build_conflict_set(...)`）：`conflicts[]` / `undetermined[]` /
   `notes[]` / `counts` / `reference_time` 全部现成。**不要在 `report.py` 里重算任何判定**（K13 渲染层零判定）。
2. **双轨输出**（`plan/04` M4）：
   * `report.md`（人读）：参数来源块（扫描窗口 / 活跃窗 / **阈值出处 `config/radar.toml`**）、
     **`undetermined` 独立小节**（`degraded` / `approximate` / `unsupported_format` 逐条列出）、
     "判定为**辅助参考**"声明、按 `severity` 降序 + `(level, path, symbols)` 稳定排序；
   * `conflicts.json`（机读）：经 `serialize.write_atomic` 冻结契约（K2）。**注意**：M3 的 `detect` 已经落
     `conflicts.json`；M4 的 `report --format json` 要和它**同内容同字节**，别造第二份 schema
     （K13 的"单一渲染源"就落在这条上：Markdown 与 JSON 必须来自**同一个**渲染源，不是人工比对）。
3. **建议是规则模板**（按 level 分派固定文案，**不是模型判断**）：
   `symbol` → "两侧并行改同一符号，需人工裁决"；`file`（不同符号）→ "仅同文件不同符号，可先后提交"；
   行区间相邻 → "改动范围相邻，建议由更早开始的会话先合并"。
4. **退出码**：`conflicts` 非空 → `1`；为空 → `0`；存在 `undetermined` **不改**码但报告里必须列出
   （与 M3 同一条口径）。用法错误 2 / 依赖缺失 3 由现有分派层兜住。
5. **零外链**：`report.md` 不含图片外链 / CDN / `http(s)` 引用；**断言常驻渲染出口**
   （`serialize.assert_no_external_resources` 已备好），不要只在测试里验一次。
6. **确定性**：双跑逐字节一致（真子进程）；不读时钟；时间一律呈现原值、**不编造**"预计完成时间"。
7. **可选通知**：`report.notify` 为 true 时尝试桌面通知；不可用 → 静默跳过 + 产物标 `notify_unavailable`，
   **不影响主流程与退出码**。现实提醒：本机大概率没有可用的通知通道——那就把 `notify_unavailable`
   这条**真的跑出来**并如实登记（比"写了通知但没人验过"强）。
8. **交付命令**：K15 四步（`stages.py` 挪表 → CLI 接线 `_cmd_report` + 测试同步（含"逐条已交付命令不得
   残留在未就绪表"）→ 冒烟期望值改真实契约 + 补**两条**（模块 + console，含 `--format` 的三种取值）→
   README 状态表/退出码表）。
   **⚠️ 检查清单（M3 实打的）**：交付时**必须**复盘这两类"交付即失效"：
   ① **变异脚本的锚点**指向该命令名（本棒是 M4，锚在 `STAGE_NOT_READY` 的 `"report": "M4"` 那一条）
   → 交付后锚点漂移，必须改锚到**仍在**未就绪表里的命令（只剩 `bench`）；
   ② 硬编码"某命令仍未交付"的测试样本 → 本仓已改成从**当前** `STAGE_NOT_READY` 动态取，别再写死。
9. **`bench` 是最后一条**：M4 交付后 `STAGE_NOT_READY` 只剩 `{"bench": "M5"}`；
   那时**阶段未就绪的 exit 4 通路仍在用**，别提前退役 `EXIT_NOT_READY`（K1 四步要等 M5）。
10. **收尾**：M4 DoD 验证 → 回写 `plan/00` / `plan/04` / `plan/05`（若动真值）/ `plan/06` / `plan/07`
    （决策记录 + K 表）→ 写 `HANDOFF-M5.md` → commit。

### M4 必须遵守的口径（逐条对应既有 K）

| K | M4 的落点 |
|---|---|
| K1 | `report` 退役 exit 4；`0/1/2/3` 四语义**各有测试**（含失败路径：缺文件 / 坏格式 / git 不可用） |
| K2 | 两个产物都走 `serialize.write_atomic`，逐字节契约 |
| K3 | 报告里的阈值**只引用** `config/radar.toml`（参数来源块写出键名与来源路径），**不得复制数值**；`report.py` 里**零策略数值字面量**（K5 门禁会扫它，记得登记/豁免要带理由） |
| K12 | 计数口径沿用 M3 的两栏（`by_max_level` 划分 / `by_level_membership` 成员数），报告里**分开呈现** |
| K13 | **渲染三律**：零判定（AST 门禁：`report.py` 不 import 判定函数、不含阈值字面量）+ 零外链（断言常驻渲染出口）+ 双跑逐字节一致 |
| K15 | 退役四步 + 两条通路冒烟 |
| K20 | 报告的排序与展示要**按 `level` 序**呈现，但**匹配口径**仍是 `levels` 集合——别把"最高粒度"写成"唯一粒度" |

---

## 三、既定口径清单（K 编号，"动了会打挂测试"）

> 全文见 `plan/07-交付对标与决策记录.md` §四。**改任何一条都要五处同步**：代码 → 测试 → README → K 表 → 决策记录。
> M3 新增一条：**K20**（检出口径：一条记录 + 粒度集合 + 三态不改判定 + 符号字段按 `approximate` 取舍 + 去重留痕）；
> 同时修订 K1（`1` 首次上岗）、K4（只读指纹 + 同一仓库判据）、K12（两栏 + 内断言）。

| K | 一句话 |
|---|---|
| K1 | 退出码 `0/1/2/3/4`；`4` 随命令交付逐项退役，四步同步（`scan` M1、`intent` M2、`detect` M3 各自退役）；**M3 起 `1` 真正使用** |
| K2 | 序列化冻结：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写；**唯一写盘点 `serialize.write_atomic`** |
| K3 | 数值唯一权威 `config/radar.toml`；代码**零内联默认值**，缺失/未知/类型不符一律报错（exit 3）；覆盖只走 `Config.with_override` |
| K4 | 只读：不 merge/rebase、不写索引、不改工作区；`merge-tree` 只允许 `--write-tree`（对象库临时对象**如实披露**）。**M3 加固**：跑完核对工作区 + `.git/index` + `.git/HEAD` 指纹不变；`merge-tree` 参数是**两侧分支**且要求两侧同一仓库（`--git-common-dir`，worktree 算同一仓库） |
| K5 | 零内联阈值字面量门禁（`0`/`1` 之外必须登记 `ALLOWED_LITERALS` 或整文件豁免并写理由）+ 下层禁止 import 上层 |
| K6 | 底线解释器（3.8）缺能力 → 自写受限子集 + 超集形态**显式报错**，不静默跳过、不引运行时依赖 |
| K7 | 会话格式版本 = 显式指纹集合；未知版本 `unsupported_format` + 缺失键 + 点名文件 |
| K8 | 编码三加固：入口 `_ensure_utf8_stdio` + 子进程显式 `encoding=` + CI `PYTHONUTF8=1` |
| K9 | 真值只存"输入与期望"；出现 `observed_*` 即红；期望值必须可由输入独立复算 |
| K10 | 生成器 `--check` 两层断言（产物形态 + 重生成逐字节）；生成侧/生产侧规范序**各一份独立实现** |
| K11 | 合成数据白名单（M1 追加 `src/beta.py` / `src/filler.py` / `{{REPO_ROOT}}` / 假 author；M2 追加 `src/dup.py` / `docs/notes.md` / `sess-radar-0020`–`0026`）|
| K12 | 计数口径先声明：`by_max_level` 是**划分**（`sum == len(conflicts)`，`_counts()` 内即断言）+ `by_level_membership` 是**成员数** |
| K13 | 报告渲染三律：零判定 + 零外链（断言常驻渲染出口）+ 双跑逐字节一致 |
| K14 | 对外声称逐条有实物（许可/命令/extras/名字四向一致），由 `tests/test_readme_gate.py` 五面对账 |
| K15 | 每交付一条命令 → 同一次提交退役其旧断言 + 补离线冒烟；`python -m` 与裸 `radar` 两条通路都冒烟 |
| K16 | 路径自适应；`expanduser` 解不出主目录时**按哨兵比对**报错——不写盘、不抛系统异常、不回落 CWD |
| K17 | **冻结产物机器无关**：`bench/` 一切文本不得含本机绝对路径；`.git` **不入**冻结产物；提交可复现靠**复算 sha** |
| K18 | **真值里的阈值一律 config 符号引用**（`config_ref` / `const`），由 `--check` 现场求值 |
| K19 | **M2 落点三分法**（`exact`/`coarse`/`unknown`）+ 计数两口径 + 磁盘优先 + 定位基线恒为 `HEAD` |
| **K20** | **M3 检出口径**：① 一条记录 = 一个 `(workspace_a, workspace_b, path)`；`levels` 是命中粒度**集合**（必含 `file`）、`level` 是最高的（只用于排序/严重度）、`symbols` 是符号集合；真值按 `levels`/`symbols` **集合精确匹配**。② 三级判据：两活跃 `(workspace, session)` 组同改同一文件 / 两侧分支 `merge-tree` 冲突路径含本 path / `HEAD` AST 的**同一或相邻**符号（`<=` 容差），不同且不相邻**不升格**。③ `degraded` 与 `approximate` **只降粒度、不改判定、不改退出码**，都落 `undetermined` 逐条列出。④ 符号字段只在 `approximate=False` 时出现（R4）。⑤ 两侧 `derived_from` 相同 ⇒ 默认不产出且**留痕**（`derived_sibling_pairs_skipped`）。⑥ `A` 与 `A.f` 同时命中只报 `A.f` |

---

## 四、本机环境坑（**只写实测过的**；M3 新增七条）

1. **`py` 的标志顺序**：`py -3.8 -X utf8 -m ...` 正确；写成 `py -X utf8 -3.8 -m ...` 会报 `Unknown option: -3`。
   一律：**先版本选择器，再 `-X utf8`**。
2. **`Path.write_text(newline=)` 是 Python 3.10+ 参数**：底线 3.8 上 `TypeError`。
   写法一律 `open(path, "w", encoding="utf-8", newline="\n")`。
3. **本机两条解释器通道**：`py -0p` → `3.8.8-64` 与 `3.12.10-64`（各装一份 editable 包）；
   PATH 上的 `radar` 是 **3.12** 那一份。别把"3.8 通道的 console 冒烟"写成"两版本各自验了两条通路"。
4. **`grep` 中文与 Git Bash 显示**：`git status --short` 显示八进制转义只是显示问题，用 `-c core.quotepath=false` 可读。
5. **临时目录**：一律 `tempfile.mkdtemp()`（Windows 侧路径），**不要**用 Git Bash 的 `/tmp`。
6. **⚠️ 只传一侧会话根 = 会去读真实用户日志**：凡"自动发现本机数据"的参数，测试与冒烟**一律两侧都显式传**
   （缺失的一侧传空目录）。`scan` / `intent` / **`detect`** 同一套规则。
7. **Windows 上 `shutil.rmtree` 会被 git 的只读对象文件挡住**：先 `chmod 0o700` 再删（`bench/gen.py` 的 `_rmtree`）。
8. **同一份夹具别物化两次**：冒烟里 `_SCAN_FIXTURES` / `_INTENT_FIXTURES` / `_DETECT_FIXTURES` 三个缓存
   **key 空间分开**（都拿 `scratch` 当 key，但不同 dict）——合成一个 dict 会互相覆盖。
9. **中文注释/字符串里别用 ASCII 双引号**：写文档脚本时用 `「」`；在双引号字符串里写 `"输入数据"` 直接 `SyntaxError`
   （本棒在生成 `plan/00` 补丁的脚本里**当场踩中一次**）。
10. **门禁与实现冲突时，先问"是不是实现写得比判据更糙"**：M2 的实例（`--check` 路径片段表）与 M3 的实例
    （`detect.py` 里 `128` 与下标 `2`）都走"扩词表 + 写理由"这条既有通道，**不改门禁**。
11. **零写盘纪律的实测方式**：新命令照抄 `test_scan_cli.py` / `test_intent.py` / `test_detect.py` 的形态——
    给一个**空的沙箱目录**当 CWD，跑完断言 `os.listdir` 为空。
12. **`-U0` 的 hunk 头要按"第二个 `@@` 之前"解析**（M2）：`parts[1]` 才是范围；`parts[2]` 是上下文文本。
13. **⚠️ `git status` 一定加 `-z`**（M2）：行模式下中文/特殊字符路径会被转义；rename/copy 会多跟一条原始路径记录。
14. **⚠️ 变异脚本的锚点要带上下文**（M2）：新增代码里出现与旧门禁**同形**的一行时，只锚那一行的变异会改到
    新代码上，目标守门照常绿。
15. **⚠️ `git merge-tree --write-tree` 的冲突信息在 stdout，不在 stderr**（M3 实测，git `2.54.0.windows.1`）：
    `2>/dev/null` 后内容一条不少、`1>/dev/null` 后为空。**注意** exit 128 的 `fatal:` 文案可能落在任一通道——
    解析只吃 stdout，诊断文案两者都取。
16. **⚠️ 冲突路径有两条来源，只认一条会漏**（M3）：`100644 <sha> <stage>\t<path>` 三元组行（content 冲突）
    与 `CONFLICT (...): Merge conflict in <path>` 文案；**`modify/delete` 形态没有三元组行**，路径只在文案里。
17. **⚠️ 只读断言别把 `.git/objects` 算进去**（M3）：`--write-tree` 会写临时 tree/blob 对象，
    那是**已披露的例外**；要比的是工作区文件 + `.git/index` + `.git/HEAD`（+ `git status` + 当前分支）。
18. **⚠️"是不是同一个仓库"要用 `git rev-parse --git-common-dir`**（M3）：同一仓库的多个 worktree
    共享它（对象库共享 → 试合并照样能跑），两个独立仓库则不同 → 落 `degraded`。**别用路径前缀判**。
19. **⚠️ 一条判据可能有多道门**（M3 实测的"假门"教训）：变异组 M25 首版只打掉 exit 128 那一支，
    **下游的"未预期退出码"兜底分支照样降级**，目标守门仍绿（变异脚本报"未检出"）。处置不是给兜底开例外，
    而是**把断言收紧到能区分各道门**（既要 `exit 128` 又要 `无共同祖先`）。**兜底救回来了 ≠ 守门是假门。**
20. **⚠️ 测试里比 stdout 与落盘产物要先归一 CRLF**（M3）：Python 的 `sys.stdout` 在 Windows 上会把 `\n`
    翻译成 `\r\n`，而 `write_atomic` 落的是 LF。判据写 `raw.replace(b"\r\n", b"\n") == out.replace(...)`，
    行尾契约另用一条断言（`b"\r\n" not in raw`）。

---

## 五、DoD 逐项 checklist（M3，已逐项验证）

* [x] **精确匹配**：七条冻结场景逐条对账，`levels` / `symbols` **集合相等**、与 `*_forbidden` 不交；
  报出的 `line_ranges` 落在 M1 登记的**构造几何**里（多报、漏报均失败）
* [x] **负样本零误报**：场景 5 空检出 + `undetermined` 也为空；`src/filler.py` 的噪声符号零命中
* [x] **反向样例**：七条场景 `objects_forbidden` 逐条断言不出现；`objects_expected` 的 `symbol: null`
  落实为"该条只到文件级"
* [x] **三态**：`degraded`（配置关闭 / 孤儿分支 128 / 无 `gitBranch`）、`approximate`（非 Python /
  基线语法错 / 跨 worktree）、`unsupported_format`（坏会话文件一路带出）——各有**手造最小夹具**的合成用例
* [x] **只读**：工作区每文件 + 索引 + HEAD 指纹前后一致、分支不变；对象库临时对象**如实披露**（有断言）
* [x] **计数恒等**：`_counts()` 内断言 `sum(by_max_level) == len(conflicts)`；两栏口径各有实物（7 条场景 + 一条多粒度记录）
* [x] **退役（K15 四步）**：`stages` → CLI + 测试 → 冒烟两条通路（期望值 **1**）+ 源缺失用例 → README；
  **顺带把退出码 1 的措辞从"未来语义"改成"已启用"**
* [x] **`derived_from` 去重**：场景 4 空检出 + `derived_sibling_pairs_skipped` 留痕 + note
* [x] **双解释器全量 pytest**：各 **299 passed / 1 skipped**（跳项附原因）
* [x] **离线冒烟 `--strict`**：**29 用例**全过（两条通路 + 生成器自检 + 零网络导入面审计）
* [x] **变异验证**：**29 组**全部被对应守门抓到，仓库按字节还原（含新 7 组 M23–M29 与改锚后的 M4）
* [x] **冻结产物未被本轮改动**：`bench/` 逐字节未变（`--check` 全过，与 M2 收尾同源）
* [x] **CI：本地等价校验（未接远端，CI 待首推验证）**——`--check` 与冒烟只在本地按同一条命令复跑过
* [x] **`HANDOFF-M4.md`（本文件）**：六节 + 起点快照，库内相对路径、无本机绝对路径

**偏差说明**（如实记录，不做美化）：见 `plan/06-里程碑.md` M3 节"偏差与新增口径"七条 +
`plan/07` §三 的 8 条决策记录 + §九 的 5 条"等价缺口"与 M25 假门教训。**摘要**：

1. `undetermined` 沿用 `discover.Undetermined` 单一形态（原样例写的 `path` 键不另立）。
2. `approximate=True` 时产物里**不出现**符号字段（原措辞"`symbol=None`"）。
3. 符号级只在同一工作区做；区块级要求两侧同一 git 仓库（worktree 算同一仓库）。
4. 记录新增 `sessions`/`session_ids`/`sessions_a`/`sessions_b`/`severity_key`/`degrade_reasons`。
5. `derived_from` 的"提示开关"**未落地**（config 无该键）——只实现默认行为，文档里不出现"可配置"字样。
6. `merge-tree` 的 `128` 按 K5 登记进 `ALLOWED_LITERALS`（带理由）。
7. 变异组 M25 首版是"假门"（下游兜底接住）→ **收紧断言**而不是放宽兜底。
8. `plan/02` 的 FR-1/FR-2 状态列在 M1/M2 收尾时**漏改** → 本棒补记勘误并翻正。

---

## 六、关键命令速查（**每条都在 M3 收尾时实跑过**）

```bash
# 安装（两个解释器各一次；--no-build-isolation 因本机 pip 代理易被污染）
py -3.12 -m pip install -e . --no-build-isolation --no-deps
py -3.8  -m pip install -e . --no-build-isolation --no-deps

# 全量测试（双解释器；先版本选择器再 -X utf8）
py -3.8  -X utf8 -m pytest -q
py -3.12 -X utf8 -m pytest -q

# 只跑 M3 的两组测试（改 detect 时先跑这个）
py -3.12 -X utf8 -m pytest tests/test_detect.py tests/test_detect_parse.py -q

# 离线冒烟（CI 与本地同一条通路；--strict 要求 console script 存在）
py -3.12 -X utf8 tools/verify_offline.py --strict

# 合成矩阵自检（CI 步骤；冲突矩阵 + 意图矩阵两层断言 + 提交 sha 复算 + 脏改动现场复核）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check

# 重建整棵矩阵（改生成器/体例后必须走这条）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --out bench

# 物化（M4/M5 与人工复核用）：冲突场景 / 意图场景
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize whole_file_overwrite --dest out/scene
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize-intent intent_disk_wins --dest out/intent

# 守门变异验证（新增/改写守门后必跑；可 --only M23,M28 单跑）
py -3.12 -X utf8 tools/verify_mutation.py

# 看生效配置 / 自检 / 已交付命令
radar config
radar selftest
radar scan   --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar intent --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar detect --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z   # 有冲突 → exit 1

# 未交付命令（当前应 exit 4）
radar report --repo .
```

> **提示**：`radar` 与 `python -m agent_conflict_radar` 是两条通路（`sys.path` 来源不同）。
> 源码态未安装时用 `PYTHONPATH=src py -3.12 -X utf8 -m agent_conflict_radar <命令>`。
> 跑 `scan` / `intent` / `detect` 时**务必**两侧都传 `--*-root`（见 §四 第 6 条）。
> 全局选项（`--config`）写在**子命令之前**：`radar --config path detect ...`。
> **退出码提示**：`detect` 返回 1 是**成功检出**（不是故障）——`set -e` 的脚本里要显式接住。

---

## 七、M4 起点快照（2026-10-18，M3 收尾时冻结）

| 项 | 状态 |
|---|---|
| 命令面 | 已交付 5 条（`config` / `selftest` / `scan` / `intent` / `detect`）；未交付 2 条（`report` M4 / `bench` M5） |
| 可直接复用的资产 | `detect.build_conflict_set()` 的 `ConflictSet`（`conflicts[]` / `undetermined[]` / `notes[]` / `counts` / `reference_time`）；`serialize.{dumps_json,write_atomic,assert_no_external_resources}`（**零外链断言现成**）；`config.Config.get`（报告参数来源块）；`plan/04` M4 的三条建议模板文案；`bench/scenarios/whole_file_overwrite`（唯一三粒度齐全的夹具，适合做报告演示） |
| 需要新造 | `report.py`、`tests/test_report*.py`、CLI 接线 `_cmd_report`（已有 `--format md\|json\|both` 参数）、冒烟 report 用例（**含 `--format` 三种取值 + 未知格式 exit 2**）、README 状态表再退一项 |
| 硬约束（别踩） | `report.py` **零判定**（AST 门禁：不 import `detect` 的判定函数、不含阈值字面量）；**零外链**（断言常驻渲染出口）；Markdown 与 JSON **同一渲染源**；`undetermined`（含 `degraded` / `approximate` / `unsupported_format`）**独立小节**逐条列出；"判定为**辅助参考**"声明；**不得声称"防止所有覆盖"** |
| 已知会被 M4 打中的形态 | `degraded=true` 的记录（区块级降级）与 `approximate=true` 的记录（**没有 `symbols` 键**）——报告渲染必须能处理"这两个键不存在"，别写成 `record["symbols"]` 直接下标取值 |
| 风险 | 三条风险（同类低星混战 / 符号级已被 `wit` 口头占位 / 本机真实并行样本为 0）**一条都没变**，M3 不改变其中任何一条；不得用真实样本数包装检出率 |
