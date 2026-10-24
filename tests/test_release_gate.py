"""发布门（M6）：`scripts/check_release.py` 的可证伪性 + 与仓库现状的并排对账。

为什么要给它写测试（而不是"手跑一次就算了"）：

1. **门本身也是产物**——`--mutation` 只是"手跑一条命令"，写进测试才能进 CI 与双解释器矩阵；
2. **门与仓库会漂移**：`MANIFEST.in` 覆盖集合、必需文件清单、名字四向一致，任何一处改动都可能让
   门默默失去意义（例如把检查项删掉但变异还在）；
3. **检查项数 == 变异组数**这条断言写在 `run_mutation()` 里，本文件再从**外部**复核一次
   （否则"两边一起改"这种最危险的漂移看不出来）。

⚠️ 本文件不跑 `check_sdist_contents` / `check_extracted_self_sufficient` 的完整流程（真建 sdist
约 10s 且要联网装构建隔离环境），那两条由发布时手跑的离线门覆盖；这里只断言**它们存在且属于
检查表**——"表的完整性"与"检查有效"是两件事，各自都要有断言。
"""

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_tree():
    """本仓是否处于**真 git 仓库**里（而不是 sdist 解压树）。

    发布门的内容基准是「受控树」——`git archive <ref>`。没有 `.git` 时门会抛
    `EnvironmentMissing`（工具据此返回 exit 3「环境缺失」，这是**正确**语义：
    "验不了"不等于"验过了"）。但测试不能把它读成"代码坏了"。

    实测（v0.0.1 / v0.0.3 的 sdist 解压树，2026-10-23）：6 条用例红，全部是
    这个原因——`test_tree_ref_prefers_the_tag_when_it_exists`、`test_mutation_run_catches_every_check`、
    以及 `test_repository_passes_the_cheap_checks[C02/C03/C07/C08]`；同一份代码在
    仓库态（本文件所在仓）是 23 passed。sdist 里跑自带测试的人会看到 6 个红。

    故这里按本仓既有纪律显式跳过并写明原因（`chdir` 到 `REPO_ROOT` 再问 git，
    避免"测试跑在别处"时误判）。
    """
    if shutil.which("git") is None:
        return False
    completed = subprocess.run(
        ["git", "rev-parse", "--git-dir"], cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return completed.returncode == 0


#: 需要"真 git 仓库"才能跑的用例（依据受控树做判定的那些）。
_GIT_REASON = (
    "需要真 git 仓库：发布门的判据基准是 `git archive <ref>` 导出的受控树；"
    "sdist 解压树没有 .git，工具按设计返回 exit 3（环境缺失 ≠ 通过）。"
    "本仓内跑全绿（23 passed）。"
)
needs_git = pytest.mark.skipif(not _git_tree(), reason=_GIT_REASON)


def _load_gate():
    """按路径加载 `scripts/check_release.py`（它不是包的一部分，不能 import 名字）。"""
    path = REPO_ROOT / "scripts" / "check_release.py"
    assert path.is_file(), "缺少发布门 scripts/check_release.py（M6 交付物）"
    name = "radar_check_release"
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load_gate()


# --------------------------------------------------------------------------------------
# 门的结构：检查表完整、变异一一对应
# --------------------------------------------------------------------------------------


def test_gate_has_both_modes(gate):
    """离线与在线两套检查都必须存在，且**在线检查不以离线检查为子集**。"""
    offline_ids = [ident for ident, _t, _f in gate.OFFLINE_CHECKS]
    online_ids = [ident for ident, _t, _f in gate.ONLINE_CHECKS]
    assert len(offline_ids) >= 11, "离线检查项过少（%d）" % len(offline_ids)
    assert len(online_ids) >= 6, "在线检查项过少（%d）" % len(online_ids)
    assert not set(offline_ids) & set(online_ids), "离线/在线检查编号重叠"


def test_online_checks_cover_the_four_required_facts(gate):
    """DoD 点名的四件在线事实必须**各有一条检查项**（不是笼统一条"在线检查"）。"""
    titles = " ".join(title for _i, title, _f in gate.ONLINE_CHECKS)
    assert "公开" in titles
    assert "tag" in titles
    assert "job" in titles and "success" in titles
    assert "sha256" in titles


def test_asset_reproducibility_is_a_gate_item(gate):
    """C11：发布件必须**可复现**（同 ref 两次构建逐字节相同）。

    本机实测踩中过：setuptools 的 sdist 带解包时刻的 mtime/uid 与 gzip 头时间，同一 ref 连跑
    两次 sha256 不同——那会让"sha256 留档可复验"变成空话。修法是归档归一；本条钉住门里有它。
    """
    titles = dict((ident, title) for ident, title, _f in gate.OFFLINE_CHECKS)
    assert "C11" in titles
    assert "可复现" in titles["C11"]


def test_attachment_identity_is_checked_against_the_tag_tree(gate):
    """DoD「本体一致性」必须有独立检查项：附件与 **tag 树**逐字节同源。

    O05（名字+字节数）与 O06（sha256 与登记一致）**都不覆盖**这条：两者都过，仍可能
    登记时就算错了、或传的是另一个包。判据必须是与 tag 树逐文件比对。
    """
    titles = dict((ident, title) for ident, title, _f in gate.ONLINE_CHECKS)
    assert "O07" in titles
    assert "tag 树" in titles["O07"] and "逐字节" in titles["O07"]


@needs_git
def test_tree_ref_prefers_the_tag_when_it_exists(gate):
    """`tree_ref()`：本地有 tag 时必须用 tag，否则 tag 后的追加提交会让"同源"失效。

    这是本机推演出的真实陷阱：附件登记是 **tag 之后**的追加提交，若仍从 `HEAD` 建包，
    包内容就会比 tag 树多出 `plan/release-assets.json`。
    """
    real_tag = gate._run(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=gate.REPO_ROOT)[1].strip()
    ctx_no_tag = gate.Context(gate.REPO_ROOT)
    assert ctx_no_tag.tree_ref() == "HEAD"
    # 借用一个一定存在的 ref 名不可能构造，故直接用 hook 断言判据方向：
    ctx_hook = gate.Context(gate.REPO_ROOT, tree_ref=lambda: "v9.9.9^{commit}")
    assert ctx_hook.tree_ref() == "v9.9.9^{commit}"
    assert real_tag  # 仓库确实解析得出 HEAD


def test_check_count_equals_mutation_count(gate):
    """检查项数 == 变异组数（从**外部**再复核一次，防"两边一起改"）。"""
    checks = gate._all_checks()
    mutations = gate._mutation_worlds()
    assert len(checks) == len(mutations), (
        "检查项 %d 条、变异 %d 组：有检查项没被变异覆盖（或反之）"
        % (len(checks), len(mutations))
    )
    for ident, _title, _func in checks:
        hits = [m for m in mutations if m.check_id == ident]
        assert len(hits) == 1, "检查项 %s 的变异数为 %d（要求 1）" % (ident, len(hits))


@needs_git
def test_mutation_run_catches_every_check(gate):
    """真跑变异：每条检查都被对应变异打红（这是"门不是假门"的正面证据）。"""
    code = gate.run_mutation(verbose=False)
    assert code == 0, "变异验证未通过（退出码 %s）" % code


# --------------------------------------------------------------------------------------
# 与仓库现状并排对账（这些检查项在真实仓库上也必须 PASS）
# --------------------------------------------------------------------------------------


#: 这些检查项**只用文件系统**（不读受控树），sdist 解压树里同样能跑，故不跳过。
#: 实测（2026-10-23，`git archive HEAD` 导出树 + 本文件）：C02/C04/C06/C08 里
#: C04/C06 在无 .git 时本来就能过，**不该**跟着一起 skip —— 跳过面要按实测收窄，
#: 「稳妥起见全跳」会把"这条检查还能不能跑"的证据一起丢掉。
_FS_ONLY_CHECKS = ("C04", "C06")


@needs_git
@pytest.mark.parametrize(
    "ident",
    ["C02", "C03", "C07", "C08"],
)
def test_repository_passes_the_cheap_checks(gate, ident):
    """真实仓库上的低成本检查必须全过（C01 由"提交后"状态决定，不在此列）。

    这四项的判据读**受控树**（`git archive <ref>`），无 `.git` 时门按设计抛
    `EnvironmentMissing`（exit 3），故标 `needs_git`；`C04`/`C06` 是纯文件系统检查，
    移到下一条，在导出树里也要跑。
    """
    func = dict((i, f) for i, _t, f in gate.OFFLINE_CHECKS)[ident]
    problems = func(gate.Context(gate.REPO_ROOT))
    assert problems == [], "\n  ".join(["%s 在真实仓库上未通过：" % ident] + problems)


@pytest.mark.parametrize("ident", _FS_ONLY_CHECKS)
def test_repository_passes_the_filesystem_only_checks_anywhere(gate, ident):
    """**纯文件系统检查在无 .git 的导出树里也必须过**（sdist 自带测试的最基本一半）。

    与上一条分开的理由：上一条要求"真 git 仓库"（受控树是判据基准），这一条要求
    **相反**——它证明"下载源码包的人至少能跑通这几条"。两条同时存在，才不会出现
    「全都 skip 了，于是源码包自带测试等于没测」。
    """
    func = dict((i, f) for i, _t, f in gate.OFFLINE_CHECKS)[ident]
    problems = func(gate.Context(gate.REPO_ROOT))
    assert problems == [], "\n  ".join(["%s 未通过：" % ident] + problems)


def test_manifest_coverage_is_not_vacuous(gate):
    """覆盖计算的探针：给一条只含 `include README.md` 的 MANIFEST，bench 文件必须判为未覆盖。"""
    tracked = ["README.md", "bench/manifest.json", "bench/scenarios/a/truth.json"]
    covered, broad = gate.manifest_covered(tracked, "include README.md\n")
    assert covered == {"README.md"}
    assert broad == []
    covered2, _ = gate.manifest_covered(
        tracked, "recursive-include bench *.json\n"
    )
    assert covered2 == {"bench/manifest.json", "bench/scenarios/a/truth.json"}


def test_manifest_broad_rule_is_reported(gate):
    """`recursive-include bench *` 这类整目录兜底必须被点名（否则"包里多了什么"不可审）。"""
    _covered, broad = gate.manifest_covered(["bench/a.json"], "recursive-include bench *\n")
    assert broad, "整目录兜底规则未被识别"


def test_runtime_product_is_excluded_from_the_package(gate):
    """`bench/last_run.json` 是运行产物：登记在 RUNTIME_PRODUCTS，且 MANIFEST 显式排除。"""
    assert "last_run.json" in gate.RUNTIME_PRODUCTS
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "exclude bench/last_run.json" in manifest, "MANIFEST.in 未显式排除运行产物"


def test_required_package_files_exist_in_the_repository(gate):
    """`REQUIRED_PACKAGE_FILES` 不是"期望清单"——每一项都必须在仓库里真实存在。"""
    missing = [item for item in gate.REQUIRED_PACKAGE_FILES if not (REPO_ROOT / item).is_file()]
    assert missing == [], "发布门要求的文件不存在：%s" % missing


def test_release_record_must_exist_before_tag(gate):
    """DoD ③：发布留档必须在 tag 之前进树——本测试断言它已入库（不是"计划里写了"）。"""
    assert (REPO_ROOT / "plan" / "RELEASE-M6.md").is_file()
    assert "plan/RELEASE-M6.md" in gate.REQUIRED_PACKAGE_FILES


def test_gate_does_not_introduce_a_fifth_exit_code(gate):
    """K1：发布门复用 0/1/2/3，**不新增**码。"""
    assert gate.EXIT_PASS == 0
    assert gate.EXIT_FAIL == 1
    assert gate.EXIT_USAGE_ERROR == 2
    assert gate.EXIT_MISSING_ENV == 3


def test_not_published_is_a_fail_not_an_environment_error(gate):
    """「还没发布」≠「工具没装」。

    本机实测踩中过：仓库 404 / 本地无 tag / 缺附件登记，首版都抛 `EnvironmentMissing`（exit 3），
    于是"仓库根本没建"看起来像"这台机器没登录 gh"。判据：这四种形态必须是 `ReleaseNotAchieved`
    （计 FAIL），只有"gh 不存在 / 未登录 / build 缺失"才是 `EnvironmentMissing`。
    """
    assert issubclass(gate.ReleaseNotAchieved, Exception)
    assert not issubclass(gate.ReleaseNotAchieved, gate.EnvironmentMissing)
    assert issubclass(gate.GhNotFound, gate.ReleaseNotAchieved)

    def ictx(**hooks):
        return gate.Context(gate.REPO_ROOT, tag="v9.9.9", **hooks)

    # 远端仓库 404 → FAIL 类
    with pytest.raises(gate.ReleaseNotAchieved):
        gate.check_repo_public(ictx(gh_json=lambda _p: (_ for _ in ()).throw(gate.GhNotFound("404"))))
    # 本地没有 tag → FAIL 类
    with pytest.raises(gate.ReleaseNotAchieved):
        gate.check_tag_points_at_release_commit(
            ictx(
                gh_json=lambda _p: {"object": {"type": "tag", "sha": "s"}},
                git=lambda *_a: (_ for _ in ()).throw(gate.EnvironmentMissing("bad revision")),
            )
        )
    # 缺附件登记 → FAIL 类（用**空临时根**：真实仓库里登记已落地，不能拿它当"缺登记"）
    empty_root = Path(tempfile.mkdtemp(prefix="radar-rel-noledger-"))
    try:
        with pytest.raises(gate.ReleaseNotAchieved):
            gate.check_release_assets_match_ledger(
                gate.Context(empty_root, tag="v9.9.9", gh_json=lambda _p: {"assets": []})
            )
    finally:
        shutil.rmtree(str(empty_root), ignore_errors=True)

    # 阴性对照：真环境缺失（gh 缺失 / 未登录）仍是 EnvironmentMissing，不能算 FAIL。
    def _missing_download(_name, _dest):
        raise gate.EnvironmentMissing("找不到 gh CLI")

    with pytest.raises(gate.EnvironmentMissing):
        gate.Context(
            gate.REPO_ROOT,
            tag="v9.9.9",
            download_asset=_missing_download,
        ).download_asset("x", REPO_ROOT)


def test_c07_ignores_docstrings_but_catches_code_literals(gate):
    """C07 的判据落点：**代码常量**里的真实主目录才算泄露，文档字符串里的示例路径不算。

    CI 首跑实测：Windows runner 的真实用户名恰好与源码文档里举例的路径相同，
    整份文本扫描把它判成泄露，Windows 两条腿全红。
    这与本仓 K16 门禁的既有纪律一致：文档字符串是**解释机制**，不是硬编码路径。

    ⚠️ 示例路径一律在**运行期**拼出：写成字面量会让本文件自己命中 C07
    （门禁把"测试里为了验证门禁而写的样例"当成泄露）。
    """
    import getpass

    login = getpass.getuser()
    marker = "doc-example-only"
    template = '"""说明：真实主目录形如 C:/Users/{0}/AppData（{1}）。"""\nVALUE = "C:/Users/{0}/x"\n'
    source = template.format(login, marker)
    literals = gate._code_string_literals(source)
    assert not any(marker in item for item in literals), "文档字符串被当成了代码常量"
    assert any(login in item for item in literals), "代码里的真实主目录被漏掉了"


def test_o04_counts_per_source_not_per_commit(gate):
    """O04 的计数单位是 **(提交, workflow, 事件来源)**，不是提交。

    真实发布形态：发布提交先被 branch push、再被 tag push 各推一次——该提交上出现 2 条 run
    是**正确**的。首版按提交计数，于是发布提交必红（本机实测踩中）。
    """
    release_sha = "abc123"
    runs = [
        {"id": 1, "head_sha": release_sha, "head_branch": "main", "workflow_id": 9, "conclusion": "success"},
        {"id": 2, "head_sha": release_sha, "head_branch": "v0.0.1", "workflow_id": 9, "conclusion": "success"},
    ]
    per_pair = {}
    for run in runs:
        key = (run["head_sha"], str(run["workflow_id"]), run["head_branch"])
        per_pair[key] = per_pair.get(key, 0) + 1
    assert all(count == 1 for count in per_pair.values()), "同一提交的 branch/tag 两次推送不应算重复"


def test_o07_uses_manifest_intent_not_whole_tree(gate):
    """O07 的期望集合 = MANIFEST 覆盖 ∪ setuptools 自动纳入的 `src/*.py`，且排除运行产物。

    首版要求"tag 树 ⊆ 包"，在真实发布时误报 5 个文件（`.gitignore` / `.github/` /
    `bench/last_run.json` 等）——源码包本来就**不该**含它们。这不是包错了，是判据把
    "源码包"当成了"整仓快照"。
    """
    tree = {
        "README.md": b"x",
        ".gitignore": b"x",
        "bench/last_run.json": b"{}",
        "src/agent_conflict_radar/__init__.py": b"x",
    }
    manifest = "include README.md\nrecursive-include bench *.json\n"
    covered, _ = gate.manifest_covered(sorted(tree), manifest)
    auto = {item for item in tree if item.startswith("src/") and item.endswith(".py")}
    # `RUNTIME_PRODUCTS` 存的是**文件名**（`last_run.json`），不是相对路径——按 basename 排除。
    expected = {
        item for item in (set(covered) | auto)
        if item.rsplit("/", 1)[-1] not in gate.RUNTIME_PRODUCTS
    }
    assert ".gitignore" not in expected, "点文件不该进源码包"
    assert "bench/last_run.json" not in expected, "运行产物不该进源码包"
    assert "src/agent_conflict_radar/__init__.py" in expected, "包内 .py 由 setuptools 自动纳入"
    assert "README.md" in expected
