# HANDOFF-M5：从 M4 续接到 M5（合成基准评分）

**项目**：`agent-conflict-radar`（本地目录 `10-18-agent-conflict-radar`）
**上一棒**：M4 —— ✅ **完成**（2026-10-18）：`radar report` 交付（单一渲染源 + 渲染三律 + 退出码 0/1/2/3 各有实物）
**当前状态**：M0 + M1 + M2 + M3 + M4 全部门禁在本机复核全绿（见 §五）
**本文件用途**：下一棒开工前**只需读本文件 + `plan/00`·`04`·`05`·`07` + `data/README.md` §6.7**，不依赖对话记忆
**启动方式（用户侧，绝对路径）**：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务`

---

## 一、当前进度与证据

### 1.1 已完成（M4 本体）

| 项 | 产物 | 证据（可复跑） |
|---|---|---|
| `radar report` 交付（K15 四步走完） | `report.py`（`build_report` / `render_markdown` / `sorted_for_display` / `notify_status`）+ `cli._cmd_report` | `tests/test_report.py`（39 条）+ 冒烟 5 条模块用例 + 3 条 console 用例 |
| **单一渲染源**（结构性，非人工比对） | `ReportSurface.payload` = `ConflictSet.as_dict()`；Markdown = `render_markdown(payload)` 纯函数 | `test_markdown_is_a_pure_function_of_the_json_payload` + `test_payload_is_byte_identical_to_detects_conflicts_json`（两份 `conflicts.json` 逐字节相同）+ `test_markdown_tracks_payload_changes`（改 payload 必变） |
| 渲染三律（K13） | 零判定 AST 门禁 / 零外链常驻出口 / 双跑逐字节 | `test_render_layer_does_not_import_any_judgement_module`（+ 可证伪探针 `test_import_scanner_is_falsifiable`）+ `test_external_resources_are_rejected_at_the_render_exit` + `test_report_is_byte_identical_across_two_real_processes` |
| 退出码 0/1/2/3 各有实物 | 有冲突 1 / 无冲突 0 / 未知 `--format` 2 / 路径不存在 2 / 会话源缺失 3 | 五条独立用例；失败路径还断言 `stdout == b""` |
| `undetermined` 独立小节 + 三态 | `degraded` / `symbol_unavailable` / `unsupported_format` 同屏逐条 | `test_undetermined_entries_are_rendered_with_all_three_codes` |
| 已知形态（无 `symbols` 键） | `approximate=true` 的记录能渲染，不直接下标取值 | `test_approximate_record_without_symbols_key_is_rendered` + 变异组 M31 |
| 建议是规则模板 | 四档按 `severity_key` 分派固定文案 | `test_suggestions_are_rule_templates_keyed_by_engine_severity` + `test_severity_keys_are_all_covered_by_suggestion_templates` + 变异组 M32 |
| 排序 | `severity` 降序 + `(level 序, path, symbols)` 稳定 | `test_display_order_is_severity_desc_then_level_and_path` + 变异组 M33 |
| 计数两栏（K12） | 条目数（划分）/ 成员数（成员）**分开**呈现 | `test_count_columns_are_presented_separately_with_their_own_semantics` |
| 可选通知 | 不可用 → `notify_unavailable`，不影响主流程 | 四条用例（未尝试 / 无通道 / 已发送 / 发送失败被吞） |
| 参数来源块（K3） | 只写键名与 `source_path`，**不复制数值** | `test_markdown_contains_parameter_source_block_without_copying_values` |
| 门禁补充 | 1 个新测试文件（39 条）+ 冒烟 +8 用例 + 变异组 M30–M33（并改锚 M4） | 见 §六 命令速查 |
| 文档回写 | `plan/00`（§一/§三/§四/§五/新增 §十一）、`plan/02`（FR-4 状态 + 两条勘误）、`plan/04`（M4 五条勘误注）、`plan/06`（M4 收尾结论）、`plan/07`（5 条决策记录 + K1/K13 修订 + §十）、README | 本文件 §五 逐项 |

### 1.2 本棒实测数字（不要照抄，下一棒收尾要**复测**）

| 项 | 值 |
|---|---|
| 测试数 | `py -3.8` 336 passed / 1 skipped；`py -3.12` 336 passed / 1 skipped |
| 跳过项 | `tests/test_paths_adaptive.py` 符号链接用例——当前文件系统不支持创建目录符号链接（声明式跳过，附原因） |
| 离线冒烟 | `--strict` 下 **35 用例全过**（模块通路 24 + 生成器自检 1 + console 通路 10） |
| 变异验证 | **33 组**全部被对应守门抓到，仓库按字节还原 |
| 合成矩阵 | **M4 未新增场景、未改冻结产物**：冲突 7 条 + 意图 8 条，两棵树的 `missing_types` 均为空 |
| 包版本 | `0.0.1`（未变） |
| 命令面 | 已交付 6 条（`config`/`selftest`/`scan`/`intent`/`detect`/`report`）；未交付 **1** 条（`bench` M5） |

### 1.3 未做（明确不在 M4 范围，就是 M5 的活）

* `radar bench` **仍 exit 4**（`stages.STAGE_NOT_READY` 里只剩 `{"bench": "M5"}`）。
* **评分函数**（逐场景 `期望 / 实际 / 判定` + 汇总 + `bench/last_run.json`）**全未开始**。
* 矩阵**补全**（每类最低条数、卡阈值边界的成对用例）——M1/M2 已交付 7 + 8 条，**M5 要按
  `bench/manifest.json` 的 `coverage.min_count_by_type` 复核并补缺**。
* `docs/技术报告.md`（M5）、`scripts/check_release.py`（M6）、`MANIFEST.in`（M6）仍未落。
* `symbol.min_overlap_lines` **仍未被任何代码消费**（`plan/04` 注⑨ / `plan/05` R5）——M5 要么消费它，
  要么在文档里明确"它是遗留键"（**不得**悄悄留着让读者以为它在起作用）。
* `derived_from` 的"提示开关"仍未落地（config 无该键）；**别在 M5 顺手加键**，除非用户明确要求（按 K3 五处同步）。

---

## 二、下一棒（M5）待办

> M5 DoD 全文见 `plan/06-里程碑.md` M5 节。这里只列**执行顺序与依赖**。

1. **先读 `plan/05` §五（覆盖度门槛）与 `bench/manifest.json`**：评分命令的判据来自台账，
   不是"跑完看着都对"。`coverage.min_count_by_type` 是门槛；`missing_types` 必须为空。
2. **`bench.py`（评分）**：
   * 输入 = `bench/scenarios/*/truth.json` + `bench/intents/*/truth.json`；
   * 逐场景物化 → 跑 `scan` → `intent` → `detect` → 与真值**集合精确匹配**；
   * **多报（extra）/ 漏报（missing）均计失败**；逐场景打印 `期望 / 实际 / 判定`；
   * 汇总落 `bench/last_run.json`（经 `serialize.write_atomic`，K2）。
3. **`--only ID[,ID...]`** 已注册在 parser 里（`bench --only`），接线时必须让"过滤后为空"是**用法错误**
   （exit 2）而不是"零条通过"。
4. **退出码**：全部场景通过 → `0`；任一失败 → `1`；用法错误 `2` / 依赖缺失 `3`
   （`bench` 也是 `_NEEDS_GIT` 成员）。**`4` 在 M5 交付后要整条退役**（K1 四步：
   删 `EXIT_NOT_READY` 常量 → 改 CLI/`stages`/测试（含 `not hasattr` 防复活）→ README 退出码表 → 决策记录）。
5. **"可证伪探活"（M5 DoD 硬要求）**：注入一个缺陷（比如把某条真值的期望改一位、或把评分函数里的
   集合比对改成"包含"），基准**必须报未达标**——探活要打在**消费处**，不是在测试里另写一份比对。
   这条与 M4 的"假门"教训同源：`tools/verify_mutation.py` 加一组专门打评分函数的变异。
6. **干净环境验证**：新建 venv + `pip install -e ".[dev]"` → README 逐条跑通（退出码按明示语义记"符合声明"）。
   **这是 M5 DoD 的一条，不能只在本机现有环境里跑。**
7. **隐私审计**：入库内容扫描（真实路径 / session id / 用户名零命中）+ 断网运行。
8. **矩阵补全**：若 `min_count_by_type` 未达标，**走生成器重建**（`--out bench`），不要手改 `truth.json`
   （K9/K10：真值必须与生成器同步产出，且 `--check` 会逐字节比对）。
9. **收尾**：M5 DoD 验证 → 回写 `plan/00` / `plan/04` / `plan/05` / `plan/06` / `plan/07` → 写 `HANDOFF-M6.md` → commit。

### M5 必须遵守的口径（逐条对应既有 K）

| K | M5 的落点 |
|---|---|
| K1 | `bench` 退役 exit 4；**四步走完**（含删 `EXIT_NOT_READY` 常量与 `not hasattr` 防复活）；`0/1/2/3` 各有测试 |
| K2 | `bench/last_run.json` 走 `serialize.write_atomic`，逐字节契约 |
| K3 | 评分用的阈值**只从 config 读**；`bench.py` 里零策略数值字面量（K5 门禁会扫） |
| K9 | 真值只存输入与期望；评分**不得**把"实际检出"写回真值 |
| K10 | 矩阵补全必须走生成器重建 + `--check` 逐字节；生成侧/生产侧规范序各一份 |
| K15 | `bench` 退役四步 + **两条通路**冒烟（模块 + console），期望值改真实契约 |
| K17 | 新增任何冻结产物仍要**机器无关**（无本机绝对路径） |
| K20 | 评分按 `levels` / `symbols` **集合精确匹配**（不是"最高粒度"单值比对） |

---

## 三、既定口径清单（K 编号，"动了会打挂测试"）

> 全文见 `plan/07-交付对标与决策记录.md` §四。**改任何一条都要五处同步**：代码 → 测试 → README → K 表 → 决策记录。
> M4 修订了两条：**K1**（`report` 与 `detect` 同一退出码口径）、**K13**（单一渲染源的落地形态写死为
> "payload = `ConflictSet.as_dict()`，Markdown 是它的纯函数"）。

| K | 一句话 |
|---|---|
| K1 | 退出码 `0/1/2/3/4`；`4` 随命令交付逐项退役，四步同步（`scan` M1 / `intent` M2 / `detect` M3 / `report` M4 各自退役）；**M3 起 `1` 真正使用**，M4 起 `report` 同口径 |
| K2 | 序列化冻结：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写；**唯一写盘点 `serialize.write_atomic`** |
| K3 | 数值唯一权威 `config/radar.toml`；代码**零内联默认值**，缺失/未知/类型不符一律报错（exit 3）；覆盖只走 `Config.with_override` |
| K4 | 只读：不 merge/rebase、不写索引、不改工作区；`merge-tree` 只允许 `--write-tree`（对象库临时对象**如实披露**）。跑完核对工作区 + `.git/index` + `.git/HEAD` 指纹不变；`merge-tree` 参数是**两侧分支**且要求两侧同一仓库（`--git-common-dir`，worktree 算同一仓库） |
| K5 | 零内联阈值字面量门禁（`0`/`1` 之外必须登记 `ALLOWED_LITERALS` 或整文件豁免并写理由）+ 下层禁止 import 上层 |
| K6 | 底线解释器（3.8）缺能力 → 自写受限子集 + 超集形态**显式报错**，不静默跳过、不引运行时依赖 |
| K7 | 会话格式版本 = 显式指纹集合；未知版本 `unsupported_format` + 缺失键 + 点名文件 |
| K8 | 编码三加固：入口 `_ensure_utf8_stdio` + 子进程显式 `encoding=` + CI `PYTHONUTF8=1` |
| K9 | 真值只存"输入与期望"；出现 `observed_*` 即红；期望值必须可由输入独立复算 |
| K10 | 生成器 `--check` 两层断言（产物形态 + 重生成逐字节）；生成侧/生产侧规范序**各一份独立实现** |
| K11 | 合成数据白名单（M1 追加 `src/beta.py` / `src/filler.py` / `{{REPO_ROOT}}` / 假 author；M2 追加 `src/dup.py` / `docs/notes.md` / `sess-radar-0020`–`0026`）|
| K12 | 计数口径先声明：`by_max_level` 是**划分**（`sum == len(conflicts)`，`_counts()` 内即断言）+ `by_level_membership` 是**成员数**；报告里**分开呈现** |
| K13 | 报告渲染三律：零判定（AST：不 import `detect`/`intent`/`discover`/`gitio`）+ 零外链（断言常驻 `render_markdown` 出口）+ 双跑逐字节一致；**单一渲染源** = payload 是事实面、Markdown 是它的纯函数 |
| K14 | 对外声称逐条有实物（许可/命令/extras/名字四向一致），由 `tests/test_readme_gate.py` 五面对账 |
| K15 | 每交付一条命令 → 同一次提交退役其旧断言 + 补离线冒烟；`python -m` 与裸 `radar` 两条通路都冒烟 |
| K16 | 路径自适应；`expanduser` 解不出主目录时**按哨兵比对**报错——不写盘、不抛系统异常、不回落 CWD |
| K17 | **冻结产物机器无关**：`bench/` 一切文本不得含本机绝对路径；`.git` **不入**冻结产物；提交可复现靠**复算 sha** |
| K18 | **真值里的阈值一律 config 符号引用**（`config_ref` / `const`），由 `--check` 现场求值 |
| K19 | **M2 落点三分法**（`exact`/`coarse`/`unknown`）+ 计数两口径 + 磁盘优先 + 定位基线恒为 `HEAD` |
| K20 | **M3 检出口径**：① 一条记录 = 一个 `(workspace_a, workspace_b, path)`；`levels` 是命中粒度**集合**（必含 `file`）、`level` 是最高的（只用于排序/严重度）、`symbols` 是符号集合；真值按 `levels`/`symbols` **集合精确匹配**。② 三级判据见 `plan/07`。③ `degraded` / `approximate` **只降粒度、不改判定、不改退出码**，都落 `undetermined` 逐条列出。④ 符号字段只在 `approximate=False` 时出现（R4）。⑤ 两侧 `derived_from` 相同 ⇒ 默认不产出且**留痕**。⑥ `A` 与 `A.f` 同时命中只报 `A.f` |

---

## 四、本机环境坑（**只写实测过的**；M4 新增三条）

1. **`py` 的标志顺序**：`py -3.8 -X utf8 -m ...` 正确；写成 `py -X utf8 -3.8 -m ...` 会报 `Unknown option: -3`。
   一律：**先版本选择器，再 `-X utf8`**。
2. **`Path.write_text(newline=)` 是 Python 3.10+ 参数**：底线 3.8 上 `TypeError`。
   写法一律 `open(path, "w", encoding="utf-8", newline="\n")`。
3. **本机两条解释器通道**：`py -0p` → `3.8.8-64` 与 `3.12.10-64`（各装一份 editable 包）；
   PATH 上的 `radar` 是 **3.12** 那一份。别把"3.8 通道的 console 冒烟"写成"两版本各自验了两条通路"。
4. **`grep` 中文与 Git Bash 显示**：`git status --short` 显示八进制转义只是显示问题，用 `-c core.quotepath=false` 可读。
5. **临时目录**：一律 `tempfile.mkdtemp()`（Windows 侧路径），**不要**用 Git Bash 的 `/tmp`。
6. **⚠️ 只传一侧会话根 = 会去读真实用户日志**：凡"自动发现本机数据"的参数，测试与冒烟**一律两侧都显式传**
   （缺失的一侧传空目录）。`scan` / `intent` / `detect` / **`report`** 同一套规则。
7. **Windows 上 `shutil.rmtree` 会被 git 的只读对象文件挡住**：先 `chmod 0o700` 再删（`bench/gen.py` 的 `_rmtree`）。
8. **同一份夹具别物化两次**：冒烟里 `_SCAN_FIXTURES` / `_INTENT_FIXTURES` / `_DETECT_FIXTURES` / `_REPORT_FIXTURES`
   四个缓存 **key 空间分开**（都拿 `scratch` 当 key，但不同 dict）——合成一个 dict 会互相覆盖。
9. **中文注释/字符串里别用 ASCII 双引号**：写文档脚本时用 `「」`；在双引号字符串里写 `"输入数据"` 直接 `SyntaxError`
   （M3 在生成 `plan/00` 补丁的脚本里踩中过一次；M4 写报告文案时也差点踩中）。
10. **门禁与实现冲突时，先问"是不是实现写得比判据更糙"**：M2 / M3 / M4 三次实例都走"扩词表 + 写理由"通道
    （M4 是 `report.py` 的三元组下标 `2`），**不改门禁**。
11. **零写盘纪律的实测方式**：新命令照抄 `test_scan_cli.py` / `test_intent.py` / `test_detect.py` / `test_report.py`
    的形态——给一个**空的沙箱目录**当 CWD，跑完断言 `os.listdir` 为空。
12. **`-U0` 的 hunk 头要按"第二个 `@@` 之前"解析**（M2）：`parts[1]` 才是范围；`parts[2]` 是上下文文本。
13. **⚠️ `git status` 一定加 `-z`**（M2）：行模式下中文/特殊字符路径会被转义；rename/copy 会多跟一条原始路径记录。
14. **⚠️ 变异脚本的锚点要带上下文**（M2）：新增代码里出现与旧门禁**同形**的一行时，只锚那一行的变异会改到
    新代码上，目标守门照常绿。
15. **⚠️ `git merge-tree --write-tree` 的冲突信息在 stdout，不在 stderr**（M3 实测，git `2.54.0.windows.1`）。
16. **⚠️ 冲突路径有两条来源，只认一条会漏**（M3）：三元组行 + `CONFLICT` 文案；`modify/delete` 只有文案。
17. **⚠️ 只读断言别把 `.git/objects` 算进去**（M3）：`--write-tree` 会写临时对象（已披露的例外）。
18. **⚠️"是不是同一个仓库"要用 `git rev-parse --git-common-dir`**（M3）：**别用路径前缀判**。
19. **⚠️ 一条判据可能有多道门**（M3）：变异要打"整段语义"，或把断言收紧到能区分各道门。
20. **⚠️ 测试里比 stdout 与落盘产物要先归一 CRLF**（M3）：`sys.stdout` 在 Windows 上翻译 `\n` → `\r\n`，
    `write_atomic` 落 LF。判据写 `raw.replace(b"\r\n", b"\n") == out.replace(...)`。
21. **⚠️ AST 门禁的 `ImportFrom` 有两条通路**（M4）：`from . import detect` 的 `node.module` 是 `None`，
    模块名在 `alias.name` 里——只读 `module` 的门禁会把"渲染层 import 了判定模块"整条漏判（假门）。
    文本/结构类门禁第一轮**必须配注入探针**。
22. **⚠️ Windows 没有零依赖的桌面通知通道**（M4）：PowerShell toast 依赖脚本策略与用户会话、失败方式不可判定。
    本机 `report.notify=true` 的真实结果是 `notify_unavailable`——这是**如实登记**，不是缺陷。
23. **⚠️ 报告的证据截断要留痕**（M4）：`report.max_evidence_items` 生效时写明"…另有 N 条"；
    只截断不登记会被读成"证据就这么多"。

---

## 五、DoD 逐项 checklist（M4，已逐项验证）

* [x] **双轨一致（结构性）**：Markdown 是 JSON payload 的纯函数；`report --format json` 与 `detect` 的
  `conflicts.json` **逐字节相同**；改 payload → Markdown 必变（探针）
* [x] **退出码四语义**：0（负样本）/ 1（`whole_file_overwrite`）/ 2（未知 `--format`、路径不存在）/
  3（会话源缺失，且 `stdout == b""`）；`undetermined` 不改码
* [x] **渲染零判定**：AST 门禁（不 import `detect`/`intent`/`discover`/`gitio`）+ 零阈值字面量（只允许 `0/1/2`）
  + 可证伪探针（注入 import 必须被抓）
* [x] **零外链**：`render_markdown` 出口常驻 `assert_no_external_resources`；带 URL 的 payload 当场抛错
* [x] **确定性**：真子进程双跑 stdout 逐字节一致；`report.md` + `conflicts.json` 两次落盘逐字节一致；LF 行尾
* [x] **参数来源块（K3）**：键名在场、数值不在场（逐键断言）
* [x] **`undetermined` 独立小节**：三态原因码 + 文件逐条列出；无条目时也写明
* [x] **已知形态**：`approximate=true`（无 `symbols` 键）与 `degraded=true` 都能渲染
* [x] **建议是规则模板**：四档按 `severity_key` 分派；`[severity]` 键集合 == 模板集合
* [x] **排序**：`severity` 降序 + `(level 序, path, symbols)` 稳定；变异打掉排序必须红
* [x] **计数两栏（K12）**：同一场景同时展示划分与成员数，且数值不同
* [x] **可选通知**：未尝试 / 无通道（真跑出 `notify_unavailable`）/ 已发送（断言命令被调用）/ 失败被吞
* [x] **退役（K15 四步）**：`stages` → CLI + 测试 → 冒烟两条通路（模块 5 + console 3）→ README
* [x] **双解释器全量 pytest**：各 **336 passed / 1 skipped**（跳项附原因）
* [x] **离线冒烟 `--strict`**：**35 用例**全过
* [x] **变异验证**：**33 组**全部被对应守门抓到，仓库按字节还原（含新 M30–M33 与改锚 M4）
* [x] **冻结产物未被本轮改动**：`bench/` 逐字节未变（`--check` 全过）
* [x] **CI：本地等价校验（未接远端，CI 待首推验证）**——`--check` 与冒烟只在本地按同一条命令复跑过
* [x] **`HANDOFF-M5.md`（本文件）**：六节 + 起点快照，库内相对路径、无本机绝对路径

**偏差说明**（如实记录，不做美化）：见 `plan/06-里程碑.md` M4 节"偏差与新增口径"五条 +
`plan/07` §三 的 5 条决策记录 + §十 的 5 条"等价缺口"与 M4 假门教训。**摘要**：

1. 建议模板按 `severity_key`（四档）分派，不是 `level`（三档）。
2. 退出码按 K20 ③ 收敛为"`conflicts` 为空 → 0"（`undetermined` 不改码）。
3. `REPORT_LEVEL_ORDER` 在渲染侧另写一份（零判定要求），一致性由漂移守卫钉住。
4. `report.py` 的三元组下标 `2` 按 K5 登记进 `ALLOWED_LITERALS`。
5. 通知在 Windows 上没有可用通道：`notify_unavailable` 是真跑出来的；"已发送"只有合成用例。

---

## 六、关键命令速查（**每条都在 M4 收尾时实跑过**）

```bash
# 安装（两个解释器各一次；--no-build-isolation 因本机 pip 代理易被污染）
py -3.12 -m pip install -e . --no-build-isolation --no-deps
py -3.8  -m pip install -e . --no-build-isolation --no-deps

