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
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    assert len(offline_ids) >= 10, "离线检查项过少（%d）" % len(offline_ids)
    assert len(online_ids) >= 6, "在线检查项过少（%d）" % len(online_ids)
    assert not set(offline_ids) & set(online_ids), "离线/在线检查编号重叠"


def test_online_checks_cover_the_four_required_facts(gate):
    """DoD 点名的四件在线事实必须**各有一条检查项**（不是笼统一条"在线检查"）。"""
    titles = " ".join(title for _i, title, _f in gate.ONLINE_CHECKS)
    assert "公开" in titles
    assert "tag" in titles
    assert "job" in titles and "success" in titles
    assert "sha256" in titles


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


def test_mutation_run_catches_every_check(gate):
    """真跑变异：每条检查都被对应变异打红（这是"门不是假门"的正面证据）。"""
    code = gate.run_mutation(verbose=False)
    assert code == 0, "变异验证未通过（退出码 %s）" % code


# --------------------------------------------------------------------------------------
# 与仓库现状并排对账（这些检查项在真实仓库上也必须 PASS）
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ident",
    ["C02", "C03", "C04", "C06", "C07", "C08"],
)
def test_repository_passes_the_cheap_checks(gate, ident):
    """真实仓库上的低成本检查必须全过（C01 由"提交后"状态决定，不在此列）。"""
    func = dict((i, f) for i, _t, f in gate.OFFLINE_CHECKS)[ident]
    problems = func(gate.Context(gate.REPO_ROOT))
    assert problems == [], "\n  ".join(["%s 在真实仓库上未通过：" % ident] + problems)


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
    # 缺附件登记 → FAIL 类
    with pytest.raises(gate.ReleaseNotAchieved):
        gate.check_release_assets_match_ledger(ictx(gh_json=lambda _p: {"assets": []}))

    # 阴性对照：真环境缺失（gh 缺失 / 未登录）仍是 EnvironmentMissing，不能算 FAIL。
    def _missing_download(_name, _dest):
        raise gate.EnvironmentMissing("找不到 gh CLI")

    with pytest.raises(gate.EnvironmentMissing):
        gate.Context(
            gate.REPO_ROOT,
            tag="v9.9.9",
            download_asset=_missing_download,
        ).download_asset("x", REPO_ROOT)
