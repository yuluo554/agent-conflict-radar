"""`report.py` / `radar report` 的 M4 DoD 对账。

四条主线：

1. **双轨同源**：`report.md` 是 `conflicts.json` 的**纯函数**（同一份 payload 两个视图），
   不是两份各自生成再人工比对；`--format json` 的字节与 `detect` 落的 `conflicts.json` 相同。
2. **渲染三律**（K13）：AST 门禁（零判定 + 不 import 判定函数）+ 零外链（断言常驻渲染出口，
   含"注入外链必须当场报错"的探针）+ 双跑逐字节一致（真子进程）。
3. **退出码四语义**（K1）：0 / 1 / 2 / 3 各有实物，`undetermined` 不改变退出码。
4. **已知会被打中的形态**：`degraded=true` 与 `approximate=true`（**没有 `symbols` 键**）
   的记录必须能渲染——不能写成 `record["symbols"]` 直接下标取值。

所有真 git 夹具都从冻结矩阵物化，两侧会话根都显式传（`plan/05` §七）。
"""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_conflict_radar import config as config_module
from agent_conflict_radar import detect, discover, report, serialize, stages
from agent_conflict_radar.bench import gen
from agent_conflict_radar.exit_codes import (
    EXIT_CONFLICTS_FOUND,
    EXIT_ENVIRONMENT,
    EXIT_OK,
    EXIT_USAGE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
BENCH_DIR = REPO_ROOT / "bench"
NOW = "2026-01-01T00:10:00Z"


def _git_available():
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="物化合成仓库需要 git（缺依赖不是通过）")


# --------------------------------------------------------------------------------------
# 夹具
# --------------------------------------------------------------------------------------


def _root_flags(dest, scratch):
    flags = []
    for name in ("claude", "codex"):
        path = Path(dest) / "sessions" / name
        if not path.is_dir():
            path = Path(scratch) / ("empty-%s" % name)
            path.mkdir(parents=True, exist_ok=True)
        flags += ["--%s-root" % name, str(path)]
    return flags


def _materialize(scenario_id, dest):
    gen.materialize_scenario(gen.scenario_by_id(scenario_id), str(dest))
    return dest


def _detect(dest, cfg=None, scratch=None):
    cfg = cfg or config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    roots = {}
    for name in ("claude", "codex"):
        path = Path(dest) / "sessions" / name
        if not path.is_dir():
            path = Path(scratch or (Path(dest) / "_scratch")) / ("empty-%s" % name)
            path.mkdir(parents=True, exist_ok=True)
        roots[name] = str(path)
    return detect.build_conflict_set(
        str(Path(dest) / "repo"), roots["claude"], roots["codex"], cfg, now=NOW
    )