# 全量测试（双解释器；先版本选择器再 -X utf8）
py -3.8  -X utf8 -m pytest -q
py -3.12 -X utf8 -m pytest -q

# 只跑 M4 的测试（改 report 时先跑这个）
py -3.12 -X utf8 -m pytest tests/test_report.py -q

# 离线冒烟（CI 与本地同一条通路；--strict 要求 console script 存在）
py -3.12 -X utf8 tools/verify_offline.py --strict

# 合成矩阵自检（CI 步骤；冲突矩阵 + 意图矩阵两层断言 + 提交 sha 复算 + 脏改动现场复核）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --check

# 重建整棵矩阵（改生成器/体例后必须走这条）
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --out bench

# 物化（M5 与人工复核用）：冲突场景 / 意图场景
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize whole_file_overwrite --dest out/scene
py -3.12 -X utf8 -m agent_conflict_radar.bench.gen --materialize-intent intent_disk_wins --dest out/intent

# 守门变异验证（新增/改写守门后必跑；可 --only M30,M31 单跑）
py -3.12 -X utf8 tools/verify_mutation.py

# 看生效配置 / 自检 / 已交付命令
radar config
radar selftest
radar scan   --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar intent --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z
radar detect --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z   # 有冲突 → exit 1
radar report --repo . --claude-root <claude 根> --codex-root <codex 根> --now 2026-01-01T00:10:00Z   # 有冲突 → exit 1
radar report --repo . --out-dir out --format both     # out/report.md + out/conflicts.json
radar report --repo . --format json                   # 只打机读 JSON

