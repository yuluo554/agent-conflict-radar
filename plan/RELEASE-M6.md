# RELEASE-M6：发布留档（tag 时刻内容）

> **本文件的使用纪律（DoD ③）**
>
> * 本文件在 **tag 之前**写好并提交，**进 tag 树**；它描述的是"发布这一刻的事实与判定口径"。
> * tag 之后才产生的事实（附件 sha256、真下载复核、CI run id、失败轮次）**一律追加在文末追加事实节**，
>   **不覆盖**本文件 §一–§七 的内容。
>   * **§八 = `v0.0.1` 的 tag 后事实（历史照录，不删不改）**；
>   * **§九 = `v0.0.2` 的 tag 后事实**（"发布物自证"这条缺陷的修复记录）；
>   * **§十 = `v0.0.3` 的 tag 后事实**（"工具锚点含版本号"这条缺陷的修复记录）。
> * 时间一律写**真实 UTC 时刻**（K7：这是事件记录，不是产物判定）。
> * 本文件**不含**发布附件自身的 sha256——那是 tag 之后的事实，且写进源码包会造成自指
>   （下次构建的字节会变，sha256 必然过期，K17）。附件登记落在 `plan/release-assets.json`。

---

## 一、发布坐标

| 项 | 值 |
|---|---|
| 仓库 | `yuluo554/agent-conflict-radar`（公开） |
| 包名 / 导入名 | `agent-conflict-radar` / `agent_conflict_radar` |
| 版本 | `0.0.3`（`src/agent_conflict_radar/__init__.py` 的 `__version__` 是唯一来源） |
| 许可 | MIT（`LICENSE` 文件 + `pyproject.toml` 的 `license = "MIT"` + `license-files`，PEP 639 形态） |
| 运行时依赖 | **零**（`dependencies = []`）；dev extra = `pytest` + `build` + `wheel` |
| 底线解释器 | Python **3.12**（3.8 已于 2024-10-07 EOL，本迭代抬地板：`requires-python` + classifier + CI 矩阵 + README 四处同口径） |
| 命令面 | **7/7**：`config` / `selftest` / `scan` / `intent` / `detect` / `report` / `bench` |
| 退出码 | 只有 `0/1/2/3`（K1） |
| 附录 | `v0.0.1` 的发布坐标是 **0.0.1 / Python 3.8 / 许可 TOML 表形态**、`v0.0.2` 是 **0.0.2 / 13→12 条门**——见 §八/§九（历史照录，不覆盖） |

**名字四向一致**（K14，发布前并排读一遍）：README H1 含 `agent-conflict-radar`；
GitHub 仓库名 `agent-conflict-radar`；`pyproject.toml` 的 `name = "agent-conflict-radar"`；
导入包名 `agent_conflict_radar`（下划线形态）。

---

## 二、发布门（`scripts/check_release.py`）

**刻意不进 CI**：它判的是"发布这件事做完了没有"，而那些状态只在发布时才存在。放进 CI 只能
被跳过或被放宽——那就是假门。

| 模式 | 判据 |
|---|---|
| 默认（离线） | C01–C13：工作树干净 / 无运行产物入库 / 名字四向 / 退出码冻结 / 矩阵自检 / 矩阵机器无关 / 提交面脱敏 / MANIFEST 覆盖 / **真建 sdist 核对** / **解包即用** / **发布件可复现**（同 ref 两次构建逐字节相同） / **文档条数与检查表对账**（C12） / **变异脚本锚点可落**（C13：`tools/verify_mutation.py` 的每组 marker 恰好命中 1 次，且包版本文件的锚点不含版本号字面量） |
| `--online` | O01–O07：仓库公开 / annotated tag 指向发布提交 / CI **逐 job** 全 success / push 事件与 run 对账 / 附件集合与登记一致 / **逐个下载复算 sha256** / **附件与 tag 树逐字节同源** |
| `--mutation` | 门自身的可证伪性：**检查项数 == 变异组数**（当前 19 ↔ 19，`v0.0.1` 时为 18 ↔ 18），每条检查必须被对应变异打红 |

退出码沿用 `radar` 的四语义：`0` 全过 / `1` 有 FAIL / `2` 用法错误 / `3` 依赖缺失（gh、build、git）。
**不新增第五个码**（K1）。