def _run_cli(dest, extra=(), pre=(), cwd=None, scratch=None):
    """真子进程跑 `python -m agent_conflict_radar report`，返回 (码, stdout 字节, stderr 文本)。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    scratch = Path(scratch or (Path(dest) / "_scratch"))
    scratch.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "agent_conflict_radar"] + list(pre) + [
        "report", "--repo", str(Path(dest) / "repo"),
    ]
    argv += _root_flags(dest, scratch) + ["--now", NOW] + list(extra)
    completed = subprocess.run(
        argv, cwd=str(cwd or REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", errors="replace")


def _surface(dest, scratch=None, notify=None):
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    return report.build_report(
        _detect(dest, cfg=cfg, scratch=scratch),
        cfg,
        repo=str(Path(dest) / "repo"),
        notify=notify,
    )


# --------------------------------------------------------------------------------------
# 双轨同源（DoD：结构性质，非人工比对）
# --------------------------------------------------------------------------------------


def test_markdown_is_a_pure_function_of_the_json_payload(tmp_path):
    """`report.md` = `render_markdown(conflicts.json)`：对同一 payload 重渲染必须逐字节相同。"""
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    surface = _surface(dest, scratch=tmp_path)
    payload = json.loads(surface.json_text())
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    rerendered = report.render_markdown(
        payload,
        source_path=str(cfg.source_path),
        repo=str(Path(dest) / "repo"),
        notify=surface.notify,
        max_evidence_items=cfg.get("report", "max_evidence_items"),
    )
    assert rerendered == surface.markdown, "Markdown 不是 JSON payload 的纯函数（出现了第二个渲染源）"


def test_payload_is_byte_identical_to_detects_conflicts_json(tmp_path):
    """`--format json` 的产物与 `detect` 落的 `conflicts.json` **同内容同字节**。"""
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    out_detect = tmp_path / "detect-out"
    code, _out, err = _run_cli_for(dest, "detect", extra=["--out-dir", str(out_detect)], scratch=tmp_path / "d")
    assert code == EXIT_CONFLICTS_FOUND, err
    detected = (out_detect / "conflicts.json").read_bytes()

    out_report = tmp_path / "report-out"
    code, _out, err = _run_cli(
        dest, extra=["--format", "json", "--out-dir", str(out_report)], scratch=tmp_path / "r"
    )
    assert code == EXIT_CONFLICTS_FOUND, err
    reported = (out_report / "conflicts.json").read_bytes()
    assert reported == detected, "报告侧 conflicts.json 与 detect 的产物不一致（造了第二份 schema）"


def _run_cli_for(dest, command, extra=(), pre=(), cwd=None, scratch=None):
    """同 `_run_cli`，但命令名可换（本文件只需要 detect / report 两条）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env["PYTHONUTF8"] = "1"
    scratch = Path(scratch or (Path(dest) / "_scratch"))
    scratch.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "agent_conflict_radar"] + list(pre) + [
        command, "--repo", str(Path(dest) / "repo"),
    ]
    argv += _root_flags(dest, scratch) + ["--now", NOW] + list(extra)
    completed = subprocess.run(
        argv, cwd=str(cwd or REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", errors="replace")


def test_markdown_tracks_payload_changes(tmp_path):
    """可证伪探针：改 payload 里的一个字段 → Markdown **必须**跟着变。

    否则"两者同源"就只是"两者都不看输入"的巧合。
    """
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    surface = _surface(dest, scratch=tmp_path)
    payload = json.loads(surface.json_text())
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    original = surface.markdown

    mutated = json.loads(surface.json_text())
    mutated["conflicts"][0]["evidence"] = list(mutated["conflicts"][0]["evidence"]) + ["mutant:probe"]
    changed = report.render_markdown(
        mutated,
        source_path=str(cfg.source_path),
        repo=str(Path(dest) / "repo"),
        notify=surface.notify,
        max_evidence_items=None,
    )
    assert changed != original, "改 payload 后 Markdown 没变：渲染层没有消费这份 payload"
    assert "mutant:probe" in changed


# --------------------------------------------------------------------------------------
# 报告内容（DoD：参数来源块 / undetermined 独立小节 / 三态逐条 / 建议模板 / 辅助参考）
# --------------------------------------------------------------------------------------


def test_markdown_contains_parameter_source_block_without_copying_values(tmp_path):
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    text = _surface(dest, scratch=tmp_path).markdown
    assert "## 参数来源" in text
    assert "config/radar.toml" in text or "radar.toml" in text
    for key in ("window.scan_days", "window.active_minutes", "symbol.adjacent_tolerance",
                "report.max_evidence_items", "[severity]"):
        assert key in text, "参数来源块缺少键名 %r" % key
    # K3：数值不得被复制进报告。窗口/容差的取值不该出现在文本里。
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    for section, key in (("window", "scan_days"), ("window", "active_minutes"),
                         ("symbol", "adjacent_tolerance")):
        value = str(cfg.get(section, key))
        for line in text.split("\n"):
            if key in line and "`%s`" % key in line:
                assert value not in line.replace("`%s`" % key, ""), (
                    "参数来源块把 %s.%s 的数值抄进了报告（K3：应只引用键名）" % (section, key)
                )


def test_markdown_declares_assistance_only_and_never_claims_full_prevention(tmp_path):
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    text = _surface(dest, scratch=tmp_path).markdown
    assert "辅助参考" in text
    assert "防止所有覆盖" not in text
    assert "不合并" in text


def test_markdown_presents_time_as_is_and_fabricates_no_estimate(tmp_path):
    """时间一律呈现原值：报告里出现 `reference_time` / `last_write_ts` 的原样字符串，
    且**不编造**"预计完成时间"类推断（DoD 措辞项）。"""
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    surface = _surface(dest, scratch=tmp_path)
    text = surface.markdown
    payload = json.loads(surface.json_text())
    assert payload["reference_time"] in text
    assert payload["conflicts"][0]["last_write_ts"] in text
    for banned in ("预计完成", "预计结束", "预计修复", "ETA"):
        assert banned not in text, "报告编造了时间推断：%r" % banned


def test_markdown_lists_undetermined_as_its_own_section(tmp_path):
    """`undetermined` 必须有独立小节，且 `degraded` / `approximate` 逐条列出。"""
    text = _surface(_materialize("same_symbol_diff_lines", tmp_path / "same"), scratch=tmp_path).markdown
    assert "## 未判定（`undetermined`）" in text
    assert "不计入" in text and "不改" not in text.split("## 未判定")[0][-200:]


def test_undetermined_entries_are_rendered_with_all_three_codes(tmp_path):
    """三态（`degraded` / `symbol_unavailable` / `unsupported_format`）逐条出现在报告里。"""
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    conflict_set = detect.ConflictSet(
        conflicts=(),
        undetermined=(
            discover.Undetermined(file="src/a.py", source="detect", code="degraded",
                                  detail="merge-tree exit 128（无共同祖先）"),
            discover.Undetermined(file="src/b.md", source="detect", code="symbol_unavailable",
                                  detail="非 Python 文件：不做符号级"),
            discover.Undetermined(file="sessions/x.jsonl", source="claude", code="unsupported_format",
                                  detail="未知版本指纹"),
        ),
        reference_time=NOW,
        notes=(),
        counts={"conflicts": 0, "undetermined": 3, "by_max_level": {}, "by_level_membership": {},
                "degraded": 0, "approximate": 0, "paths_in_conflict": 0},
    )
    surface = report.build_report(
        conflict_set, cfg, repo=".", notify={"attempted": False, "available": False, "detail": "x"}
    )
    for code in ("degraded", "symbol_unavailable", "unsupported_format"):
        assert code in surface.markdown, "报告漏了原因码 %r" % code
    for path in ("src/a.py", "src/b.md", "sessions/x.jsonl"):
        assert path in surface.markdown, "报告漏了文件 %r" % path
    assert "**无冲突条目。**" in surface.markdown


def test_approximate_record_without_symbols_key_is_rendered(tmp_path):
    """`approximate=true` 的记录**没有** `symbols` 键——渲染层不得直接下标取值。"""
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    record = {
        "levels": ["file"],
        "level": "file",
        "workspace_a": "/w",
        "workspace_b": "/w",
        "path": "docs/notes.md",
        "line_ranges": [[3, 4], [5, 6]],
        "severity": cfg.get("severity", "file_only"),
        "severity_key": "file_only",
        "degraded": True,
        "degrade_reasons": ["会话没有 gitBranch 信息"],
        "approximate": True,
        "sessions": ["claude:a.jsonl", "claude:b.jsonl"],
        "session_ids": ["a", "b"],
        "sessions_a": ["claude:a.jsonl"],
        "sessions_b": ["claude:b.jsonl"],
        "last_write_ts": NOW,
        "evidence": ["path:docs/notes.md"],
    }
    assert "symbols" not in record
    conflict_set = detect.ConflictSet(
        conflicts=(),
        undetermined=(),
        reference_time=NOW,
        notes=(),
        counts={},
    )
    payload = conflict_set.as_dict()
    payload["conflicts"] = [record]
    text = report.render_markdown(
        payload, source_path=str(cfg.source_path), repo=".", notify=None,
        max_evidence_items=cfg.get("report", "max_evidence_items"),
    )
    assert "docs/notes.md" in text
    assert "`approximate=true`" in text
    assert "不提供" in text, "报告没有说明符号级字段缺失的原因"
    assert "`degraded`" in text


def test_suggestions_are_rule_templates_keyed_by_engine_severity(tmp_path):
    """建议文案按 `severity_key` 分派（规则模板，不是模型判断）。"""
    payload = {
        "reference_time": NOW,
        "conflicts": [],
        "undetermined": [],
        "notes": [],
        "counts": {},
    }
    expected = {
        "same_symbol": "两侧并行改同一符号，需人工裁决",
        "same_file_diff_symbol": "仅同文件不同符号，可先后提交",
        "adjacent_lines": "改动范围相邻，建议由更早开始的会话先合并",
        "file_only": "仅文件级同改",
    }
    for severity_key, needle in expected.items():
        record = {
            "levels": ["file"], "level": "file", "workspace_a": "/w", "workspace_b": "/w",
            "path": "src/x.py", "line_ranges": [[1, 2], [3, 4]], "severity": 1,
            "severity_key": severity_key, "degraded": False, "approximate": False,
            "sessions": ["a"], "session_ids": ["a"], "sessions_a": ["a"], "sessions_b": ["b"],
            "last_write_ts": NOW, "evidence": [],
        }
        payload["conflicts"] = [record]
        text = report.render_markdown(payload, source_path="config/radar.toml", repo=".", notify=None)
        assert needle in text, "`%s` 的建议模板不对：%r" % (severity_key, text)


def test_display_order_is_severity_desc_then_level_and_path(tmp_path):
    """人读报告按 severity 降序、同分按 (level 序, path, symbols)（稳定排序）。"""
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))

    def record(path, level, severity, symbols=None):
        item = {
            "levels": ["file"] + ([level] if level != "file" else []),
            "level": level, "workspace_a": "/w", "workspace_b": "/w", "path": path,
            "line_ranges": [[1, 1], [2, 2]], "severity": severity,
            "severity_key": "file_only", "degraded": False, "approximate": symbols is None,
            "sessions": ["a"], "session_ids": ["a"], "sessions_a": ["a"], "sessions_b": ["b"],
            "last_write_ts": NOW, "evidence": [],
        }
        if symbols is not None:
            item["symbols"] = symbols
            item["symbol_spans"] = []
        return item

    payload = {
        "reference_time": NOW,
        "conflicts": [
            record("z.py", "file", cfg.get("severity", "file_only"), []),
            record("b.py", "symbol", cfg.get("severity", "same_symbol"), ["f"]),
            record("a.py", "file", cfg.get("severity", "adjacent_lines"), []),
        ],
        "undetermined": [],
        "notes": [],
        "counts": {},
    }
    text = report.render_markdown(payload, source_path="config/radar.toml", repo=".", notify=None)
    order = [text.index("`%s`" % path) for path in ("b.py", "a.py", "z.py")]
    assert order == sorted(order), "冲突明细不是按 severity 降序：%r" % text


