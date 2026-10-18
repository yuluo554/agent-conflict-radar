"""合成冲突矩阵与植入真值的守门（M1 DoD：矩阵可重建 / 真值可复算 / 两层 `--check`）。

四条判据，分别对应一次真实踩过的坑：

1. **真值可独立复算**（K9）：本文件**不 import 检测引擎**，只读 `bench/` 的冻结产物 + `config`，
   用 ast 与行区间自己算出期望——如果本文件需要调引擎才能断言，那真值就是"引擎自证"。
2. **冻结产物可重建**（K10）：生成器重跑到临时目录 → 与仓库里的 `bench/` 逐字节比对。
3. **零真实值**（K11）：白名单之外的东西（真实 UUID、真实用户名、本机绝对路径）出现即红。
4. **生成侧与生产侧序列化各一份实现**（K10）：逐字节一致是**测试断言**出来的，
   不是靠"顺手 import 同一份实现"保证的——后者会让两份契约的漂移永远测不出来。
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import serialize
from agent_conflict_radar.bench import gen

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "bench"
SRC_ROOT = REPO_ROOT / "src"

#: 真值里允许出现的白名单形态（K11）。**真实 UUID 一律不许出现**——合成 session id 是 `sess-radar-NNNN`。
REAL_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)


def _git_available():
    return subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0


pytestmark = pytest.mark.skipif(not _git_available(), reason="物化合成仓库需要 git（缺依赖不是通过）")


# --------------------------------------------------------------------------------------
# 冻结产物存在性与布局
# --------------------------------------------------------------------------------------


def test_frozen_tree_exists_and_covers_every_scenario():
    manifest = json.loads((BENCH_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator_version"] == gen.GENERATOR_VERSION
    assert sorted(entry["id"] for entry in manifest["scenarios"]) == sorted(gen.scenario_ids())
    for entry in manifest["scenarios"]:
        sdir = BENCH_DIR / "scenarios" / entry["id"]
        assert (sdir / "truth.json").is_file(), "缺少真值：%s" % entry["id"]
        assert (sdir / "repo" / "src" / "alpha.py").is_file(), "缺少合成仓库基线：%s" % entry["id"]
        assert list((sdir / "sessions").rglob("*.jsonl")), "缺少会话日志：%s" % entry["id"]


def test_manifest_coverage_is_a_set_cover_with_no_missing_types():
    manifest = json.loads((BENCH_DIR / "manifest.json").read_text(encoding="utf-8"))
    coverage = manifest["coverage"]
    assert coverage["missing_types"] == [], "覆盖度缺类：%s" % coverage["missing_types"]
    for name, minimum in coverage["min_count_by_type"].items():
        assert coverage["count_by_type"].get(name, 0) >= minimum, "%s 未达最低条数" % name
    assert coverage["threshold_pair"]["hit_case"] in gen.scenario_ids()
    assert coverage["threshold_pair"]["miss_case"] in gen.scenario_ids()
    assert coverage["counting_unit"].startswith("用例条目数"), "计数口径必须先声明（K12）"
    assert "非穷举" in coverage["sampling_notice"], "必须显式声明抽样覆盖非穷举"


def test_generator_check_passes_on_the_frozen_tree():
    """两层断言 + 提交 sha 复算（这是 CI 里跑的同一条命令）。"""
    completed = subprocess.run(
        [sys.executable, "-m", "agent_conflict_radar.bench.gen", "--check"],
        cwd=str(REPO_ROOT),
        env=dict(os.environ, PYTHONPATH=str(SRC_ROOT), PYTHONUTF8="1"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")


def test_check_actually_detects_a_tampered_truth(tmp_path):
    """可证伪性：往真值里加一个 `observed_*` 字段 → `--check` 必须红。

    判别 = "把被测行为弄坏，门会红吗？"——只断言"正常时通过"的门，可能是空转的。
    """
    copied = tmp_path / "bench"
    import shutil

    shutil.copytree(str(BENCH_DIR), str(copied))
    truth_path = copied / "scenarios" / "same_symbol_diff_lines" / "truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["observed_conflicts"] = []
    truth_path.write_text(serialize.dumps_json(truth), encoding="utf-8")
    failures = gen.check(str(copied))
    assert any("observed_*" in item for item in failures), failures


def test_check_detects_a_threshold_drift(tmp_path):
    """可证伪性：把 config 里的相邻容差改掉 → 真值的边界关系必须当场变红。

    这条守的是"6a/6b 的期望建立在阈值边界上"这件事本身：阈值变了而真值没重生成，
    矩阵就变成了"用旧边界测新引擎"。
    """
    from agent_conflict_radar import config as config_module

    import shutil

    copied = tmp_path / "bench"
    shutil.copytree(str(BENCH_DIR), str(copied))
    text = (REPO_ROOT / "config" / "radar.toml").read_text(encoding="utf-8")
    mutated = text.replace("adjacent_tolerance = 3", "adjacent_tolerance = 9")
    assert mutated != text
    config_path = tmp_path / "radar.toml"
    config_path.write_text(mutated, encoding="utf-8")

    original_load = config_module.load
    try:
        config_module.load = lambda path=None, start=None: original_load(str(config_path))
        gen.load_config = config_module.load
        failures = gen.check(str(copied))
    finally:
        config_module.load = original_load
        gen.load_config = original_load
    assert any("边界关系不成立" in item for item in failures), failures


# --------------------------------------------------------------------------------------
# 真值语义：无 observed_* / 有反向样例 / 期望可由输入独立复算
# --------------------------------------------------------------------------------------


def _truths():
    manifest = json.loads((BENCH_DIR / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["scenarios"]:
        path = BENCH_DIR / "scenarios" / entry["id"] / "truth.json"
        yield entry["id"], json.loads(path.read_text(encoding="utf-8"))


def test_every_truth_has_forbidden_samples_and_no_observed_fields():
    for ident, truth in _truths():
        assert truth["objects_forbidden"], "%s 缺反向样例（K9）" % ident
        flattened = json.dumps(truth, ensure_ascii=False)
        assert "observed_" not in flattened, "%s 出现 observed_* 字段" % ident
        for path in _walk(truth):
            if path.startswith("thresholds_ref"):
                # 例外：`thresholds_ref` 是**唯一**允许出现阈值键名的地方，而且它的值必须是 config 引用
                # （由 test_threshold_refs_are_symbolic 断言）——键名在那里是"指向"，不是"复制数值"。
                continue
            leaf = path.rsplit(".", 1)[-1]
            assert leaf not in gen.FORBIDDEN_TRUTH_KEYS, "%s 内嵌策略数值键 %r" % (ident, leaf)


def _walk(node, prefix=""):
    if isinstance(node, dict):
        for key in sorted(node):
            path = "%s.%s" % (prefix, key) if prefix else key
            yield path
            yield from _walk(node[key], path)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, prefix)


def test_expectations_are_recomputable_without_the_detection_engine():
    """**独立复算**：只用 `repo/` 原文（ast）+ 真值里的几何 + config 阈值，重新推出期望集合。

    这里刻意不 import `intent` / `detect`（M2/M3 的产物）：真值若与引擎同源，
    引擎全坏也会全绿（`plan/05` §4.1 的判别句）。
    """
    from agent_conflict_radar import config as config_module

    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    tolerance = cfg.get("symbol", "adjacent_tolerance")

    for ident, truth in _truths():
        geometry = truth["geometry"]
        sides = geometry["sides"]
        pair = geometry["pair"]
        repo_dir = BENCH_DIR / "scenarios" / ident / "repo"

        # 1) 符号区间：直接从 repo/ 原文用 ast 复算，必须与真值登记的一致。
        for side in sides:
            lines = (repo_dir / side["path"]).read_text(encoding="utf-8").rstrip("\n").split("\n")
            recomputed = _symbol_ranges(lines)
            assert recomputed[side["symbol"]] == tuple(geometry["symbols"][side["path"]][side["symbol"]])
            low, high = recomputed[side["symbol"]]
            assert low <= side["changed"][0] and side["changed"][1] <= high

        # 2) 粒度集合：按几何与阈值重新推（不读引擎、不读 levels_expected）。
        expected = set()
        if pair["same_file"]:
            expected.add("file")
        if truth["git_expected_merge_exit"] == 1:
            expected.add("block")
        if pair["same_file"] and pair["derived_same_parent"]:
            expected = set()  # 同一 parent 派生的 subagent：整对不出记录（场景 4）
        elif pair["same_file"]:
            if pair["symbol_relation"] == "same":
                expected.add("symbol")
            elif pair["gap_lines"] is not None and pair["gap_lines"] <= tolerance:
                expected.add("symbol")
        assert expected == set(truth["levels_expected"]), (
            "%s 的期望与独立复算不符：真值 %r ≠ 复算 %r（真值可能被手改或几何漂了）"
            % (ident, sorted(truth["levels_expected"]), sorted(expected))
        )


def test_threshold_refs_are_symbolic_pointers_not_values():
    """`thresholds_ref` 里只允许出现 `config:<section>.<key>` 形态的**指向**，不许出现数值。"""
    for ident, truth in _truths():
        refs = truth["thresholds_ref"]
        seen = 0
        for key, value in sorted(refs.items()):
            if key == "note":
                continue
            seen += 1
            assert isinstance(value, str) and value.startswith("config:"), "%s.%s=%r 不是 config 引用" % (ident, key, value)
            assert not any(char.isdigit() for char in value.split(":")[0]), "引用里不该出现数值"
        assert seen, "%s 没有登记任何阈值引用" % ident


def _symbol_ranges(lines):
    import ast

    tree = ast.parse("\n".join(lines) + "\n")
    ranges = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ranges[node.name] = (node.lineno, node.end_lineno)
    return ranges


def test_threshold_pair_is_straddling_the_boundary():
    """6a 与 6b 必须**成对**卡在阈值两侧（间距相差正好 1 行）。"""
    by_id = dict(_truths())
    hit = by_id["threshold_exact"]
    miss = by_id["threshold_near_miss"]
    assert hit["geometry"]["pair"]["gap_lines"] + 1 == miss["geometry"]["pair"]["gap_lines"]
    assert "symbol" in hit["levels_expected"] and "symbol" not in miss["levels_expected"]


def test_subagent_scenario_reports_nothing_but_keeps_the_geometry():
    """场景 4 的几何与场景 2 相同——差异只应来自 `derived_same_parent`（防"靠几何蒙对"）。"""
    by_id = dict(_truths())
    same_symbol = by_id["same_symbol_diff_lines"]
    derived = by_id["subagent_derived"]
    for key in ("same_file", "symbol_relation", "gap_lines", "overlap_lines"):
        assert same_symbol["geometry"]["pair"][key] == derived["geometry"]["pair"][key], key
    assert same_symbol["geometry"]["pair"]["derived_same_parent"] is False
    assert derived["geometry"]["pair"]["derived_same_parent"] is True
    assert derived["levels_expected"] == [] and same_symbol["levels_expected"] != []


def test_git_merge_expectations_match_a_real_merge_tree_run(tmp_path):
    """真值里的 `git_expected_merge_exit` 必须与**现场真跑**的 merge-tree 一致。

    这条是"期望值可由输入独立复算"的最硬版本：期望值不是我们说了算，git 说了算。
    """
    for ident in gen.scenario_ids():
        scenario = gen.scenario_by_id(ident)
        dest = tmp_path / ident
        shas = gen.materialize_scenario(scenario, str(dest))
        truth = json.loads((BENCH_DIR / "scenarios" / ident / "truth.json").read_text(encoding="utf-8"))
        assert shas == truth["repo_shas"], "%s 的提交 sha 不可复算" % ident
        branches = sorted(shas["branches"])
        assert len(branches) == 2, "%s 应有两条分支" % ident
        actual = gen.merge_tree_exit(str(dest / "repo"), branches[0], branches[1])
        assert actual == truth["git_expected_merge_exit"], (
            "%s：merge-tree 实测 exit=%s ≠ 真值 %s" % (ident, actual, truth["git_expected_merge_exit"])
        )


# --------------------------------------------------------------------------------------
# 白名单与隐私（K11）
# --------------------------------------------------------------------------------------


def test_frozen_artifacts_contain_no_real_identifiers_or_machine_paths():
    offenders = []
    for path in sorted(BENCH_DIR.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(BENCH_DIR).as_posix()
        if REAL_UUID_RE.search(text):
            offenders.append("%s 含真实 UUID 形态" % rel)
        if re.search(r"(?<![\w.])[A-Za-z]:[\\/]", text):
            offenders.append("%s 含盘符式绝对路径" % rel)
        for marker in ("/home/", "/Users/", "\\Users\\", "/tmp/"):
            if marker in text:
                offenders.append("%s 含本机路径片段 %r" % (rel, marker))
        if "radar-user" in text and "radar-user@" not in text and "radar-user" not in rel:
            # 用户名本身是白名单值；出现就说明用了合成值，不做额外限制——
            # 这里只保留"确实用过白名单用户名"的痕迹，防止有人误删成真实用户名。
            pass
    assert offenders == [], "\n  ".join(offenders)


def test_frozen_sessions_use_whitelisted_ids_and_fixed_base_time():
    for path in sorted((BENCH_DIR / "scenarios").rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            record = json.loads(line)
            blob = json.dumps(record, ensure_ascii=False)
            assert "sess-radar-" in blob or path.name.startswith("sess-radar-"), path
            for stamp in re.findall(r"20\d\d-\d\d-\d\dT", blob):
                assert stamp.startswith("2026-01-01T"), "合成时间戳必须从固定基准 2026-01-01 起（K11）：%s" % stamp


def test_sessions_carry_the_measured_harness_shapes():
    """合成日志必须复现**实测形态**，否则"解析器被真实数据打中"这件事从未被测过。"""
    claude_files = sorted((BENCH_DIR / "scenarios").rglob("sessions/claude/*.jsonl"))
    codex_files = sorted((BENCH_DIR / "scenarios").rglob("sessions/codex/*.jsonl"))
    assert claude_files and codex_files
    for path in claude_files:
        first = json.loads(path.read_text(encoding="utf-8").split("\n")[0])
        assert "message" not in first, "%s 的首行是消息行：与实测（首行多为 last-prompt）不符" % path.name
    for path in codex_files:
        first = json.loads(path.read_text(encoding="utf-8").split("\n")[0])
        assert first.get("type") == "session_meta", "%s 首行不是 session_meta" % path.name
        assert first["payload"].get("cwd")


def test_codex_subagents_have_parent_thread_id_but_no_session_id():
    """实测：子会话没有 `session_id`（只有主会话有），靠 `parent_thread_id` 认父。"""
    root = BENCH_DIR / "scenarios" / "subagent_derived" / "sessions" / "codex"
    metas = {}
    for path in sorted(root.glob("*.jsonl")):
        metas[path.name] = json.loads(path.read_text(encoding="utf-8").split("\n")[0])["payload"]
    children = [payload for payload in metas.values() if "parent_thread_id" in payload]
    parents = [payload for payload in metas.values() if "parent_thread_id" not in payload]
    assert len(children) == 2 and len(parents) == 1
    for payload in children:
        assert "session_id" not in payload, "子会话不该有 session_id（实测 0/157）"
        assert payload["id"].startswith("sess-radar-")
    assert parents[0].get("session_id") == parents[0]["id"]


# --------------------------------------------------------------------------------------
# K10：生成侧与生产侧各一份独立实现，一致性靠逐字节测试
# --------------------------------------------------------------------------------------


def test_generator_serializer_is_an_independent_implementation_with_identical_bytes():
    """生成器的 `_dump_json` 与 `serialize.dumps_json` 必须是**两份实现**、**同一份字节**。"""
    payload = {"b": 1, "a": "中文", "nested": {"z": [1, 2], "y": None}, "flag": True}
    assert gen._dump_json(payload) == serialize.dumps_json(payload)

    # 判据落在**导入面**上（AST），而不是字符串包含：只在文档里提到对方的名字不算共用实现。
    import ast

    tree = ast.parse(Path(gen.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.name)
    assert "dumps_json" not in imported and "normalize_newlines" not in imported, (
        "生成器 import 了生产侧序列化实现：两份契约的漂移就再也测不出来了（K10）"
    )
    assert "write_atomic" in imported, "写盘必须仍走唯一写盘点（K2）"


def test_frozen_json_files_obey_the_frozen_contract():
    """冻结产物本身必须满足 K2：LF 行尾、结尾一个换行、`ensure_ascii=False`、`indent=2`、键有序。"""
    for path in sorted(BENCH_DIR.rglob("*.json")):
        raw = path.read_bytes()
        assert b"\r\n" not in raw, "%s 含 CRLF" % path
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), "%s 结尾换行不合契约" % path
        text = raw.decode("utf-8")
        payload = json.loads(text)
        assert text == serialize.dumps_json(payload), "%s 与冻结序列化契约不逐字节一致" % path


def test_truth_sha256_in_manifest_matches_the_file():
    manifest = json.loads((BENCH_DIR / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["scenarios"]:
        path = BENCH_DIR / "scenarios" / entry["id"] / "truth.json"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["truth_sha256"] == digest, "%s 的台账 sha256 与文件不符" % entry["id"]


def test_check_tolerates_the_runtime_product_but_not_generator_products(tmp_path):
    """`last_run.json` 是**运行产物**，不是生成物；`--check` 必须放行它，但**只放行它**。

    两端都要断言，否则就是假门：
    * 只断"有 last_run.json 时 --check 仍绿"→ 如果实现把整个比对关掉，这条照样绿；
    * 只断"多余文件会红"→ 不能证明 `last_run.json` 真的被放行。
    """
    import shutil

    copied = tmp_path / "bench"
    shutil.copytree(str(BENCH_DIR), str(copied))

    # 1) 放行运行产物：写一份 last_run.json → --check 仍全过。
    (copied / "last_run.json").write_text(
        serialize.dumps_json({"bench": {}, "summary": {"all_passed": True}}), encoding="utf-8"
    )
    assert gen.check(str(copied)) == []

    # 2) 只放行**这一个**名字：换个名字的陈旧文件 → 必须红（验证放行面没有变宽）。
    (copied / "stale-run.json").write_text("{}\n", encoding="utf-8")
    failures = gen.check(str(copied))
    assert any("stale-run.json" in item for item in failures), failures