---

## 三、源码包（`MANIFEST.in`）——"源码包自足"

白名单规则，**不用 `graft` 整目录兜底**。内容分两类：

| 类别 | 规则 |
|---|---|
| 根文件 | `README.md` / `LICENSE` / `pyproject.toml` / `MANIFEST.in` |
| 数值口径（K3） | `recursive-include config *.toml` |
| 文档与计划 | `recursive-include docs *.md`、`recursive-include plan *.md` |
| 门禁与测试 | `recursive-include tools *.py`、`recursive-include tests *.py`、`recursive-include scripts *.py` |
| 冻结矩阵（K11 白名单假值） | `recursive-include bench *.json *.jsonl *.py *.md` |
| **显式排除** | `exclude bench/last_run.json`（运行产物：每次整矩阵运行都会重写，不是源码内容） |
| 防御性排除 | `prune out` / `prune dist` / `prune build` / `global-exclude __pycache__ *.py[cod]` |

**验证方式不是读规则文本**，是 C09 + C10 两条实测：

1. `git archive HEAD` 导出**受控树**（避免工作树里的 `*.egg-info` 等未跟踪产物混进包），
   在导出树上真建 sdist，逐条核对：`bench/` 全部受控文件都在、`last_run.json` 不在、必需文件都在；
2. 解包到中立目录，**从解包目录之外**用解包出来的 `src/` 跑 `--version` / `selftest` /
   `bench --only`（模块通路），全部 exit 0。

---

## 四、发布步骤与顺序（顺序本身是判据）

```text
1. 本地全绿（pytest / 离线冒烟 --strict / bench 全矩阵 / gen --check / mutation / 发布门离线 + 变异）
2. 脱敏复查（入库内容 + 提交元数据邮箱）
3. **从候选树建 sdist**：scripts/check_release.py --build-asset dist/release --tag <候选 ref>
   → 记下 sha256（记为 A）与字节数（该树**尚未**含附件登记文件）
4. **写附件登记**：--record-assets dist/release --tag <新 tag> → plan/release-assets.json
   （经 serialize.write_atomic 落盘，K2）
5. **提交登记文件** → 再打 annotated tag（tag 树从此**含**登记文件）
6. **从新 tag 树再建一次 sdist**，断言 sha256 == A ← 证明"登记入库没有改变包"
7. push tag → tag push 触发一条 run（CI 必须绿）
8. 远端正下载复核：scripts/check_release.py --online --tag <tag>   → 必须 0 FAIL
9. 手工上传附件（**不得**用仓库 zipball 替代）；中立目录解包跑一次 CLI（"解压即用"实证）
10. 本文件 §九 追加 tag 后事实 → 追加提交 push
```

**为什么 ③–⑥ 是这个顺序（`v0.0.1` 时是反的）**：附件必须与 tag 树**逐字节同源**，而
`v0.0.1` 的登记文件是 tag **之后**的追加提交，于是 O05/O06/O07 在发布物自身里**必然 FAIL**
（"下载到包的人照着 README 跑同一份门，得到 4 FAIL"）。修正的依据是一次实测：
`plan/release-assets.json` **不在 sdist 内**（`tar -tzf dist/*.tar.gz | grep -c release-assets` → **0**，
`MANIFEST.in` 只收 `plan *.md`）——所以"先把登记写进树、再打 tag"**不会改变包的字节**（第 ⑥ 步当场断言），
自指/鸡生蛋的顾虑用**流程顺序**解决，**不需要**把 O05/O06/O07 降级成 WARN/SKIP。

---

## 五、DoD 三件套与判据（发布时逐条核对）

| # | 判据 | 核对方式 |
|---|---|---|
| ① tag | annotated tag 打在 **CI 绿的收尾提交**上 | `git cat-file -t <tag>` = `tag`；`gh api .../git/tags/<sha>` 的 `object.sha` == 本地 `rev-parse <tag>^{commit}`（O02） |
| ② Release 附产物 | 源码 zip/tar 为**手工上传附件**；本地留同名副本 + sha256 留档 | 附件集合与 `plan/release-assets.json` 一致（O05）；逐个下载复算 sha256（O06） |
| ③ 发布留档 | 本文件进 tag 树 | `git ls-tree -r <tag> -- plan/RELEASE-M6.md` 非空 |