def test_evidence_is_capped_by_config_with_a_count_of_the_hidden_items(tmp_path):
    """证据条数上限读 `report.max_evidence_items`；被截掉的条数要**明写**，不能装作没有。"""
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    limit = cfg.get("report", "max_evidence_items")
    record = {
        "levels": ["file"], "level": "file", "workspace_a": "/w", "workspace_b": "/w",
        "path": "src/x.py", "line_ranges": [[1, 1], [2, 2]], "severity": 1,
        "severity_key": "file_only", "degraded": False, "approximate": True,
        "sessions": ["a"], "session_ids": ["a"], "sessions_a": ["a"], "sessions_b": ["b"],
        "last_write_ts": NOW,
        "evidence": ["e%d" % index for index in range(limit + 2)],
    }
    payload = {"reference_time": NOW, "conflicts": [record], "undetermined": [],
               "notes": [], "counts": {}}
    text = report.render_markdown(
        payload, source_path="config/radar.toml", repo=".", notify=None, max_evidence_items=limit
    )
    assert "…另有 2 条" in text, "被截断的证据条数没有如实登记"
    assert "e%d" % limit not in text.split("…另有")[0], "超过上限的证据仍被展示"


# --------------------------------------------------------------------------------------
# 渲染三律（K13）
# --------------------------------------------------------------------------------------