# 未交付命令（当前应 exit 4）
radar bench
```

> **提示**：`radar` 与 `python -m agent_conflict_radar` 是两条通路（`sys.path` 来源不同）。
> 源码态未安装时用 `PYTHONPATH=src py -3.12 -X utf8 -m agent_conflict_radar <命令>`。
> 跑 `scan` / `intent` / `detect` / `report` 时**务必**两侧都传 `--*-root`（见 §四 第 6 条）。
> 全局选项（`--config`）写在**子命令之前**：`radar --config path report ...`。
> **退出码提示**：`detect` / `report` 返回 1 是**成功检出**（不是故障）——`set -e` 的脚本里要显式接住。

---

## 七、M5 起点快照（2026-10-18，M4 收尾时冻结）

| 项 | 状态 |
|---|---|
| 命令面 | 已交付 6 条（`config` / `selftest` / `scan` / `intent` / `detect` / `report`）；未交付 **1** 条（`bench` M5） |
| 可直接复用的资产 | `detect.build_conflict_set()`（冲突集合）；`report.ReportSurface`（报告面）；`serialize.{dumps_json,write_atomic,assert_no_external_resources}`；`config.Config.get` / `with_override`；`bench/gen.{scenario_ids,scenario_by_id,materialize_scenario,intent_scenario_by_id,materialize_intent_scenario}`；`bench/manifest.json` 的覆盖度门槛 |
| 需要新造 | `bench.py`（评分：逐场景物化 → 跑链路 → 集合精确匹配 → 汇总）、`bench/last_run.json`、`tests/test_bench.py`、CLI 接线 `_cmd_bench`（`--bench-dir` / `--out-dir` / `--only` 已注册）、冒烟 bench 用例、**`EXIT_NOT_READY` 整条退役**、`docs/技术报告.md` |
| 硬约束（别踩） | 评分**不得**把实际检出写回真值（K9）；矩阵补全**只能**走生成器重建（K10）；`bench/last_run.json` 走 `write_atomic`（K2）；"可证伪探活"要打在**消费处**；`bench` 退役 `4` 时必须四步走完（含 `not hasattr` 防复活） |
| 已知会被 M5 打中的形态 | ①`tools/verify_offline.py` 里 `for command in sorted(stages.STAGE_NOT_READY)` 循环会**变空**——那两段"阶段未就绪"用例要整段退役（不是留下空循环）；②`test_staged_commands_return_not_ready` 的参数化会**无样本**——要么退役，要么按 `test_selftest_detects_stage_table_overlap` 的写法显式失败并说明"里程碑已全交付"；③变异组 M4 的锚点（现在锚在 `bench`）在 `bench` 交付后**再次漂移**，届时该组要整条退役 |
| 风险 | 三条风险（同类低星混战 / 符号级已被 `wit` 口头占位 / 本机真实并行样本为 0）**一条都没变**；M4 不改变其中任何一条；不得用真实样本数包装检出率 |