**不得**以"仓库 zipball 即产物"替代附件：zipball 是 GitHub 生成的快照，不含
`MANIFEST.in` 决定的内容边界，也没有"本地副本 + sha256"这条可复验链条。

---

## 六、诚实口径（发布前的本地等价证据）

口径纪律沿用 `plan/07` §七–§十一：**不写"CI 绿"四个字，直到真有远端 run**。
发布前一切 CI 类结论只写"本地等价校验（未接远端，CI 待首推验证）"。

| 等价物 | 本次（M6 收尾前）结果 |
|---|---|
| `py -3.8 -X utf8 -m pytest -q` | 见 §八 实测记录 |
| `py -3.12 -X utf8 -m pytest -q` | 见 §八 实测记录 |
| `py -3.12 -X utf8 tools/verify_offline.py --strict` | 见 §八 实测记录 |
| `radar bench`（整矩阵） | 15/15 场景、174 项检查、exit 0 |
| `python -m agent_conflict_radar.bench.gen --check` | 两层断言 + 提交 sha 复算全过，exit 0 |
| `tools/verify_mutation.py` | 36 组变异全部被抓到（M5 口径） |
| `scripts/check_release.py` | 离线 **无 FAIL**（当轮条数以门输出为准） |
| `scripts/check_release.py --mutation` | **检查项数 == 变异组数**，逐条被打红（当轮 19 ↔ 19） |
| `scripts/check_release.py --build-asset` | 同一 ref 连跑两次 sha256 相同（发布件可复现） |

---

## 七、风险与已知边界（不粉饰）

1. **同类低星项目混战**：多 agent 冲突检测赛道已有若干工具；本仓的差异点是"写入前四级粒度 +
   冻结合成矩阵 + 可复跑评分"，不是首创声明。
2. **符号级已被 `wit` 口头占位**：本仓不称首创，只称"独立实现 + 可复跑真值"。
3. **本机真实并行冲突样本为 0**：验收主体是**合成矩阵**，不得用真实样本数包装检出率。
4. **跨平台逐字节一致未实测**：`last_run.json` 的双跑一致只在 Windows/3.12 上验过。
5. **`report.notify=true` 在本机不可用**：真实结果是 `notify_unavailable`，如实登记，不是缺陷。
6. **`symbol.min_overlap_lines` 是遗留键**（不消费）：判定规则是"同一符号 ∪ 间距 ≤ 容差"。

---

## 八、tag 后追加事实

> ⚠️ **本节只在 tag 之后追加**，不修改上文任何内容。每条都写**真实 UTC 时刻**与可复跑命令。
> 本节首次落地：2026-10-18T08:15Z。

### 8.1 时间线（全部真实 UTC）

| 时刻（UTC） | 动作 | 结果 |
|---|---|---|
| 2026-10-18T06:32:29Z | `gh repo create yuluo554/agent-conflict-radar --public` | 公开仓库创建成功 |
| 2026-10-18T06:32:39Z | `git push -u origin main`（提交 `c27a171`） | 推送成功 |
| 2026-10-18T06:40:27Z | CI 首跑（run `39104421327`）结束 | ❌ **四腿全红**（照录，未抹除） |
| 2026-10-18T07:20Z | 第二轮（`dd4f304`，run `39106857401`） | ❌ Windows 两腿红（ubuntu 已绿） |
| 2026-10-18T07:35Z | 第三轮（`b954155`，run `39107533253`） | ❌ Windows 两腿红（仅 1 条测试） |
| 2026-10-18T07:44:39Z | 第四轮（`ded85f8`，run `39108203623`） | ✅ **四腿全绿** |
| 2026-10-18T07:44:39Z | `git tag -a v0.0.1`（annotated，tagger 邮箱为 GitHub noreply） | tag 对象 `bf26e6f1…` → commit `ded85f8` |
| 2026-10-18T07:47Z | `git push origin v0.0.1` | tag push 触发 run `39108822514` |
| 2026-10-18T07:52Z | tag push 的 CI 结束 | ✅ **四腿全绿** |
| 2026-10-18T07:55:35Z | `gh release create v0.0.1` + 手工上传附件 | Release 创建成功 |
| 2026-10-18T07:55:47Z | `--record-assets` → `plan/release-assets.json` | 登记 1 个附件；追加提交 `b6c7ec1` |
| 2026-10-18T08:03:50Z | 登记提交的 CI（run `39109515916`） | ❌ 四腿红（`test_not_published_...` 前提过时，已在下一提交修复） |
| 2026-10-18T08:12Z | 发布门判据修正提交 `f953821`（run `39110126482`） | ✅ **四腿全绿** |
| 2026-10-18T08:35Z | 文档回写提交 `aa12feb`（run `39111930352`） | ❌ Windows 两腿红：文档里写了 runner 的真实用户名（**真泄露**，非误报） |
| 2026-10-18T08:45Z | 脱敏提交 `a1e4d72`（run `39112648142`） | ✅ **四腿全绿**（末轮） |