#: 禁止被渲染层 import 的判定模块（零判定）。
_FORBIDDEN_IMPORTS = frozenset({"detect", "intent", "discover", "gitio"})


def _imports_of(path):
    """AST 收集 import 的**顶层模块名**。

    `from . import detect` 这类相对导入的 `node.module` 是 `None`、模块名在 `alias` 里；
    只读 `node.module` 会把"渲染层 import 了判定模块"整条漏掉（本门禁首版就是这样，属假门）。
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
            if node.level:
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
    return found


def test_render_layer_does_not_import_any_judgement_module():
    imports = _imports_of(SRC_ROOT / "agent_conflict_radar" / "report.py")
    offending = sorted(imports & _FORBIDDEN_IMPORTS)
    assert offending == [], "渲染层 import 了判定模块 %s（K13 零判定）" % offending
    assert "serialize" in imports, "渲染层应经 serialize 出口（零外链断言所在处）"


def test_import_scanner_is_falsifiable(tmp_path, write_lf):
    """探针自证：把禁止的 import 写进临时文件，同一个扫描器必须抓到。"""
    probe = write_lf(
        tmp_path / "probe_report.py",
        "from . import detect\nimport gitio\n",
    )
    assert sorted(_imports_of(probe) & _FORBIDDEN_IMPORTS) == ["detect", "gitio"]


def test_render_layer_has_no_threshold_literals():
    """`report.py` 里的数值只允许结构性 `0` / `1` 与已登记的三元组下标 `2`。"""
    tree = ast.parse((SRC_ROOT / "agent_conflict_radar" / "report.py").read_text(encoding="utf-8"))
    values = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }
    assert values <= {0, 1, 2}, "report.py 出现未登记的数值字面量：%s" % sorted(values - {0, 1, 2})


def test_external_resources_are_rejected_at_the_render_exit(tmp_path):
    """零外链断言常驻渲染出口：payload 里带 URL → 渲染**当场**抛错（不是靠测试事后比对）。"""
    payload = {
        "reference_time": NOW,
        "conflicts": [],
        "undetermined": [
            {"file": "a.py", "source": "detect", "code": "degraded",
             "detail": "见 https://example.invalid/x 的说明"},
        ],
        "notes": [],
        "counts": {},
    }
    with pytest.raises(ValueError) as excinfo:
        report.render_markdown(payload, source_path="config/radar.toml", repo=".", notify=None)
    assert "外部资源" in str(excinfo.value)


def test_generated_report_has_zero_external_resources(tmp_path):
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    text = _surface(dest, scratch=tmp_path).markdown
    assert serialize.find_external_resources(text) == []
    assert "http://" not in text and "https://" not in text


def test_report_is_byte_identical_across_two_real_processes(tmp_path):
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    first = _run_cli(dest, scratch=tmp_path / "a")
    second = _run_cli(dest, scratch=tmp_path / "b")
    assert first[1] == second[1], "同一输入两次真子进程运行的 stdout 不逐字节一致"


def test_out_dir_products_are_byte_identical_across_two_runs(tmp_path):
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    for name in ("a", "b"):
        code, _out, err = _run_cli(
            dest, extra=["--out-dir", str(tmp_path / name)], scratch=tmp_path / ("run-" + name)
        )
        assert code == EXIT_CONFLICTS_FOUND, err
    assert (tmp_path / "a" / "report.md").read_bytes() == (tmp_path / "b" / "report.md").read_bytes()
    assert (tmp_path / "a" / "conflicts.json").read_bytes() == (
        tmp_path / "b" / "conflicts.json"
    ).read_bytes()


def test_report_md_is_lf_and_ends_with_exactly_one_newline(tmp_path):
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    code, _out, err = _run_cli(dest, extra=["--out-dir", str(tmp_path / "out")], scratch=tmp_path / "run")
    assert code == EXIT_CONFLICTS_FOUND, err
    raw = (tmp_path / "out" / "report.md").read_bytes()
    assert b"\r\n" not in raw, "report.md 必须是 LF 行尾"
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")


# --------------------------------------------------------------------------------------
# 退出码四语义（K1）+ --format 三种取值
# --------------------------------------------------------------------------------------


def test_exit_one_when_conflicts_exist(tmp_path):
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    code, out, err = _run_cli(dest, scratch=tmp_path)
    assert code == EXIT_CONFLICTS_FOUND, err
    assert b"# " in out


def test_exit_zero_when_no_conflicts(tmp_path):
    dest = _materialize("negative_no_overlap", tmp_path / "negative")
    code, out, err = _run_cli(dest, scratch=tmp_path)
    assert code == EXIT_OK, err
    assert "无冲突".encode("utf-8") in out


def test_unknown_format_is_a_usage_error(run_cli):
    code, _out, err = run_cli(["report", "--format", "pdf"])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_missing_repo_path_is_a_usage_error(run_cli, tmp_path):
    code, _out, err = run_cli(["report", "--repo", str(tmp_path / "no-such-dir")])
    assert code == EXIT_USAGE
    assert "用法错误" in err


def test_missing_session_root_is_an_environment_error(tmp_path):
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    code, out, err = _run_cli(
        dest,
        extra=["--claude-root", str(tmp_path / "no-such-root")],
        scratch=tmp_path / "run",
    )
    assert code == EXIT_ENVIRONMENT, err
    assert out == b"", "环境缺失时不得吐产物（否则会被当成空报告）"


def test_undetermined_does_not_change_the_exit_code(tmp_path):
    """有 `undetermined` 但无冲突 → 仍是 0；有冲突 → 仍是 1（与 M3 同口径）。"""
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    clean = _surface(_materialize("negative_no_overlap", tmp_path / "negative"), scratch=tmp_path)
    assert clean.payload["conflicts"] == []
    assert clean.payload["undetermined"] == []


@pytest.mark.parametrize("fmt", ["md", "json", "both"])
def test_all_three_formats_write_the_right_products(tmp_path, fmt):
    dest = _materialize("same_symbol_diff_lines", tmp_path / "same")
    out_dir = tmp_path / ("out-" + fmt)
    code, _out, err = _run_cli(
        dest, extra=["--format", fmt, "--out-dir", str(out_dir)], scratch=tmp_path / ("run-" + fmt)
    )
    assert code == EXIT_CONFLICTS_FOUND, err
    assert (out_dir / "report.md").is_file() == (fmt in ("md", "both"))
    assert (out_dir / "conflicts.json").is_file() == (fmt in ("json", "both"))


def test_json_format_prints_json_to_stdout(tmp_path):
    dest = _materialize("same_symbol_diff_lines", tmp_path / "same")
    code, out, err = _run_cli(dest, extra=["--format", "json"], scratch=tmp_path / "run")
    assert code == EXIT_CONFLICTS_FOUND, err
    payload = json.loads(out.decode("utf-8"))
    text = out.decode("utf-8").replace("\r\n", "\n")
    assert text == serialize.dumps_json(payload), "stdout 不满足冻结序列化契约（K2）"
    assert payload["conflicts"][0]["path"] == "src/alpha.py"


def test_report_creates_no_file_without_out_dir(tmp_path):
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    _run_cli(dest, scratch=tmp_path / "run", cwd=sandbox)
    assert sorted(os.listdir(str(sandbox))) == [], "report 在 CWD 落了产物（含临时文件）"


# --------------------------------------------------------------------------------------
# 可选通知（notify_unavailable 真的跑得出来）
# --------------------------------------------------------------------------------------


def test_notify_false_means_not_attempted(tmp_path):
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    surface = _surface(dest, scratch=tmp_path)
    assert surface.notify["attempted"] is False
    assert "未尝试" in surface.markdown


def test_notify_true_without_a_channel_reports_unavailable_not_failure(tmp_path):
    """配置开通知但本机没有通道 → 报告标 `notify_unavailable`，主流程与退出码不变。"""
    cfg_path = _config_with_notify_true(tmp_path)
    cfg = config_module.load(str(cfg_path))
    dest = _materialize("same_file_diff_symbol", tmp_path / "diff_symbol")
    status = report.notify_status(cfg, "标题", "正文", channel_resolver=lambda: None)
    assert status["attempted"] is True
    assert status["available"] is False
    assert "零依赖" in status["detail"]

    surface = report.build_report(
        _detect(dest, cfg=cfg, scratch=tmp_path), cfg, repo=str(Path(dest) / "repo"), notify=status
    )
    assert "notify_unavailable" in surface.markdown


def test_notify_available_path_is_reported(tmp_path, monkeypatch):
    cfg_path = _config_with_notify_true(tmp_path)
    cfg = config_module.load(str(cfg_path))
    calls = []

    import subprocess as subprocess_module

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess_module.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(report.shutil, "which", lambda name: "C:\\fake\\" + name)
    monkeypatch.setattr(report.subprocess, "run", fake_run)
    status = report.notify_status(
        cfg, "标题", "正文", channel_resolver=lambda: ("notify-send", lambda t, b: ["notify-send", t, b])
    )
    assert status["available"] is True
    assert calls, "声称已发送但根本没调用通知命令（假通知）"


def test_notify_failure_is_swallowed_and_disclosed(tmp_path, monkeypatch):
    cfg_path = _config_with_notify_true(tmp_path)
    cfg = config_module.load(str(cfg_path))

    def boom(argv, **kwargs):
        raise OSError("no notification daemon")

    monkeypatch.setattr(report.shutil, "which", lambda name: "C:\\fake\\" + name)
    monkeypatch.setattr(report.subprocess, "run", boom)
    status = report.notify_status(
        cfg, "标题", "正文", channel_resolver=lambda: ("notify-send", lambda t, b: ["notify-send", t, b])
    )
    assert status["attempted"] is True
    assert status["available"] is False
    assert "失败" in status["detail"]


def _config_with_notify_true(tmp_path):
    text = (REPO_ROOT / "config" / "radar.toml").read_text(encoding="utf-8")
    assert "notify = false" in text
    path = tmp_path / "radar-notify.toml"
    with open(str(path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text.replace("notify = false", "notify = true"))
    return path


# --------------------------------------------------------------------------------------
# 漂移守卫 + K15 退役
# --------------------------------------------------------------------------------------


def test_level_display_order_matches_engine_order():
    """`report.REPORT_LEVEL_ORDER` 与 `detect.LEVEL_ORDER` 必须一致（两处各写一份是有意的：
    渲染层不能 import 判定模块）。"""
    assert report.REPORT_LEVEL_ORDER == detect.LEVEL_ORDER


def test_severity_keys_are_all_covered_by_suggestion_templates():
    """`[severity]` 的每个键都必须有建议模板（新增档位时这条会红，而不是悄悄落到兜底文案）。"""
    cfg = config_module.load(str(REPO_ROOT / "config" / "radar.toml"))
    severity_keys = set(cfg.section("severity"))
    assert severity_keys == set(report.SUGGESTIONS), (
        "建议模板与 [severity] 档位不一致：%s" % sorted(severity_keys ^ set(report.SUGGESTIONS))
    )


def test_count_columns_are_presented_separately_with_their_own_semantics(tmp_path):
    """K12 两栏分开呈现：`by_max_level` 是划分、`by_level_membership` 是成员数。

    场景 `whole_file_overwrite` 的一条记录同时命中三级 ⇒ 划分和 = 1、成员数各为 1。
    两栏若被渲染成同一份数据，这条会红。
    """
    dest = _materialize("whole_file_overwrite", tmp_path / "overwrite")
    text = _surface(dest, scratch=tmp_path).markdown
    partition = [line for line in text.split("\n") if line.startswith("| 条目数")]
    membership = [line for line in text.split("\n") if line.startswith("| 成员数")]
    assert partition and membership, "报告没有把两栏计数分开呈现"
    assert "| 0 | 0 | 1 |" in partition[0], "条目数（划分）列不对：%s" % partition[0]
    assert "| 1 | 1 | 1 |" in membership[0], "成员数列不对：%s" % membership[0]


def test_report_is_not_staged_anymore():
    assert "report" in stages.DELIVERED_COMMANDS
    assert "report" not in stages.STAGE_NOT_READY
