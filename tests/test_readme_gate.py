"""README 指令面 / 安装面 / 测试面 对账门（K14）。

守的是那句最容易落空的话："读者照着这句话去找，能不能找到对应的文件/命令/参数？"
README 里写的命令**长期无人校验**，实测过的两类真缺陷正是这样潜伏的：
README 审计命令的路径多了一层不存在的目录；`python -m <pkg>` 缺 `__main__.py` 导致每条命令都报错。

六个面：

1. **README 命令 → CLI parser**（逐行关联旗标到子命令，防"旗标写在错的命令行上"的张冠李戴）；
2. **CLI 子命令 → README 反向覆盖**（命令总表不得漏掉已注册命令）；
3. **tests/ 与 src/ 的 import → 冻结标准库名单 / dev extra / 本包**（`sys.stdlib_module_names`
   是 3.10+ 才有的 API，底线解释器上取到空集会把每个标准库判成第三方 → 全量假红，故用冻结名单）；
4. **README 的 extras ↔ pyproject 声明双向**；
5. **包布局 ↔ 打包配置**（`package-dir` 解析结果必须真实存在；不得有"包外顶层目录"被 import）；
6. **README 登记的发布门条数 ↔ 检查表实际条数**（`release-gate-counts` 机读锚 + 编号区间）；
   解析器与发布门的 **C12** 共用一份实现——否则"文档 ↔ 测试 ↔ 门"会各说一套。
"""

import ast
import configparser
import re
from pathlib import Path

import pytest

#: 冻结标准库名单（判定词表，不是参数值）。新增标准库 import 时把它加进来是**正常维护动作**；
#: 用 `sys.stdlib_module_names` 代替会在 Python 3.8 上取到空集 → 每个标准库都判成第三方 → 全量假红。
FROZEN_STDLIB = frozenset(
    {
        "argparse",
        "ast",
        "configparser",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "getpass",
        "io",
        "itertools",
        "json",
        "os",
        "pathlib",
        "re",
        "shutil",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "types",
        "typing",
        "unicodedata",
        "collections",
        "hashlib",
        "importlib",
        "inspect",
        "shutil",
        "tempfile",
        # M6：Windows 8.3 短名的回归用例要调 `GetShortPathNameW` 造真实短名。
        # `ctypes` 是标准库（Windows 侧提供 kernel32 绑定；POSIX 上那条分支不执行）。
        "ctypes",
    }
)

#: 允许出现在 tests/ 里的第三方模块（必须同时出现在 pyproject 的 dev extra 里）。
ALLOWED_THIRD_PARTY_TESTS = frozenset({"pytest"})

_COMMAND_LINE_RE = re.compile(r"^\s*(?:\$\s+)?(?P<line>(?:radar|(?:\w[\w.\-]*\s+)?(?:-\d\.\d+|-X\s+utf8)\s+){0,4}.*)$")


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def readme_text(repo_root) -> str:
    return _read(Path(repo_root) / "README.md")