### 8.2 CI 首跑失败的原因（**照录，不抹除**）

首跑四腿全红，暴露两个**本地同平台跑不出来**的真实缺陷：

1. **ubuntu 两腿**：`intent._is_clean_relative("C:/abs/a.py")` 在 POSIX 上返回 `True`
   ——`os.path.isabs` 不认盘符，于是盘符式绝对路径被判成"干净的相对路径"。
   修复：加 `_DRIVE_ABSOLUTE_RE` 与 POSIX 绝对路径两条显式判据（跨平台一致）。
2. **windows 两腿**：runner 的 `TEMP` 是 **8.3 短名**（`C:/Users/<8.3 短名>/...`），而
   `git worktree list` 报长名（`C:/Users/<长名>/...`）。只做 `normcase(normpath())`
   时前缀对不上 → 每个会话都被判成 `in_worktree=False` → **整棵矩阵一个冲突都不产出**
   （而 `scan`/`intent` 层看起来还"正常"）。修复：`discover._norm()` 先 `realpath` 再归一。
3. 第三轮 Windows 仍红：`C07` 脱敏判据把**文档字符串里解释机制的示例路径**当成泄露
   （runner 的真实用户名恰好与示例里的相同）。修复：`.py` 只看**代码位置**的字符串常量
   （与本仓 K16 门禁的既有纪律一致）。
4. 登记提交那轮的失败：`test_not_published_...` 仍假设"仓库没有附件登记"，登记落地后前提过时。
   修复：改用空临时根构造"未发布"世界。
5. **文档回写那轮的失败（第 5 类）**：`plan/06` 与 `plan/RELEASE-M6.md` 里写了 runner 的**真实用户名**
   作为举例。C07 判据是**对的**——在公开仓库里写下 runner 的真实主目录就是泄露。
   修复：改成中性占位符（`<8.3 短名>` / `<长名>`）。
   **这条值得单独记**：它说明"文档里为了解释而写的真实值"与"代码里的真实值"同等危险。

### 8.3 发布门（`--online`）终态

运行：`python scripts/check_release.py --online --tag v0.0.1`
结果：**18 条检查无 FAIL，退出码 0**（离线 C01–C11 + 在线 O01–O07）。
终态复核时刻：2026-10-18T08:52Z，工作树干净（`git status --porcelain` 空）。

其中 O04 与 O07 在真实发布时各暴露一次判据错误，已修正并各配回归测试：

* **O04**：计数单位改为 `(提交, workflow, 事件来源)`。发布提交被 branch push 与 tag push
  各推一次是**正确形态**；按提交计数会让发布提交必红。
* **O07**：期望集合改为 `MANIFEST 覆盖 ∪ setuptools 自动纳入的 src/*.py`，并排除运行产物。
  源码包**本来就不该**含 `.gitignore` / `.github/` / `bench/last_run.json`；
  首版要求"tag 树 ⊆ 包"，等于把源码包当成整仓快照。

### 8.4 附件（手工上传，非 zipball）

