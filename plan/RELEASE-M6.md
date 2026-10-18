# RELEASE-M6：发布留档（tag 时刻内容）

> **本文件的使用纪律（DoD ③）**
>
> * 本文件在 **tag 之前**写好并提交，**进 tag 树**；它描述的是"发布这一刻的事实与判定口径"。
> * tag 之后才产生的事实（附件 sha256、真下载复核、CI run id、失败轮次）**一律追加在文末
>   「§八 tag 后追加事实」**，**不覆盖**本文件 §一–§七 的内容。
> * 时间一律写**真实 UTC 时刻**（K7：这是事件记录，不是产物判定）。
> * 本文件**不含**发布附件自身的 sha256——那是 tag 之后的事实，且写进源码包会造成自指
>   （下次构建的字节会变，sha256 必然过期，K17）。附件登记落在 `plan/release-assets.json`。

---

## 一、发布坐标

| 项 | 值 |
|---|---|
| 仓库 | `yuluo554/agent-conflict-radar`（公开） |
| 包名 / 导入名 | `agent-conflict-radar` / `agent_conflict_radar` |
| 版本 | `0.0.1`（`src/agent_conflict_radar/__init__.py` 的 `__version__` 是唯一来源） |
| 许可 | MIT（`LICENSE` 文件 + `pyproject.toml` 的 `license` 元数据） |
| 运行时依赖 | **零**（`dependencies = []`）；dev extra 只有 `pytest` |
| 底线解释器 | Python **3.8**（自写受限 TOML 子集解析器的原因）；主用 3.12 |
| 命令面 | **7/7**：`config` / `selftest` / `scan` / `intent` / `detect` / `report` / `bench` |
| 退出码 | 只有 `0/1/2/3`（K1） |

**名字四向一致**（K14，发布前并排读一遍）：README H1 含 `agent-conflict-radar`；
GitHub 仓库名 `agent-conflict-radar`；`pyproject.toml` 的 `name = "agent-conflict-radar"`；
导入包名 `agent_conflict_radar`（下划线形态）。

---

## 二、发布门（`scripts/check_release.py`）

**刻意不进 CI**：它判的是"发布这件事做完了没有"，而那些状态只在发布时才存在。放进 CI 只能
被跳过或被放宽——那就是假门。

| 模式 | 判据 |
|---|---|
| 默认（离线） | C01–C11：工作树干净 / 无运行产物入库 / 名字四向 / 退出码冻结 / 矩阵自检 / 矩阵机器无关 / 提交面脱敏 / MANIFEST 覆盖 / **真建 sdist 核对** / **解包即用** / **发布件可复现**（同 ref 两次构建逐字节相同） |
| `--online` | O01–O07：仓库公开 / annotated tag 指向发布提交 / CI **逐 job** 全 success / push 事件与 run 对账 / 附件集合与登记一致 / **逐个下载复算 sha256** / **附件与 tag 树逐字节同源** |
| `--mutation` | 门自身的可证伪性：**检查项数 == 变异组数**（18 ↔ 18），每条检查必须被对应变异打红 |

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
1. 本地全绿（双解释器 pytest / 离线冒烟 --strict / bench 全矩阵 / gen --check / mutation）
2. 脱敏复查（入库内容 + 提交元数据邮箱）
3. 提交 M6 交付物（MANIFEST.in / scripts/check_release.py / 本文件）
4. 跑离线发布门：scripts/check_release.py          → 必须 0 FAIL
5. 建仓：gh repo create yuluo554/agent-conflict-radar --public
6. push main                                     → CI 首跑（**失败照录**）
7. CI 绿 → 打 annotated tag（version_tag）→ push tag → tag push 触发一条 run
8. `scripts/check_release.py --build-asset dist/release --tag <tag>` 建出源码包
   （走 `git archive <tag>` → 受控树 → sdist → 归档归一，与门 C09/O07/C11 同一条路径）
   → 手工上传为 Release 附件（**不得**用仓库 zipball 替代）
9. 本地留同名副本 → --record-assets 生成 plan/release-assets.json → **追加提交** push
10. 远端正下载复核：scripts/check_release.py --online --tag <tag>   → 必须 0 FAIL
11. 中立目录解包跑 selftest（"解压即用"实证）
12. 本文件 §八 追加事实 → 追加提交 push
```

**为什么 ⑧ 必须在 ⑦ 之后**：附件必须与 tag 树**逐字节同源**。先打 tag 再建包，才能保证
"包 = tag 树的内容"；反过来先建包再打 tag，中间任何一次提交都会让两者分叉。

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
| `scripts/check_release.py` | 离线 11 条无 FAIL |
| `scripts/check_release.py --mutation` | 18 条检查 ↔ 18 条变异，逐条被打红 |
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

### 8.3 发布门（`--online`）终态

运行：`python scripts/check_release.py --online --tag v0.0.1`
结果：**18 条检查无 FAIL，退出码 0**（离线 C01–C11 + 在线 O01–O07）。

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