def _stdlib_and_third_party_imports(paths):
    """AST 从严收集 import（含函数体内 import），返回 [(模块名, 文件)]。"""
    found = []
    for path in paths:
        tree = ast.parse(_read(path), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # 相对导入（level>0）不算外部依赖
                if node.level:
                    continue
                names = [node.module or ""]
            for name in names:
                found.append((name.split(".")[0], path))
    return found


# --------------------------------------------------------------------------------------
# 面 1 + 面 2：README 命令 ↔ CLI parser
# --------------------------------------------------------------------------------------


def _subparsers():
    import argparse

    from agent_conflict_radar.cli import build_parser

    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return parser, action.choices
    raise AssertionError("找不到子命令注册表")


def _flags_of(subparser):
    flags = set()
    for action in subparser._actions:  # noqa: SLF001
        flags.update(action.option_strings)
    return flags


def _readme_command_lines(readme_text):
    """从 fenced code block 里抽出 `radar …` / `python -m agent_conflict_radar …` 命令。

    只取围栏代码块内的行（正文里的散文不算），跳过含占位符或明显非命令的行。
    """
    lines = []
    in_block = False
    for raw in readme_text.split("\n"):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if not in_block or not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    commands = []
    for line in lines:
        candidate = None
        if line.startswith("radar "):
            candidate = line
        elif " -m agent_conflict_radar" in line:
            candidate = line.split(" -m agent_conflict_radar", 1)[1].strip()
            if candidate.startswith("```"):
                continue
        if candidate is None:
            continue
        if "<" in candidate or ">" in candidate or candidate.endswith("..."):
            continue
        if "|" in candidate or ";" in candidate or "&&" in candidate:
            continue
        if candidate.startswith("-"):
            continue
        commands.append(candidate)
    return commands


def test_readme_commands_exist_in_cli(repo_root):
    """面 1：README 里每条命令的子命令与旗标都必须存在于 CLI，且**旗标落在正确的子命令上**。"""
    parser, subparsers = _subparsers()
    global_flags = _flags_of(parser) - {""}
    commands = _readme_command_lines(_read(repo_root / "README.md"))
    assert commands, "README 里没有抽出任何命令：抽取逻辑或 README 结构变了"

    problems = []
    for command in commands:
        tokens = command.split()
        tokens = [token for token in tokens if token not in ("--",)]
        subcommand = None
        for token in tokens:
            if token in subparsers:
                subcommand = token
                break
        if subcommand is None:
            problems.append("README 命令没有可识别的子命令：%r" % command)
            continue
        index = tokens.index(subcommand)
        before, after = tokens[:index], tokens[index + 1 :]
        for token in before:
            if token.startswith("-") and token not in global_flags:
                problems.append("%r 里旗标 %r 不在全局选项里（可能写错了位置）" % (command, token))
        allowed = _flags_of(subparsers[subcommand])
        for token in after:
            if not token.startswith("-"):
                continue
            flag = token.split("=", 1)[0]
            if flag not in allowed:
                problems.append("%r 里旗标 %r 不属于子命令 %r" % (command, flag, subcommand))
    assert problems == [], "\n  ".join(["README 指令面与 CLI 不一致（K14 面 1）:"] + problems)


def _readme_section(readme_text, heading):
    """取出 `## <heading>` 到下一个 `## ` 之间的正文。

    为什么必须按**章节**取：同一个命令名会在多处出现（顶部状态表、示例、正文），
    只在全文里找"这串字出现过"的话，命令总表漏记一条也**永远不会红**
    （实测形态：变异改了命令总表的行，但顶部状态表仍露出同名行 → 门禁照常绿）。
    """
    lines = readme_text.split("\n")
    collected = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == "## %s" % heading
            continue
        if inside:
            collected.append(line)
    return "\n".join(collected)


def _readme_command_table_entries(readme_text):
    """抽出**命令总表章节**里以 `` `radar <cmd>` `` 作为**首个单元格**的行。

    判据落在结构位置（章节 + 表格行首格），而不是"文件里出现过这串字"：
    子串判据会被示例命令满足，于是"命令总表漏记一条"永远不会红
    （SKILL 明确记过"README 命令要验路径存在 + 模块可执行，而非子串"）。
    """
    section = _readme_section(readme_text, "命令总表")
    entries = set()
    for line in section.split("\n"):
        match = re.match(r"^\|\s*`(?P<cell>[^`]+)`\s*\|", line.strip())
        if match:
            entries.add(match.group("cell").strip())
    return entries


def _runnable_subcommands(readme_text):
    """code block 里真正被调用到的子命令集合。"""
    _parser, subparsers = _subparsers()
    covered = set()
    for command in _readme_command_lines(readme_text):
        for token in command.split():
            if token in subparsers:
                covered.add(token)
    return covered


def test_command_table_has_entries(readme_text):
    entries = _readme_command_table_entries(readme_text)
    radar_rows = {entry for entry in entries if entry.startswith("radar ")}
    assert len(radar_rows) >= 5, "命令总表抽取面过小（%d 行）：抽取器或 README 结构变了" % len(radar_rows)
    assert "## 命令总表" in readme_text, "README 缺少「命令总表」章节：本门禁按章节取正文"


def test_every_cli_subcommand_is_documented(repo_root, readme_text):
    """面 2：反向覆盖，且**分两条判据**——"写进命令总表"与"有可照抄的运行示例"。"""
    _parser, subparsers = _subparsers()
    table_entries = _readme_command_table_entries(readme_text)
    runnable = _runnable_subcommands(readme_text)

    missing_table = [name for name in subparsers if ("radar %s" % name) not in table_entries]
    missing_runnable = [name for name in subparsers if name not in runnable]
    assert missing_table == [], "README 命令总表未记录：%s" % sorted(missing_table)
    assert missing_runnable == [], "README 未给出可照抄的运行示例：%s" % sorted(missing_runnable)


# --------------------------------------------------------------------------------------
# 面 3：import 落点（冻结名单 / dev extra / 本包）
# --------------------------------------------------------------------------------------


def test_src_imports_are_stdlib_or_own_package(repo_root):
    paths = sorted((Path(repo_root) / "src" / "agent_conflict_radar").rglob("*.py"))
    assert paths, "扫描面为空"
    offenders = []
    for module, path in _stdlib_and_third_party_imports(paths):
        if module in FROZEN_STDLIB or module == "agent_conflict_radar":
            continue
        offenders.append("%s 导入了非标准库模块 %r（本项目零第三方运行时依赖）" % (path.name, module))
    assert offenders == [], "\n  ".join(offenders)


def test_tests_imports_are_stdlib_dev_extra_or_own_package(repo_root, pyproject_extras):
    paths = sorted((Path(repo_root) / "tests").rglob("*.py"))
    assert paths, "扫描面为空"
    dev_extras = pyproject_extras.get("dev", set())
    offenders = []
    for module, path in _stdlib_and_third_party_imports(paths):
        if module in FROZEN_STDLIB or module == "agent_conflict_radar":
            continue
        if module in ALLOWED_THIRD_PARTY_TESTS:
            if module not in dev_extras:
                offenders.append("%s 依赖 %r，但 pyproject 的 dev extra 未声明" % (path.name, module))
            continue
        offenders.append(
            "%s 导入了 %r：若属标准库请加入 FROZEN_STDLIB（判定词表，扩词表是正常维护），"
            "否则必须声明进 dev extra" % (path.name, module)
        )
    assert offenders == [], "\n  ".join(offenders)


# --------------------------------------------------------------------------------------
# 面 4：README extras ↔ pyproject 双向
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pyproject_extras(repo_root) -> dict:
    """解析 pyproject 的 optional-dependencies（不依赖 tomllib：底线解释器没有它）。

    用 `configparser` 读 TOML 是不可靠的，故这里用受限正则抽取 `[project.optional-dependencies]`
    段——`test_extras_parsing_is_not_vacuous` 会验证抽取器真的抓到了东西。
    """
    text = _read(Path(repo_root) / "pyproject.toml")
    extras = {}
    in_block = False
    current = None
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_block = stripped == "[project.optional-dependencies]"
            current = None
            continue
        if not in_block or not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^(?P<name>[\w.\-]+)\s*=\s*\[(?P<items>.*)\]\s*$", stripped)
        if match:
            current = match.group("name")
            extras[current] = set()
            items = match.group("items")
            for item in items.split(","):
                item = item.strip().strip('"').strip("'")
                if item:
                    extras[current].add(re.split(r"[<>=!\[]", item)[0].strip())
    return extras


def test_extras_parsing_is_not_vacuous(pyproject_extras):
    """抽取器自证：抓不到东西的门禁等于没有门禁。"""
    assert "dev" in pyproject_extras, "未解析出 dev extra：抽取器或 pyproject 结构变了"
    assert "pytest" in pyproject_extras["dev"]


def test_readme_extras_are_declared(repo_root, pyproject_extras):
    """面 4：README 里 `pip install -e ".[...]"` 用到的每个 extra 都必须在 pyproject 声明。"""
    readme = _read(repo_root / "README.md")
    used = set()
    for match in re.finditer(r'pip install[^\n]*?"\.\[([^\]]+)\]"', readme):
        for name in match.group(1).split(","):
            name = name.strip()
            if name:
                used.add(name)
    assert used, "README 未出现 `pip install -e \".[...]\"` 形态：抽取器或 README 变了"
    undeclared = sorted(used - set(pyproject_extras))
    assert undeclared == [], "README 用到但 pyproject 未声明的 extra：%s" % undeclared


def test_pyproject_declares_no_runtime_dependencies(repo_root):
    """零第三方运行时依赖是"断网可跑/纯本地"的结构性前提，必须被断言。"""
    text = _read(Path(repo_root) / "pyproject.toml")
    match = re.search(r"^dependencies\s*=\s*\[(?P<items>[^\]]*)\]", text, re.MULTILINE)
    assert match is not None, "pyproject 未声明 dependencies（应显式声明为空）"
    assert match.group("items").strip() == "", "运行时依赖必须为空，实为 %r" % match.group("items")


# --------------------------------------------------------------------------------------
# 面 5：包布局 ↔ 打包配置；README 声明的许可 ↔ 实物
# --------------------------------------------------------------------------------------


def test_packaging_maps_src_layout_and_resolves(repo_root):
    """面 5：`package-dir` 的**解析结果**必须真实存在。

    判据落在解析结果上，而不是"pyproject 里出现过 src 这个词"——
    坏配置也可能含那个词（SKILL 明确记过这一坑）。
    """
    pyproject = _read(Path(repo_root) / "pyproject.toml")
    assert re.search(r'package-dir\s*=\s*\{\s*""\s*=\s*"src"\s*\}', pyproject), "package-dir 未声明 src 布局"
    assert re.search(r"where\s*=\s*\[\s*\"src\"\s*\]", pyproject), "packages.find 的 where 未包含 src"
    package_dir = Path(repo_root) / "src" / "agent_conflict_radar"
    assert (package_dir / "__init__.py").is_file(), "解析到的包目录不存在：%s" % package_dir


def test_no_top_level_package_outside_src(repo_root):
    """禁止"包外顶层目录"：它不进安装面，而源码态 `python -m` 却能跑通（潜伏多个里程碑）。

    判别 = "这个包能被 import，是被谁放到 sys.path 上的？"
    """
    offenders = [path.name for path in Path(repo_root).iterdir() if (path / "__init__.py").is_file()]
    assert offenders == [], "仓库根出现可导入包（不会进安装面）：%s" % offenders


def test_readme_declared_license_has_a_file(repo_root):
    """README 声明 MIT → 仓库必须有 LICENSE 文件（pyproject 的 license 只是元数据）。

    同类缺口：README 写的命令/参数/附件名与实物不符。这条只看许可，命令面由面 1/2 覆盖。
    """
    readme = _read(repo_root / "README.md")
    assert "MIT" in readme
    assert "LICENSE" in readme
    license_path = Path(repo_root) / "LICENSE"
    assert license_path.is_file(), "README 声明了许可但仓库没有 LICENSE 文件"
    assert "MIT License" in _read(license_path)


def test_readme_states_all_exit_codes_and_config_location(repo_root):
    """README 必须写出退出码语义与"数值唯一位置"——它们是用户最需要照着找的两样东西。

    M5 起只有四语义：`4 = 阶段未就绪` 已随命令面 7/7 交付整条退役（K1 四步），
    因此这里断言的是 **0–3 全在、4 不在**。判据不能再写"4 也在"——那会把退役
    又变回"README 与代码各说一套"。
    """
    readme = _read(repo_root / "README.md")
    for code in ("`0`", "`1`", "`2`", "`3`"):
        assert code in readme, "README 未写退出码 %s 的语义" % code
    assert "| `4` |" not in readme, "退出码 4 已退役：README 不得再把它列成一种语义"
    assert "config/radar.toml" in readme
    assert "plan/06-里程碑.md" in readme


def test_product_name_is_consistent_four_ways(repo_root, installed_version, src_fallback):
    """名字四向一致：README H1 / pyproject.name / 导入包名 / 安装元数据版本号。

    SKILL 实录过"README 标题把产品名拼错一个字母、五个里程碑无人发现"的形态。
    """
    readme = _read(Path(repo_root) / "README.md")
    first_line = readme.split("\n", 1)[0]
    assert "agent-conflict-radar" in first_line, "README H1 必须含规范产品名"
    pyproject = _read(Path(repo_root) / "pyproject.toml")
    assert re.search(r'^name\s*=\s*"agent-conflict-radar"', pyproject, re.MULTILINE)
    import agent_conflict_radar

    assert agent_conflict_radar.__version__
    if src_fallback:
        pytest.skip("未安装（走源码树兜底）：安装面版本号一致性留给 CI/干净环境断言")
    from agent_conflict_radar import __version__

    assert installed_version == __version__, (
        "安装元数据版本 %r 与包内 __version__ %r 不一致" % (installed_version, __version__)
    )


def test_readme_command_lines_extractor_is_not_vacuous(repo_root):
    """抽取器自证：文本抽取类门禁第一轮变异验证要专门看"探针有没有把目标文本切坏"。"""
    commands = _readme_command_lines(_read(repo_root / "README.md"))
    assert len(commands) >= 5, "只抽出 %d 条命令：抽取器可能把文本切坏了" % len(commands)
    staged = [command for command in commands if command.startswith("radar bench")]
    assert staged, "README 应给出 `radar bench` 的用法示例（M5 招牌命令）"


# --------------------------------------------------------------------------------------
# 面 6：README 登记的发布门条数 ↔ 检查表实际条数
# --------------------------------------------------------------------------------------


def _load_release_gate():
    """按路径加载 `scripts/check_release.py`（它不是包的一部分，不能按名字 import）。

    这里**不复制解析器**：条数对账用的就是发布门 C12 的同一个函数——否则"文档 ↔ 测试 ↔ 门"
    会各说一套，而这条判据存在的理由正是"数字只有一个来源"。
    """
    import importlib.util
    import sys

    path = Path(__file__).resolve().parent.parent / "scripts" / "check_release.py"
    assert path.is_file(), "缺少发布门 scripts/check_release.py（M6 交付物）"
    name = "radar_check_release_readme_face"
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_release_gate_counts_are_reconciled(repo_root, readme_text):
    """面 6：README 的机读锚与编号区间 == 检查表实际条数（离线 / 在线 / 变异三向）。

    为什么要有这一面：M6 发布物的 README 曾同时写"离线 10 条 + 在线 6 条"（=16）与"18 组变异"
    ——自相矛盾，而且没有任何判据把数字钉住。这里钉住它：改检查表而不同步 README → 红。
    """
    gate = _load_release_gate()
    declared = gate.documented_gate_counts(readme_text)
    assert declared is not None, (
        "README 缺少机读条数锚 `release-gate-counts offline=… online=… mutations=…`"
    )
    assert declared["offline"] == len(gate.OFFLINE_CHECKS), (
        "README 登记离线 %d 条 ≠ 检查表实际 %d 条" % (declared["offline"], len(gate.OFFLINE_CHECKS))
    )
    assert declared["online"] == len(gate.ONLINE_CHECKS), (
        "README 登记在线 %d 条 ≠ 检查表实际 %d 条" % (declared["online"], len(gate.ONLINE_CHECKS))
    )
    assert declared["mutations"] == len(gate._mutation_worlds()), (  # noqa: SLF001
        "README 登记变异 %d 组 ≠ 实际 %d 组"
        % (declared["mutations"], len(gate._mutation_worlds()))  # noqa: SLF001
    )
    ranges = gate._GATE_RANGE_RE.search(readme_text)  # noqa: SLF001
    assert ranges is not None, "README 缺少检查编号区间 `离线 C01–C… / 在线 O01–O…`"
    assert int(ranges.group(1)) == len(gate.OFFLINE_CHECKS), "README 的离线区间与实际条数不符"
    assert int(ranges.group(2)) == len(gate.ONLINE_CHECKS), "README 的在线区间与实际条数不符"


def test_release_gate_counts_extractor_is_not_vacuous(repo_root, readme_text):
    """抽取器自证 + **可证伪**：锚缺席必须返回 None；数字改掉必须读到改后的值。"""
    gate = _load_release_gate()
    assert gate.documented_gate_counts(readme_text) is not None, "真实 README 上抽不到锚"
    assert gate.documented_gate_counts("这一行没有锚") is None, "锚缺席被当成了「抽到零条」"
    probe = gate.documented_gate_counts("release-gate-counts offline=1 online=2 mutations=3")
    assert probe == {"offline": 1, "online": 2, "mutations": 3}, (
        "抽取器没有读到改后的值（可能把数字写死成了默认值）：%r" % (probe,)
    )