| 项 | 值 |
|---|---|
| 名称 | `agent_conflict_radar-0.0.1.tar.gz` |
| 字节数 | `417182` |
| sha256 | `f19688f1d6338b2adc3455bcc3b216e0c0633fda1eafa73da0598ddfa14347ab` |
| 构建路径 | `scripts/check_release.py --build-asset dist/release --tag v0.0.1`（`git archive v0.0.1` → 受控树 → sdist → 归档归一） |
| 本地副本 | `dist/release/agent_conflict_radar-0.0.1.tar.gz`（git 忽略；sha256 登记在 `plan/release-assets.json`） |
| 可复现性 | 同一 tag 连跑两次 sha256 **完全相同**（门 C11 钉住） |
| 远端复核 | O05（集合+字节数）、O06（**真下载**复算 sha256）、O07（与 tag 树逐字节同源）全部 PASS |

**zip/tar 内不含自身 sha256**（K17 自指必过期）；sha256 只出现在 `plan/release-assets.json`
（tag 之后的追加提交）。

### 8.5 「解压即用」实证（中立目录）

在**解包目录之外**的中立目录运行，工作目录零残留：

```
下载件 sha256 = f19688f1…47ab  （与登记一致）
PYTHONPATH=<解包>/agent_conflict_radar-0.0.1/src python -m agent_conflict_radar --version
  → agent-conflict-radar 0.0.1
… selftest
  → 自检通过：配置 / 退出码契约 / 序列化契约 / 阶段表 / 包版本 五项正常。
… bench --bench-dir <解包>/agent_conflict_radar-0.0.1/bench
  → 15/15 场景、174 项检查、覆盖度达标、exit 0
中立目录文件数（跑完后）：0
```

### 8.6 发布门修正带来的仓内变更（tag 之后，**不改 tag 树**）

tag `v0.0.1` **仍指向 `ded85f8`**。以下内容都是 tag 之后在 `main` 上的追加提交，
属于"发布工具与留档的修正"，不改变已发布的包内容：

| 提交 | 内容 |
|---|---|
| `b6c7ec1` | 附件 sha256 登记 `plan/release-assets.json` |
| `f953821` | 发布门 O04 / O07 判据修正 + 3 条回归测试（**包内容未变**，见下条核验） |

**核验"包未变"**：`--build-asset --tag v0.0.1` 仍然只读 tag 树，重算 sha256 仍为
`f19688f1…47ab`（门 C11 与 O07 都对着这条断言）。发布门的修正只改**判据**，不改**产物**。

---

## 九、`v0.0.2` 的 tag 后追加事实

> ⚠️ 本节与 §八 同一纪律：**只在 tag 之后追加**，不改上文任何内容。
> **未发布前本节只写"tag 前已固定的事实"与"待追加清单"**——不许先写好 run id / 附件 sha256 再发布
> （那正是这次要修的形态：文档声称的东西没人核对）。

### 9.1 为什么会有这次发布（tag 前已固定的事实）

`v0.0.1` **已被发布，且不可变**。它的附件下载下来能直接看到一处硬伤：
把 tag 树 clone 出来跑**它自带的**发布门，得到的是 **4 FAIL / exit 1**
（`python scripts/check_release.py --online --tag v0.0.1` → O04 / O05 / O06 / O07）。
根因两条，都在 tag 之后才修好：

1. **O04 的计数口径**（tag 树那版把 branch push 的**全历史** run 拿来对账）→ 已由 `f953821` 修好；
2. **附件登记文件在 tag 树里不存在**（它是 tag 之后的追加提交），而 O05/O06/O07 都依赖它
   → 这三条在发布物自身里**必然 FAIL**。

第 2 条是**流程缺陷，不是判据缺陷**：实测 `plan/release-assets.json` **不在 sdist 内**
（`tar -tzf dist/*.tar.gz | grep -c release-assets` → **0**），所以把登记放到 **tag 之前**入库
**不会改变包的字节**。`v0.0.2` 因此把顺序改成 §四 的 ③–⑥，并用"If 登记入库前后两次 sdist 的
sha256 相同"当场证明它不影响包体——**没有**把任何 FAIL 降级成 WARN/SKIP。

### 9.2 `v0.0.2` 相对 `v0.0.1` 的变更（tag 前）

