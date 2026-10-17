"""零内联阈值字面量门禁（K5）——"数值口径一处定义"的可证伪落法。

判据：**策略数值只能来自 `config/radar.toml`，不能作为字面量藏在代码里**。
本文件按模块扫描 `ast.Constant` 数值字面量：除 `0` / `1`（结构性常量：索引、1-based 起点、
真假分支）外，任何数值都必须显式登记在 `ALLOWED_LITERALS` 或落在 `EXEMPT_FILES` 里。

两条防空转纪律（SKILL「假门」家族）：

* **扫描面必须非空**：断言扫到了预期数量的模块，且包内每个 `.py` 要么在扫描面、要么在豁免名单——
  否则"新增一个模块"就会**默认逃出**门禁，而门禁仍然全绿。
* **探针自证**：把一段含 `42` 的代码写成临时文件，用**同一个扫描函数**跑一遍，必须能抓到。
  "探针通过"证明的是"扫描器真的在工作"，不是"我这次恰好没写错"。

扩名单是**正常维护动作**（阈值是词表不是参数值）；绕过词表（把数值抄进代码再声称"这是常量"）
是造假。每个新条目都必须带理由。
"""

import ast
from pathlib import Path

#: 允许的结构性数值。
STRUCTURAL_NUMBERS = (0, 1)

#: 整文件豁免（附理由）。豁免要少而可解释——每多一个，门禁的覆盖就少一块。
EXEMPT_FILES = {
    "config.py": "配置解析器实现：其中的数字是语法/实现常量（如偏移量），不是策略阈值；策略值一律来自被解析的文件",
    "exit_codes.py": "退出码定义位：0–4 是契约本体，定义就在这里（K1）",
    "bench/rng.py": "确定性 RNG 的算法常量（splitmix64 的黄金比例增量、两个混淆乘子、位移量、64 位掩码）：是算法本体，不是策略阈值",
    "bench/gen.py": (
        "合成场景生成器：其中的数字是**构造几何**（改动行号 2/9/10/14/15/19、符号区间、会话偏移分钟、"
        "覆盖度最低条数、sha 位数）——是「输入数据」本身，不是判定阈值。判定阈值一律经 "
        "`thresholds_ref` / `gap_rule` 引用 config，且 `--check` 会读 config 现场求值"
        "（改阈值而真值不动 → 变红）。豁免理由与兜底守门一并写在这里，供复核"
    ),
}

#: 逐值豁免：(相对包根的 posix 路径, 数值) -> 理由
ALLOWED_LITERALS = {
    ("serialize.py", 2): "json indent=2，是冻结序列化契约的一部分（K2）",
    ("gitio.py", 2): "`worktree` 形态判定里的参数位置常量（是否需要第二个参数），非策略阈值",
    ("discover.py", 400): "错误详情文本的截断长度：诊断展示用常量，不是判定阈值（阈值一律读 config）",
    ("intent.py", 400): "同 discover.py：错误详情文本的截断长度，只影响报错信息长度，不参与任何判定",
}

#: 包内**必须存在**的模块（防止"扫描面为空 → 门禁空转"）。
REQUIRED_MODULES = (
    "__init__.py",
    "__main__.py",
    "cli.py",
    "config.py",
    "discover.py",
    "errors.py",
    "exit_codes.py",
    "gitio.py",
    "intent.py",
    "paths.py",
    "serialize.py",
    "stages.py",
    "versions.py",
    "bench/__init__.py",
    "bench/gen.py",
    "bench/rng.py",
)


def _package_root(src_root: Path) -> Path:
    return Path(src_root) / "agent_conflict_radar"


def iter_scoped_files(src_root: Path):
    """返回 (相对路径, 绝对路径) 列表；豁免文件已剔除，但**豁免文件本身也必须存在**。"""
    root = _package_root(src_root)
    scoped = []
    seen_exempt = set()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXEMPT_FILES:
            seen_exempt.add(rel)
            continue
        scoped.append((rel, path))
    return scoped, seen_exempt


def scan_numeric_literals(path: Path, rel: str):
    """扫描单个文件的数值字面量，返回违规列表 [(行号, 数值)]。"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if node.value in STRUCTURAL_NUMBERS:
                continue
            if (rel, node.value) in ALLOWED_LITERALS:
                continue
            violations.append((node.lineno, node.value))
    return violations


def test_scan_face_is_not_empty(src_root):
    scoped, seen_exempt = iter_scoped_files(src_root)
    assert len(scoped) + len(seen_exempt) >= len(REQUIRED_MODULES), (
        "扫描面过小（%d 个文件）：门禁可能在空转" % (len(scoped) + len(seen_exempt))
    )
    for name in REQUIRED_MODULES:
        assert name in dict((rel, None) for rel, _p in scoped) or name in seen_exempt, (
            "包内缺少预期模块 %r：既不在扫描面也不在豁免名单" % name
        )
    for name in EXEMPT_FILES:
        assert name in seen_exempt, "豁免名单里的 %r 在包内不存在（名单已过期）" % name


def test_every_package_module_is_classified(src_root):
    """包内每个模块要么被扫描、要么被显式豁免——**没有第三种默认逃逸**。"""
    scoped, seen_exempt = iter_scoped_files(src_root)
    classified = {rel for rel, _p in scoped} | seen_exempt
    root = _package_root(src_root)
    on_disk = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert on_disk == classified, "未分类模块：%s" % sorted(on_disk - classified)


def test_no_policy_numeric_literals_in_source(src_root):
    scoped, _seen = iter_scoped_files(src_root)
    problems = []
    for rel, path in scoped:
        for lineno, value in scan_numeric_literals(path, rel):
            problems.append("%s:%d 出现数值字面量 %r" % (rel, lineno, value))
    assert problems == [], (
        "策略数值必须来自 config/radar.toml（K3/K5）。若确属实现常量，请在 ALLOWED_LITERALS 登记并写明理由：\n  "
        + "\n  ".join(problems)
    )


def test_scanner_actually_detects_injected_literal(tmp_path, write_lf):
    """探针自证：注入 `42` 后同一扫描函数必须抓到（否则门禁是假门）。"""
    probe = write_lf(tmp_path / "probe_module.py", "def f():\n    return 42\n")
    violations = scan_numeric_literals(probe, "probe_module.py")
    assert violations == [(2, 42)], "扫描器未能检出注入的字面量：%r" % (violations,)


def test_scanner_ignores_structural_numbers_and_allowlist(tmp_path, write_lf):
    """阴性对照：结构性数值与已登记豁免值**不得**被误报（否则门禁会被"随手放宽"掉）。"""
    probe = write_lf(tmp_path / "probe_ok.py", "def f(items):\n    return items[0], items[1], 1.0, 0, True\n")
    assert scan_numeric_literals(probe, "probe_ok.py") == []

    probe2 = write_lf(tmp_path / "serialize.py", "X = 2\n")
    assert scan_numeric_literals(probe2, "serialize.py") == []
