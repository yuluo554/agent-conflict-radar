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
| 默认（离线） | C01–C10：工作树干净 / 无运行产物入库 / 名字四向 / 退出码冻结 / 矩阵自检 / 矩阵机器无关 / 提交面脱敏 / MANIFEST 覆盖 / **真建 sdist 核对** / **解包即用** |
| `--online` | O01–O07：仓库公开 / annotated tag 指向发布提交 / CI **逐 job** 全 success / push 事件与 run 对账 / 附件集合与登记一致 / **逐个下载复算 sha256** / **附件与 tag 树逐字节同源** |
| `--mutation` | 门自身的可证伪性：**检查项数 == 变异组数**（17 ↔ 17），每条检查必须被对应变异打红 |

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
8. 真建 sdist → 手工上传为 Release 附件（**不得**用仓库 zipball 替代）
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
| `scripts/check_release.py` | 离线 10 条无 FAIL |
| `scripts/check_release.py --mutation` | 17 条检查 ↔ 17 条变异，逐条被打红 |

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

（待发布执行后填写。计划登记项：建仓时刻 / push 时刻 / CI 首跑 run id 与结论（含失败轮次）/
tag 对象 sha 与指向的 commit / Release 附件名 + 字节数 + sha256 / `--online` 门运行结果 /
中立目录解包 selftest 结果。）