| 类别 | 变更 |
|---|---|
| 流程（核心） | 附件登记**先进树再打 tag**；tag 树因此自带 `plan/release-assets.json` |
| 门 | 新增第 12 条离线检查 **C12**（文档登记的条数 == 检查表实际条数）+ 对应变异组 → `--mutation` 由 18↔18 变 **19↔19** |
| 测试 | `tests/test_readme_gate.py` 新增**第六面**（README 机读锚 ↔ 检查表），含抽取器非空/可证伪自证；并与门的 C12 **共用同一解析器** |
| 文档 | README 加机读条数锚 `release-gate-counts offline=12 online=7 mutations=19`；`plan/06` 的陈旧读数（"10 条无 FAIL"）改为引用门输出；`plan/00`/`plan/07`/`plan/RELEASE-M6` 的条数改"以门输出为准" |
| 平台 | 地板 3.8 → **3.12**（`requires-python` + classifier + CI 矩阵 + README 四处同口径）；CI actions `checkout@v7` / `setup-python@v7`（注解清零的目标） |
| 打包 | PEP 639：`license = "MIT"` + `license-files = ["LICENSE"]`，删 `License ::` classifier，`setuptools>=77`（`wheel` **保留**） |
| 数据台账 | `data/README.md` 补机读复核锚 `next_review: 2027-01-17`（只加锚，不改既有数字） |
| 交接 | `.gitignore` 加 `update/`（交接目录不再让 C01 变红） |

### 9.3 tag 后事实（真实 UTC）

| 时刻（UTC） | 动作 | 结果 |
|---|---|---|
| 2026-10-20T04:23:07Z | annotated tag `v0.0.2`（tagger 邮箱为 GitHub noreply） | tag 对象 `76f85969…` → commit `48e825e5f2306a9291b8d5e7592c69512941a049`（`git cat-file -t` = `tag`；远端 `git/ref/tags/v0.0.2` 的 `object.sha` 与本地一致 → O02 PASS） |
| 2026-10-20T04:23:57Z→04:32:03Z | branch push run **`39369358990`**（`main`@`48e825e`） | ✅ **两腿全 success**（`ubuntu-latest` / `windows-latest` × py3.12，各 10 步） |
| 2026-10-20T04:24:02Z→04:32:47Z | tag push run **`39369365885`**（`v0.0.2`） | ✅ **两腿全 success**（同上） |
| 2026-10-20T04:34:26Z | `gh release create v0.0.2` + 手工上传附件 | Release 已发布（非 draft / 非 prerelease） |
| 2026-10-20T04:35Z | `scripts/check_release.py --online --tag v0.0.2` | ✅ **19 条检查 0 FAIL，exit 0**（离线 C01–C12 + 在线 O01–O07） |
| 2026-10-20T04:37Z | `git clone --branch v0.0.2` → 跑**该树自带**的门 `--online --tag v0.0.2` | ✅ **19 条检查 0 FAIL，exit 0** ← **发布物自证成立**（改前同一命令在 v0.0.1 上实测 4 FAIL / exit 1） |
| 2026-10-20T04:38Z | 解包 sdist → 中立目录跑 CLI | `--version` → `0.0.2`；`--config <unpacked>/config/radar.toml selftest` → 「自检通过：配置 / 退出码契约 / 序列化契约 / 阶段表 / 包版本 五项正常」；`bench --bench-dir <unpacked>/bench` → **15/15、174 项 0 失败**；中立目录跑完残留 **0** 个文件 |

**附件（手工上传，非 zipball）**

| 项 | 值 |
|---|---|
| 名称 | `agent_conflict_radar-0.0.2.tar.gz` |
| 字节数 | `434407` |
| sha256 | `73c7fb7c621f03d9fbe929fb41c611e552fa78a703296d79ee2d11c56f7e421f`（与 GitHub 附件 `digest` 逐字符相同） |
| 构建路径 | `--build-asset dist/release --tag v0.0.2`（`git archive` → 受控树 → sdist → 归档归一） |
| 可复现性 | 登记入库**前**（提交 `2c3d8ec` 的树）与**后**（tag 树）各建一次，sha256 **逐字符相同** ← 这就是"登记先入库不改变包字节"的实测证据 |
| 远端复核 | O05（集合 + 字节数）、O06（**真下载**复算 sha256）、O07（与 tag 树**逐字节**同源）全部 PASS |

**CI 注解（本轮新矩阵）**：每条 run **1 条 notice**（`ubuntu-latest` 迁移 Ubuntu 26 的公告；
`gh run view --log` 实测该 run 的镜像仍是 `ubuntu24/20261018.339`，即**尚未**迁到 Ubuntu 26）；
**Node20 弃用 warning = 0 条**（改前 4 条）——actions v7 起效。

**本轮仍「未验证」的（不许读成已验证）**：`tools/verify_mutation.py` 的写入型全组变异未跑
（只跑了门自带的内存注入版 `--mutation`，19↔19）；`ubuntu-latest` 真正切到 Ubuntu 26 之后的矩阵未跑。

> 🔴 **后记（2026-10-20，v0.0.3 发布后补写）**：上面那条"写入型变异器未跑"**留了债**。
> 发版后真跑了它，M6 当场抛 `AssertionError`——因为它的 marker 还写着 `__version__ = "0.0.1"`，
> 而包内已是 `0.0.2`。**包内容没错、门也没错**，但"下载者按 README 跑工具会炸"这条与
> v0.0.1 的 4 FAIL 是同一类：**测试与发布门都覆盖不到的地方**。v0.0.3 已修（锚点改不含版本号）
> 并新增门 **C13** + `tests/test_mutation_anchors.py` 把它变成发布前可发现的事。详见 §十。

---

## 十、`v0.0.3` 的 tag 后追加事实

### 10.1 为什么会有这次发布（tag 前已固定的事实）

`v0.0.2` 的附件内容是对的（`--online` 在 tag 树里 19 条 0 FAIL），但它带着一处**工具级**缺陷：

```
$ cd <clone v0.0.2> && python tools/verify_mutation.py --only M6
AssertionError: M6：锚点未命中 src/agent_conflict_radar/__init__.py（marker 漂了或撞了 docstring）
exit 1
```

根因：`tools/verify_mutation.py` 的 M6 变异把 marker 写成 `__version__ = "0.0.1"`，而 v0.0.2 里
`__version__` 已是 `0.0.2`。**这不是"发布物内容陈旧"，是"锚点里含版本号"这个设计缺陷**：
每次发版都会失效，而且只在**运行到那一组**时才暴露——测试全绿、发布门全绿、包已上传，
只有下载者会撞上。

修法（**不放宽任何判据**）：

1. 锚点改成 `__version__ = "` + 把余下的原值注释掉 → **不含版本号**，发版不再失效；
2. 新增离线检查 **C13**：AST 解析 `tools/verify_mutation.py` 的 MUTATIONS 表，断言每组
   marker 目标文件存在且**恰好命中 1 次**、replacement ≠ marker、包版本文件的锚点**不含版本号字面量**；
3. 新增测试 `tests/test_mutation_anchors.py`（5 条）：同一套判据 + "组号唯一" + "`must_fail` 指向的
   测试必须真实存在"（pytest 对不存在的 node id 返回非零，会被变异脚本误读成"抓到了"）+ 一条
   **可证伪自证**（人为造坏的三种锚点必须被报出来）；
4. 配变异组 **R20** → 门的 `--mutation` 由 19↔19 变 **20↔20**。

**负控（在 v0.0.2 的发布物上实测）**：把新测试拷进 v0.0.2 的 tag 树再跑 → **2 failed / 3 passed**，
报的正是 `M6：marker 在 … 里命中 0 次` 与 `锚点里含版本号字面量`。

### 10.2 `v0.0.3` 相对 `v0.0.2` 的变更（tag 前）

| 类别 | 变更 |
|---|---|
| 工具（核心） | `tools/verify_mutation.py` 的 M6 锚点改为**不含版本号**（`__version__ = "` + 注释余值） |
| 门 | 新增第 13 条离线检查 **C13**（变异脚本锚点可落）+ 变异组 R20 → `--mutation` **20↔20** |
| 测试 | 新增 `tests/test_mutation_anchors.py`（5 条，含可证伪自证）；全套 **398 passed / 1 skipped** |
| 文档 | README 机读锚改 `offline=13 online=7 mutations=20`、区间改 `C01–C13`；`plan/07` 新增 **K23** |

### 10.3 tag 后事实（真实 UTC）

（发版后追加；见下方表格）
