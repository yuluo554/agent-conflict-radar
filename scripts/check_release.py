"""发布终态自检门（M6）——**刻意不进 CI**。

为什么不在 CI 里：它检查的是"发布这件事做完了没有"——仓库公开、tag 指向、CI 已绿、附件已传且
sha256 可复算。这些状态在**发布时才存在**；放进 CI 会让每次提交都跑一个"还没有 tag、还没有
Release"的注定失败的门，于是只能被跳过或被放宽——那是假门。

两种模式
--------

    python scripts/check_release.py                 # 离线：仓库自身可发布吗（工作树/脱敏/源码包）
    python scripts/check_release.py --online        # 在线：发布已达成吗（含逐个附件下载复算 sha256）
    python scripts/check_release.py --mutation      # 门自身变异验证（检查项数 == 变异组数）
    python scripts/check_release.py --record-assets dist/release --tag v0.0.1
                                                     # 把本地附件副本的 sha256 记进 plan/release-assets.json

判据纪律
--------

* **每条检查都必须可被一条变异打红**（`--mutation`）。检查项数与被抓到的变异组数不相等 =
  有检查项其实没在查东西（"门看起来很多项，其实没在查"）。这条断言写在 ``run_mutation`` 里，
  不是靠人自觉。
* **检查项不做"看起来像"的判断**：至少一条判据落在**产物实测**上（真建 sdist、真解包、真跑
  CLI、真下载算 sha256），而不是只读文本里出现过某个词。
* **K2**：本脚本唯一的写盘点（`--record-assets`）走 `serialize.write_atomic`，不另写一份
  `open()+json.dump`。
* **K3**：脚本自身**零策略数值**——阈值/超时一律不在这里定义；能用结构常量（0/1/下标）表达的
  就不引入数值。
* **K7**：留档里的时间是**真实 UTC 时刻**（事件记录，不是产物判定）；这是本脚本唯一读系统时钟
  的地方。
* **K17**：发布附件与 tag 树逐字节同源；zip/tar 内**不写自身 sha256**（自指必过期）——sha256
  只写进 `plan/release-assets.json`。该文件**不在 sdist 内**（`MANIFEST.in` 只收 `plan *.md`），
  所以它可以在 **tag 之前**入库：加了它不会改变包的字节（`--build-asset` 前后各建一次可当场核对），
  于是"发布物自证"不需要放宽任何判据。
"""

import argparse
import fnmatch
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_conflict_radar import serialize  # noqa: E402
from agent_conflict_radar import bench as bench_package  # noqa: E402
from agent_conflict_radar.bench import gen  # noqa: E402
from agent_conflict_radar.exit_codes import (  # noqa: E402
    EXIT_CONFLICTS_FOUND,
    EXIT_ENVIRONMENT,
    EXIT_OK,
    EXIT_USAGE,
)

#: 发布门的退出码（与 `radar` 的四语义同构，避免出现第二套编码）：
#: 0 = 全部通过；1 = 有 FAIL；2 = 用法错误；3 = 依赖/环境缺失（gh / build / git 不可用）。
EXIT_PASS = EXIT_OK
EXIT_FAIL = EXIT_CONFLICTS_FOUND
EXIT_USAGE_ERROR = EXIT_USAGE
EXIT_MISSING_ENV = EXIT_ENVIRONMENT

#: 规范仓库坐标（K14 四向一致的第四面；与 pyproject 的 Homepage、README H1 并排读）。
CANONICAL_SLUG = "yuluo554/agent-conflict-radar"
CANONICAL_NAME = "agent-conflict-radar"

#: 附件登记文件。**不在 sdist 内**（MANIFEST 只收 `plan *.md`），因此可以在 **tag 之前**入库：
#: 这样 tag 树自带登记，O05/O06/O07 在发布物自身里才成立；而包字节不受影响（不含本文件）。
ASSET_LEDGER_RELPATH = "plan/release-assets.json"

#: 运行产物：不入源码包（与 `bench.gen.RUNTIME_PRODUCTS` 同源）。
RUNTIME_PRODUCTS = gen.RUNTIME_PRODUCTS

#: 源码包里**必须**存在的非 bench 文件（发布留档与数值口径是其中两项的判据来源）。
REQUIRED_PACKAGE_FILES = (
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "MANIFEST.in",
    "config/radar.toml",
    "docs/技术报告.md",
    "plan/RELEASE-M6.md",
    "scripts/check_release.py",
)

#: 签名形状：真实用户名/真实主目录。判据是**值**（真实用户名、真实仓库路径），不是"出现过路径形状"
#: ——后者会把策略说明与测试里的假值一并判违规，门禁就会因误报被随手放宽（M2–M5 三次实测）。
_DRIVE_USER_RE = re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]([^\\/\"'\s]+)")
_BASH_HOME_RE = re.compile(r"/(?:c|mnt/[a-z])/[Uu]sers/([^/\"'\s]+)")
_POSIX_HOME_RE = re.compile(r"/(?:Users|home)/([^/\"'\s]+)")
_REAL_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.IGNORECASE
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

#: 合成数据白名单值（K11）：这些"用户段"是生成器的假值，出现即说明用了白名单，不算泄露。
WHITELISTED_HOME_SEGMENTS = frozenset(
    {
        "radar-user",
        "radar-probe",
        "user",
        "username",
        "example",
        "你的",
        "<你的 claude 会话根>",
        "<你的 codex 会话根>",
    }
)

#: 允许出现在提交身份里的邮箱形态（GitHub noreply）。
_ALLOWED_COMMIT_EMAIL_RE = re.compile(r"^(?:\d+\+)?[\w.-]+@users\.noreply\.github\.com$")


# --------------------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------------------


class EnvironmentMissing(Exception):
    """依赖/环境缺失（gh / build / git 不可用）→ 退出码 3，**不算 FAIL**。"""


class ReleaseNotAchieved(Exception):
    """发布未达成（本地没有 tag / 远端对象 404）→ 计 **FAIL**（exit 1）。

    与 `EnvironmentMissing` 的区别是发布门最该守住的一条：**"还没发布"不是"工具没装"**。
    混成一类会让"仓库根本没建"看起来像"这台机器没登录 gh"。
    """


class GhNotFound(ReleaseNotAchieved):
    """远端对象不存在（仓库 / tag / Release 404）。"""


def _run(argv: Sequence[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """跑子进程，显式 utf-8 解码（K8：不依赖控制台码页）。"""
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return (
        completed.returncode,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --------------------------------------------------------------------------------------
# 检查上下文（所有外部状态都从这里取——变异验证靠替换这些钩子，而不是改真仓库）
# --------------------------------------------------------------------------------------


class Context(object):
    """一次发布门运行所看到的世界。钩子全部可替换，供 `--mutation` 注入坏世界。"""

    def __init__(self, root: Path = REPO_ROOT, tag: str = "", slug: str = CANONICAL_SLUG, **hooks: Callable):
        self.root = Path(root)
        self.tag = tag
        self.slug = slug
        self._hooks = hooks
        self._sdist_cache: Optional[Dict[str, bytes]] = None
        self._tree_cache: Optional[Dict[str, bytes]] = None

    # ---- 文件与 git ----
    def tree_ref(self) -> str:
        """发布树的 ref：**给了 tag 且本地能解析就用 tag，否则用 HEAD**。

        为什么必须这样：tag 之后还会追加"附件登记"提交，`HEAD` 就前进了；若仍从 `HEAD` 建包，
        得到的就不是 tag 树的内容——"附件与 tag 树逐字节同源"当场失效（本机实测推演过）。
        """
        if "tree_ref" in self._hooks:
            return self._hooks["tree_ref"]()
        if self.tag:
            code, out, _err = _run(["git", "rev-parse", "--verify", "%s^{commit}" % self.tag], cwd=self.root)
            if code == EXIT_PASS:
                return "%s^{commit}" % self.tag
        return "HEAD"

    def tree_files(self) -> Dict[str, bytes]:
        """受控树（`git archive <ref>`）的 `{路径: 字节}`——发布包的内容基准。"""
        if "tree_files" in self._hooks:
            return dict(self._hooks["tree_files"]())
        if self._tree_cache is None:
            self._tree_cache = _archive_files(self.root, self.tree_ref())
        return dict(self._tree_cache)

    def tracked(self) -> List[str]:
        """受控树的路径列表（= `tree_files()` 的键，按名字排序）。

        用树而不是 `git ls-files`：tag 之后的追加提交会让索引比 tag 树多出文件，届时
        "发布包里该有什么"必须以 **tag 树** 为准。
        """
        if "tracked" in self._hooks:
            return list(self._hooks["tracked"]())
        return sorted(self.tree_files())

    def git(self, *args: str) -> str:
        if "git" in self._hooks:
            return self._hooks["git"](*args)
        code, out, err = _run(["git"] + list(args), cwd=self.root)
        if code != EXIT_PASS:
            raise EnvironmentMissing("git %s 失败：%s" % (" ".join(args), err.strip() or code))
        return out

    def read(self, rel: str) -> str:
        """读文本。**给了 tag 且能解析时读 tag 树的内容**（不是工作区）。

        理由与 `tree_ref()` 相同：tag 之后工作区/`HEAD` 会多出追加提交的文件，
        而"发布留档 / MANIFEST / pyproject 是不是 tag 里那份"必须以 tag 树为准。
        """
        if "read" in self._hooks:
            return self._hooks["read"](rel)
        files = self.tree_files()
        if rel in files:
            return files[rel].decode("utf-8")
        return _read(self.root / rel)

    def exists(self, rel: str) -> bool:
        if "exists" in self._hooks:
            return self._hooks["exists"](rel)
        if rel in self.tree_files():
            return True
        return (self.root / rel).exists()

    def bench_dir(self) -> Path:
        if "bench_dir" in self._hooks:
            hook = self._hooks["bench_dir"]
            # 允许传路径本身或返回路径的函数：变异世界写 `bench_dir=<path>` 是最自然的形态。
            return Path(hook() if callable(hook) else hook)
        return self.root / "bench"

    # ---- sdist ----
    def sdist_members(self) -> Dict[str, bytes]:
        if "sdist_members" in self._hooks:
            return dict(self._hooks["sdist_members"]())
        # 一次运行只建一次：C09 与 C10 看的是**同一份**源码包（否则两条结论可能对应两个包）。
        if self._sdist_cache is None:
            self._sdist_cache = _build_sdist_members(self.root, self.tree_ref())
        return dict(self._sdist_cache)

    def normalize_archive(self) -> Callable[[Path, Path], None]:
        """归档归一函数（C11 的探针点：变异世界可以把它换成"原样拷贝"）。"""
        if "normalize_archive" in self._hooks:
            return self._hooks["normalize_archive"]
        return _normalize_sdist_archive

    # ---- gh（仅 --online 用） ----
    def gh_json(self, api_path: str) -> Any:
        if "gh_json" in self._hooks:
            return self._hooks["gh_json"](api_path)
        if shutil.which("gh") is None:
            raise EnvironmentMissing("找不到 gh CLI：--online 需要 GitHub CLI 且已登录")
        code, out, err = _run(["gh", "api", api_path], cwd=self.root)
        if code != EXIT_PASS:
            blob = (err or out).strip()
            if "HTTP 404" in blob or "Not Found" in blob:
                # 远端对象不存在 = 发布未达成（FAIL），不是环境缺失。
                raise GhNotFound("远端对象不存在：%s（%s）" % (api_path, blob))
            raise EnvironmentMissing("gh api %s 失败（未登录或无权限）：%s" % (api_path, blob))
        return json.loads(out)

    def download_asset(self, name: str, dest: Path) -> Path:
        if "download_asset" in self._hooks:
            return Path(self._hooks["download_asset"](name, dest))
        if shutil.which("gh") is None:
            raise EnvironmentMissing("找不到 gh CLI：附件复算需要 gh release download")
        target = Path(dest) / name
        code, _out, err = _run(
            ["gh", "release", "download", self.tag, "--pattern", name, "--dir", str(dest)],
            cwd=self.root,
        )
        if code != EXIT_PASS or not target.is_file():
            raise EnvironmentMissing("下载附件 %r 失败：%s" % (name, err.strip() or code))
        return target

    # ---- 时钟（K7：真实 UTC，用于**事件记录**） ----
    def now_utc(self) -> str:
        if "now_utc" in self._hooks:
            return self._hooks["now_utc"]()
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _archive_files(root: Path, ref: str) -> Dict[str, bytes]:
    """`git archive <ref>` → `{路径: 字节}`（受控树的内容基准）。"""
    completed = subprocess.run(
        ["git", "archive", "--format=tar", ref], cwd=str(root), stdout=subprocess.PIPE
    )
    if completed.returncode != EXIT_PASS:
        raise EnvironmentMissing("git archive %s 失败（无法导出受控树）" % ref)
    blob = tempfile.mkdtemp(prefix="radar-rel-archive-")
    try:
        archive_path = Path(blob) / "_tree.tar"
        with open(str(archive_path), "wb") as handle:
            handle.write(completed.stdout)
        files: Dict[str, bytes] = {}
        with tarfile.open(str(archive_path), "r:") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is not None:
                    files[member.name] = extracted.read()
        return files
    finally:
        shutil.rmtree(blob, ignore_errors=True)


def _build_sdist_members(root: Path, ref: str = "HEAD") -> Dict[str, bytes]:
    """真建一份 sdist，返回 `{包内相对路径: 字节}`。

    为什么必须真建：只读 MANIFEST.in 的规则文本无法证明 setuptools 真的照做了——规则写错一个
    空格、`exclude` 顺序反了，文本看都看不出来（这是 M6 检查项 C09 存在的理由）。

    为什么先 `git archive` 导出再建：工作树里可能有 `*.egg-info`、缓存等未跟踪产物，直接建会把
    它们带进包里（本机实测：`src/agent_conflict_radar.egg-info/*` 曾混入 sdist）。发布包必须由
    **受版本控制的内容**构成，所以先在临时目录里还原一份纯 tracked 树，再在那里构建。
    """
    try:
        import build  # noqa: F401
    except ImportError:
        raise EnvironmentMissing("缺少 `build` 包：pip install build（发布门需要真建 sdist）")
    export_dir = tempfile.mkdtemp(prefix="radar-rel-sdist-src-")
    outdir = tempfile.mkdtemp(prefix="radar-rel-sdist-out-")
    try:
        # git archive 走 stdout；tar 是二进制，必须走字节通道（`_run` 是 utf-8 文本通道）。
        completed = subprocess.run(
            ["git", "archive", "--format=tar", ref], cwd=str(root), stdout=subprocess.PIPE
        )
        if completed.returncode != EXIT_PASS:
            raise EnvironmentMissing("git archive %s 失败（无法导出受控树）" % ref)
        archive_path = Path(export_dir) / "_tree.tar"
        with open(str(archive_path), "wb") as handle:
            handle.write(completed.stdout)
        tree_dir = Path(export_dir) / "tree"
        tree_dir.mkdir()
        with tarfile.open(str(archive_path), "r:") as archive:
            _extract_tar(archive, tree_dir)
        code, out, err = _run(_build_sdist_argv(outdir, tree_dir), cwd=outdir)
        if code != EXIT_PASS:
            raise EnvironmentMissing("构建 sdist 失败：%s" % ((err or out).strip().splitlines()[-1:]))
        del out, err
        archives = sorted(Path(outdir).glob("*.tar.gz"))
        if not archives:
            raise EnvironmentMissing("构建声称成功但没有产出 .tar.gz")
        members: Dict[str, bytes] = {}
        with tarfile.open(str(archives[0]), "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
                extracted = archive.extractfile(member)
                if extracted is not None:
                    members[rel] = extracted.read()
        return members
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)
        shutil.rmtree(outdir, ignore_errors=True)


#: sdist 里 setuptools **必然**生成的包元数据（不是本仓产物）。逐名放行，多一个名字就红。
GENERATED_EGG_INFO = frozenset(
    {
        "src/agent_conflict_radar.egg-info/PKG-INFO",
        "src/agent_conflict_radar.egg-info/SOURCES.txt",
        "src/agent_conflict_radar.egg-info/dependency_links.txt",
        "src/agent_conflict_radar.egg-info/entry_points.txt",
        "src/agent_conflict_radar.egg-info/requires.txt",
        "src/agent_conflict_radar.egg-info/top_level.txt",
    }
)


def _extract_tar(archive: tarfile.TarFile, dest: Path) -> None:
    """解 tar；3.12+ 传 `filter="data"` 消掉弃用警告，3.8 退回无 filter 的旧签名（K6）。"""
    try:
        archive.extractall(str(dest), filter="data")
    except TypeError:
        archive.extractall(str(dest))


def _extract_members(members: Dict[str, bytes], dest: Path) -> Path:
    """把 `sdist_members()` 落到磁盘（中立目录），供"解包即用"检查真跑 CLI。"""
    dest = Path(dest)
    for rel, payload in members.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(str(target), "wb") as handle:
            handle.write(payload)
    return dest


# --------------------------------------------------------------------------------------
# MANIFEST.in 覆盖计算（C08）
# --------------------------------------------------------------------------------------


def manifest_covered(tracked: Sequence[str], manifest_text: str) -> Tuple[set, List[str]]:
    """按 setuptools 的 include/exclude 语义算出"被规则覆盖的路径集合"。

    `include` / `exclude` 用 fnmatch 对整条相对路径匹配；`recursive-include DIR PAT` 匹配
    `DIR/` 下任意层级；`prune DIR` 整目录剔除；`global-exclude PAT` 按文件名匹配任意层级。
    返回 `(覆盖集合, 命中的宽规则列表)`——宽规则单独报出来，因为"整目录兜底"会让
    "包里多了什么"不可审（本仓 MANIFEST 明令禁止）。
    """
    included = set()
    excluded = set()
    pruned: List[str] = []
    broad: List[str] = []
    for raw_line in manifest_text.split("\n"):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        directive = parts[0].lower()
        if directive in ("include", "exclude", "recursive-include", "prune", "global-exclude") and len(parts) < 2:
            continue
        if directive == "include":
            for pattern in parts[1:]:
                included.update(item for item in tracked if fnmatch.fnmatchcase(item, pattern))
        elif directive == "recursive-include":
            if len(parts) < 3:
                continue
            directory = parts[1].rstrip("/")
            for pattern in parts[2:]:
                if pattern == "*":
                    broad.append(line)
                prefix = directory + "/"
                for item in tracked:
                    if item.startswith(prefix) and fnmatch.fnmatchcase(item[len(prefix):], pattern):
                        included.add(item)
        elif directive == "exclude":
            for pattern in parts[1:]:
                excluded.update(item for item in tracked if fnmatch.fnmatchcase(item, pattern))
        elif directive == "prune":
            directory = parts[1].rstrip("/")
            pruned.append(directory)
        elif directive == "global-exclude":
            for pattern in parts[1:]:
                for item in tracked:
                    if fnmatch.fnmatchcase(item.rsplit("/", 1)[-1], pattern):
                        excluded.add(item)
    for item in tracked:
        for directory in pruned:
            if item == directory or item.startswith(directory + "/"):
                excluded.add(item)
    return included - excluded, broad


# --------------------------------------------------------------------------------------
# 检查项
# --------------------------------------------------------------------------------------
# 每条：ident, 标题, 函数(ctx) -> List[str]（空 = PASS）。**一条检查至少能被一条变异打红**。


def check_worktree_clean(ctx: Context) -> List[str]:
    """C01 工作树 = 历史：发布必须从一棵干净树出发（脏树打出的包不可复现）。"""
    code, out, _err = _run(["git", "status", "--porcelain", "-z"], cwd=ctx.root)
    if code != EXIT_PASS:
        raise EnvironmentMissing("git status 失败")
    entries = [item for item in out.split("\0") if item]
    return ["工作树有未提交改动：%s" % entries[:10]] if entries else []


def check_no_ignored_artifacts(ctx: Context) -> List[str]:
    """C02 跟踪面不含忽略产物（out/、egg-info、__pycache__、dist/、pytest 缓存）。"""
    forbidden = (
        "out/",
        ".venv/",
        "venv/",
        "dist/",
        "build/",
        ".pytest_cache/",
        "__pycache__/",
        ".egg-info/",
    )
    offenders = []
    for item in ctx.tracked():
        lowered = item.lower()
        if any(
            lowered.startswith(token) or ("/" + token) in lowered
            for token in forbidden
        ):
            offenders.append(item)
        if item.endswith((".egg-info", "MANIFEST")):
            offenders.append(item)
    return ["跟踪面含运行/构建产物：%s" % offenders[:10]] if offenders else []


def check_name_four_ways(ctx: Context) -> List[str]:
    """C03 名字四向一致（K14）：README H1 / 仓库名 / pyproject.name / 包名。"""
    failures: List[str] = []
    readme = ctx.read("README.md")
    first_line = readme.split("\n", 1)[0]
    if CANONICAL_NAME not in first_line:
        failures.append("README H1 不含规范产品名 %r：%r" % (CANONICAL_NAME, first_line))
    pyproject = ctx.read("pyproject.toml")
    if not re.search(r'^name\s*=\s*"%s"' % re.escape(CANONICAL_NAME), pyproject, re.MULTILINE):
        failures.append("pyproject.toml 的 name 不是 %r" % CANONICAL_NAME)
    if not re.search(r"Homepage\s*=\s*\"https://github\.com/%s\"" % re.escape(CANONICAL_SLUG), pyproject):
        failures.append("pyproject.toml 的 Homepage 不是 https://github.com/%s" % CANONICAL_SLUG)
    if not ctx.exists("src/agent_conflict_radar/__init__.py"):
        failures.append("包目录 src/agent_conflict_radar/__init__.py 不存在")
    else:
        init_text = ctx.read("src/agent_conflict_radar/__init__.py")
        if not re.search(r'^__version__\s*=\s*"[^"]+"', init_text, re.MULTILINE):
            failures.append("__init__.py 没有 __version__")
    if ctx.slug != CANONICAL_SLUG:
        failures.append("本次运行的目标仓库 %r 与规范坐标 %r 不一致" % (ctx.slug, CANONICAL_SLUG))
    return failures


def check_exit_codes_frozen(ctx: Context) -> List[str]:
    """C04 K1：退出码只有 0/1/2/3，`4 = 阶段未就绪` 不得复活。

    判据落在 **AST 名字引用**上，不在文本上：M5 的退役说明把 `StageNotReady` / `EXIT_NOT_READY`
    作为**历史名词**写进了注释与文档字符串——按子串扫会把"记录退役"误判成"退役失败"
    （本机实测：首版就这么红了一次）。真正要防的是"它们作为代码符号还存在"。
    """
    import ast

    source = ctx.root / "src" / "agent_conflict_radar"
    failures: List[str] = []
    revived: List[str] = []
    retired_names = ("EXIT_NOT_READY", "STAGE_NOT_READY", "StageNotReady")
    for path in sorted(source.rglob("*.py")):
        tree = ast.parse(_read(path), filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.alias):
                name = node.name.rsplit(".", 1)[-1]
            if name in retired_names:
                revived.append("%s:%d 引用 %s" % (path.name, node.lineno, name))
    if revived:
        failures.append("K1 退役的「阶段未就绪」复活了：%s" % revived)
    from agent_conflict_radar import exit_codes as exit_codes_module

    if tuple(exit_codes_module.ALL_EXIT_CODES) != (EXIT_OK, EXIT_CONFLICTS_FOUND, EXIT_USAGE, EXIT_ENVIRONMENT):
        failures.append("ALL_EXIT_CODES 不再是冻结的 (0, 1, 2, 3)")
    return failures


def check_matrix_self_check(ctx: Context) -> List[str]:
    """C05 冻结矩阵自检（K10）：形态 + 重生成逐字节 + 提交 sha 复算。"""
    failures = gen.check(str(ctx.bench_dir()))
    return ["矩阵自检失败：%s" % item for item in failures[:10]]


def check_matrix_machine_independent(ctx: Context) -> List[str]:
    """C06 K17：`bench/` 一切文本机器无关（无真实主目录、无真实用户名、无真实 UUID）。"""
    bench_dir = ctx.bench_dir()
    if not bench_dir.is_dir():
        return ["矩阵目录不存在：%s" % bench_dir]
    login = getpass.getuser().lower()
    offenders: List[str] = []
    for path in sorted(bench_dir.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".jsonl", ".md", ".py", ".txt"):
            continue
        text = _read(path)
        rel = path.relative_to(bench_dir).as_posix()
        for match in _DRIVE_USER_RE.finditer(text):
            segment = match.group(1).lower()
            if segment not in WHITELISTED_HOME_SEGMENTS and segment == login:
                offenders.append("%s 含真实用户名 %r" % (rel, match.group(1)))
        for pattern in (_BASH_HOME_RE, _POSIX_HOME_RE):
            for match in pattern.finditer(text):
                segment = match.group(1).lower()
                if segment not in WHITELISTED_HOME_SEGMENTS and segment == login:
                    offenders.append("%s 含真实主目录 %r" % (rel, match.group(0)))
        if _REAL_UUID_RE.search(text):
            offenders.append("%s 含真实 UUID 形态" % rel)
    return offenders[:10]


def _code_string_literals(source: str) -> List[str]:
    """取出 Python 源码里**代码位置**的字符串常量（跳过文档字符串与注释）。

    为什么必须跳过：判据是"不得**硬编码**真实主目录"，而文档里写
    `C:/Users/runneradmin/...` 是在**解释机制**（本仓 K16 的同类门禁早有这条纪律）。
    CI 首跑实测踩中：Windows runner 的真实用户名恰好是 `runneradmin`，于是一段解释
    "8.3 短名 vs 长名"的文档字符串被判成泄露，Windows 两条腿全红。
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstring_ids.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_ids
    ]


def check_commit_surface_desensitized(ctx: Context) -> List[str]:
    """C07 提交面脱敏：入库内容 + **提交元数据邮箱**（代码干净 ≠ 提交面干净）。

    扫描面取**受控树**（tag 树或 HEAD 树），不是工作区文件：工作区里未跟踪的东西不会进仓库。
    对 `.py` 只看**代码位置**的字符串常量（文档字符串是解释机制，不是硬编码路径）。
    """
    login = getpass.getuser().lower()
    offenders: List[str] = []
    for rel, raw in sorted(ctx.tree_files().items()):
        suffix = rel.rsplit(".", 1)[-1].lower()
        if suffix in ("png", "jpg", "jpeg", "gif", "pdf", "zip", "gz"):
            continue
        try:
            text = _normalize_newlines(raw.decode("utf-8"))
        except UnicodeDecodeError:
            continue
        if suffix == "py":
            # 逐条字符串常量判断，而不是扫整份文本——否则文档里的示例路径会误报。
            for literal in _code_string_literals(text):
                for match in _DRIVE_USER_RE.finditer(literal):
                    if match.group(1).lower() == login:
                        offenders.append("%s 含真实用户名 %r" % (rel, match.group(1)))
                for pattern in (_BASH_HOME_RE, _POSIX_HOME_RE):
                    for match in pattern.finditer(literal):
                        if match.group(1).lower() == login:
                            offenders.append("%s 含真实主目录 %r" % (rel, match.group(0)))
                if _REAL_UUID_RE.search(literal):
                    offenders.append("%s 含真实 UUID 形态" % rel)
            continue
        for match in _DRIVE_USER_RE.finditer(text):
            segment = match.group(1).lower()
            if segment == login:
                offenders.append("%s 含真实用户名 %r" % (rel, match.group(1)))
        for pattern in (_BASH_HOME_RE, _POSIX_HOME_RE):
            for match in pattern.finditer(text):
                segment = match.group(1).lower()
                if segment == login:
                    offenders.append("%s 含真实主目录 %r" % (rel, match.group(0)))
        if _REAL_UUID_RE.search(text):
            offenders.append("%s 含真实 UUID 形态" % rel)
    # 提交元数据邮箱：作者与提交者两侧都要查（M6 独有的漏点）。
    identities = ctx.git("log", "--format=%ae%n%ce").split("\n")
    for address in sorted({item.strip() for item in identities if item.strip()}):
        if not _ALLOWED_COMMIT_EMAIL_RE.match(address):
            offenders.append("提交元数据含非 noreply 邮箱：%s" % address)
    return offenders[:10]


def check_asset_build_is_deterministic(ctx: Context) -> List[str]:
    """C11 发布件可复现：同一 ref 连续建两次，**逐字节相同**。

    为什么要有这条：本机实测 setuptools 的 sdist **不是**逐字节可复现的（tar 成员带解包时刻的
    `mtime` 与 `uid/gid`，gzip 头也带当前时间）——同一 tag 连跑两次 sha256 不同。
    那会让"本地副本 + sha256 留档可复验"退化成"只有当时那一份对得上"。
    `_normalize_sdist_archive` 是修法；本检查是**钉住修法**的那道门（否则下次有人恢复成
    `shutil.copyfile` 也不会有任何东西变红）。
    """
    ref = ctx.tree_ref()
    normalize = ctx.normalize_archive()
    first_dir, first_name = _raw_sdist_archive(ctx.root, ref)
    second_dir, second_name = _raw_sdist_archive(ctx.root, ref)
    try:
        work = Path(tempfile.mkdtemp(prefix="radar-rel-det-"))
        try:
            one = work / ("a-" + first_name)
            two = work / ("b-" + second_name)
            normalize(first_dir / first_name, one)
            normalize(second_dir / second_name, two)
            if _sha256(one) != _sha256(two):
                return [
                    "同一 ref 连续两次构建的归档不一致（sha256 不同）：发布件不可复现，"
                    "sha256 留档无法复验。检查 `_normalize_sdist_archive` 是否仍在生效"
                ]
            return []
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    finally:
        shutil.rmtree(str(first_dir), ignore_errors=True)
        shutil.rmtree(str(second_dir), ignore_errors=True)


def check_manifest_coverage(ctx: Context) -> List[str]:
    """C08 MANIFEST.in 白名单覆盖 `bench/`（且无整目录兜底规则）。"""
    try:
        manifest_text = ctx.read("MANIFEST.in")
    except (OSError, KeyError):
        return ["缺少 MANIFEST.in"]
    tracked = ctx.tracked()
    covered, broad = manifest_covered(tracked, manifest_text)
    failures: List[str] = []
    expected_bench = {
        item
        for item in tracked
        if item.startswith("bench/") and item.rsplit("/", 1)[-1] not in RUNTIME_PRODUCTS
    }
    missing_bench = sorted(expected_bench - covered)
    if missing_bench:
        failures.append("MANIFEST.in 未覆盖 %d 个矩阵文件：%s" % (len(missing_bench), missing_bench[:10]))
    leaked_runtime = sorted(set(tracked) & covered & {
        item for item in tracked if item.rsplit("/", 1)[-1] in RUNTIME_PRODUCTS
    })
    if leaked_runtime:
        failures.append("MANIFEST.in 把运行产物带进包：%s" % leaked_runtime)
    missing_required = [item for item in REQUIRED_PACKAGE_FILES if item not in covered]
    if missing_required:
        failures.append("MANIFEST.in 未覆盖必需文件：%s" % missing_required)
    if broad:
        failures.append("MANIFEST.in 出现整目录兜底规则（不可审）：%s" % broad)
    return failures


def check_sdist_contents(ctx: Context) -> List[str]:
    """C09 真建 sdist 并逐条核对内容（C08 的实测版）。"""
    members = ctx.sdist_members()
    names = set(members)
    failures: List[str] = []
    tracked = ctx.tracked()
    expected_bench = {
        item
        for item in tracked
        if item.startswith("bench/") and item.rsplit("/", 1)[-1] not in RUNTIME_PRODUCTS
    }
    missing_bench = sorted(expected_bench - names)
    if missing_bench:
        failures.append("源码包缺 %d 个矩阵文件：%s" % (len(missing_bench), missing_bench[:10]))
    missing_required = [item for item in REQUIRED_PACKAGE_FILES if item not in names]
    if missing_required:
        failures.append("源码包缺必需文件：%s" % missing_required)
    leaked = sorted(
        name
        for name in names
        if name not in GENERATED_EGG_INFO
        and (
            name.rsplit("/", 1)[-1] in RUNTIME_PRODUCTS
            or "__pycache__" in name
            or name.startswith("out/")
            or name.startswith("dist/")
            or ".egg-info" in name
        )
    )
    if leaked:
        failures.append("源码包含运行/构建产物：%s" % leaked[:10])
    return failures


def check_extracted_self_sufficient(ctx: Context) -> List[str]:
    """C10 解包即用：把源码包解到中立目录，**从解包目录之外**跑 CLI（模块通路）。

    判据落在真跑上（`--version` / `selftest` / `bench --only` 三条），不是"包里有个 cli.py"。
    """
    members = ctx.sdist_members()
    work = Path(tempfile.mkdtemp(prefix="radar-rel-extract-"))
    neutral = Path(tempfile.mkdtemp(prefix="radar-rel-neutral-"))
    try:
        extracted = _extract_members(members, work)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(extracted / "src")
        env["PYTHONUTF8"] = "1"
        bench_dir = str(extracted / "bench")
        failures: List[str] = []
        cases = [
            ("--version", [sys.executable, "-m", "agent_conflict_radar", "--version"]),
            ("selftest", [sys.executable, "-m", "agent_conflict_radar", "selftest"]),
            (
                "bench --only",
                [
                    sys.executable,
                    "-m",
                    "agent_conflict_radar",
                    "bench",
                    "--only",
                    "same_symbol_diff_lines",
                    "--bench-dir",
                    bench_dir,
                ],
            ),
        ]
        for label, argv in cases:
            completed = subprocess.run(
                argv,
                cwd=str(neutral),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode != EXIT_PASS:
                detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
                failures.append("解包后 `%s` 退出码 %s：%s" % (label, completed.returncode, detail.strip()[:200]))
        return failures
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
        shutil.rmtree(str(neutral), ignore_errors=True)


# --------------------------------------------------------------------------------------
# 在线检查（--online）
# --------------------------------------------------------------------------------------


def _release_commit(ctx: Context) -> str:
    try:
        return ctx.git("rev-parse", "%s^{commit}" % ctx.tag).strip()
    except EnvironmentMissing as exc:
        # 本地都没有这个 tag ⇒ 发布未达成（不是环境缺失）。
        raise ReleaseNotAchieved("本地不存在 tag %r：%s" % (ctx.tag, exc))


def check_repo_public(ctx: Context) -> List[str]:
    """O01 仓库公开。"""
    info = ctx.gh_json("repos/%s" % ctx.slug)
    if info.get("private") is not False:
        return ["仓库不是公开的：private=%r" % info.get("private")]
    if str(info.get("visibility", "")).lower() != "public":
        return ["仓库 visibility 不是 public：%r" % info.get("visibility")]
    return []


def check_tag_points_at_release_commit(ctx: Context) -> List[str]:
    """O02 annotated tag 指向发布提交（tag 对象 → commit，且与本地一致）。"""
    ref = ctx.gh_json("repos/%s/git/ref/tags/%s" % (ctx.slug, ctx.tag))
    obj = ref.get("object", {})
    if obj.get("type") != "tag":
        return ["tag %r 不是 annotated tag（object.type=%r）" % (ctx.tag, obj.get("type"))]
    tag_object = ctx.gh_json("repos/%s/git/tags/%s" % (ctx.slug, obj.get("sha")))
    remote_commit = str(tag_object.get("object", {}).get("sha", ""))
    local_commit = _release_commit(ctx)
    if remote_commit != local_commit:
        return ["tag %r 指向 %s，本地解析为 %s（tag 打在了别的提交上）" % (ctx.tag, remote_commit, local_commit)]
    return []


def check_ci_jobs_green(ctx: Context) -> List[str]:
    """O03 CI 逐 job 全 success（发布提交上的**每一条** run、每一个 job）。"""
    commit = _release_commit(ctx)
    runs = ctx.gh_json("repos/%s/actions/runs?head_sha=%s&per_page=100" % (ctx.slug, commit))
    items = runs.get("workflow_runs", [])
    if not items:
        return ["发布提交 %s 上没有任何 CI run" % commit]
    failures: List[str] = []
    for run in items:
        if run.get("conclusion") != "success":
            failures.append("run %s 结论为 %r" % (run.get("id"), run.get("conclusion")))
        jobs = ctx.gh_json("repos/%s/actions/runs/%s/jobs?per_page=100" % (ctx.slug, run.get("id")))
        job_items = jobs.get("jobs", [])
        if not job_items:
            failures.append("run %s 没有任何 job" % run.get("id"))
        for job in job_items:
            if job.get("conclusion") != "success":
                failures.append(
                    "run %s 的 job %r 结论为 %r" % (run.get("id"), job.get("name"), job.get("conclusion"))
                )
    return failures[:10]


def check_push_runs_reconciled(ctx: Context) -> List[str]:
    """O04 push 事件 ↔ run 对账：**每次推送恰好一条 run**；tag push 与发布提交的 branch push 都绿。

    ⚠️ 判据必须区分「当前状态」与「历史轮次」：本仓首推曾四腿全红（如实照录，不抹除）。
    若要求"所有历史 run 都 success"，唯一的通过方式就是改写历史——那正是 DoD
    「首跑失败照录不抹除」要防的事。所以：

    * **每次推送**（按 `head_sha` 归并）的 run 数必须等于 workflow 数——缺一条说明
      "CI 绿"这件事没有对应的那次推送，多一条说明有重跑未收口；
    * **tag push** 的 run 必须全绿（发布口径）；
    * **发布提交**（tag 指向的 commit）的 branch push run 必须全绿（与 O03 互证）；
    * 其余更早提交上的失败轮次**只登记不判红**（`recorded` 列表，随输出打印）。
    """
    workflows = sorted((ctx.root / ".github" / "workflows").glob("*.yml"))
    if not workflows:
        return [".github/workflows 下没有 workflow 文件"]
    per_event = len(workflows)
    payload = ctx.gh_json("repos/%s/actions/runs?event=push&per_page=100" % ctx.slug)
    runs = [run for run in payload.get("workflow_runs", []) if run.get("event") == "push"]
    if not runs:
        return ["没有任何 push 事件的 CI run"]
    failures: List[str] = []
    info = ctx.gh_json("repos/%s" % ctx.slug)
    default_branch = str(info.get("default_branch", ""))
    release_commit = _release_commit(ctx)

    tag_runs = [run for run in runs if run.get("head_branch") == ctx.tag]
    if len(tag_runs) != per_event:
        failures.append("tag push 的 run 数 %d ≠ workflow 数 %d" % (len(tag_runs), per_event))
    for run in tag_runs:
        if run.get("conclusion") != "success":
            failures.append("tag push 的 run %s 结论为 %r" % (run.get("id"), run.get("conclusion")))

    release_branch_runs = [
        run
        for run in runs
        if run.get("head_branch") == default_branch and str(run.get("head_sha", "")) == release_commit
    ]
    if len(release_branch_runs) != per_event:
        failures.append(
            "发布提交 %s 的 branch push run 数 %d ≠ workflow 数 %d"
            % (release_commit[:12], len(release_branch_runs), per_event)
        )
    for run in release_branch_runs:
        if run.get("conclusion") != "success":
            failures.append("发布提交的 branch run %s 结论为 %r" % (run.get("id"), run.get("conclusion")))

    # 每次推送 = 每个被推送提交**在每个 workflow 上**恰一条 run。
    # ⚠️ 判据按 (提交, workflow) 计，而不是按提交计数：同一个提交可能被 **branch push 与
    # tag push 各推一次**（本仓的发布提交就是这样），那时该提交有 2 条 run 是**正确**的。
    # 首版按提交计数，于是发布提交必红（本机实测）。
    # 判据按 **(提交, workflow, 事件来源)** 计：`head_branch` 区分 branch push 与 tag push。
    # 发布提交同时被 branch push 与 tag push 各推一次，是**正确**的发布形态（本仓即如此）；
    # 首版按提交计数，于是发布提交必红（本机实测）。真正要防的是"同一个来源重复触发"。
    per_pair: Dict[Tuple[str, str, str], int] = {}
    for run in runs:
        key = (
            str(run.get("head_sha", "")),
            str(run.get("workflow_id", "")) or str(run.get("name", "")),
            str(run.get("head_branch", "")),
        )
        per_pair[key] = per_pair.get(key, 0) + 1
    for (sha, workflow, branch), count in sorted(per_pair.items()):
        if count != 1:
            failures.append(
                "提交 %s 在 %r 上的 workflow %r 有 %d 条 push run（要求恰好 1 条）"
                % (sha[:12], branch, workflow, count)
            )

    # 历史失败轮次：只登记，不判红（DoD：首跑失败照录不抹除）。
    recorded = sorted(
        (str(run.get("id")), str(run.get("head_sha", ""))[:12], str(run.get("conclusion")))
        for run in runs
        if run.get("conclusion") not in (None, "success")
    )
    if recorded and getattr(ctx, "verbose", False):
        print("       历史失败轮次（照录，不判红）：%s" % recorded)
    return failures[:10]


#: 源码包成员与 tag 树之间**允许**不同的名字（都是打包/工具生成的，不是源码内容）。
_PACKAGE_METADATA = frozenset({"PKG-INFO", "setup.cfg"}) | GENERATED_EGG_INFO


def check_attachment_matches_tag_tree(ctx: Context) -> List[str]:
    """O07 本体一致性：Release 附件与 **tag 树**逐字节同源。

    为什么单列一条：O05 只核对"名字 + 字节数"、O06 只核对"sha256 与登记一致"。两者都通过，
    仍然可能是"登记时就算错了"或"传的是另一个包"。这条把**远端的字节**与**tag 树的字节**
    直接比。

    判据按 **MANIFEST.in 的白名单意图**取交集，而不是"tag 树里每个文件都必须在包里"：
    源码包本来就**不该**含 `.gitignore` / `.gitattributes` / `.github/` 与运行产物
    `bench/last_run.json`（后者在 MANIFEST 里显式 exclude）。首版把"tag 树 ⊆ 包"当成同源，
    在真实发布时立刻误报 5 个文件（本机实测）——那不是包错了，是判据把"源码包"当成了"整仓快照"。

    因此三层判据：
    1. **被 MANIFEST 覆盖的 tag 树文件**必须全部在包里，且逐字节相同（这是"同源"的实质）；
    2. 包里不得出现 MANIFEST 覆盖之外的内容（放行打包器生成的元数据）；
    3. 运行产物不得出现在包里。
    """
    ledger = _ledger(ctx)
    entries = ledger.get("assets", [])
    if not entries:
        return ["附件登记为空：无可比对对象"]
    tree = ctx.tree_files()
    manifest_text = ctx.read("MANIFEST.in")
    covered, _broad = manifest_covered(sorted(tree), manifest_text)
    # `src/` 下的包文件由 setuptools 的 `packages.find` **自动**纳入源码包，不需要（也不应该）
    # 在 MANIFEST.in 里再列一遍——它们同样是"tag 树里该进包的内容"。
    auto_packaged = {
        item for item in tree if item.startswith("src/") and item.endswith(".py")
    }
    expected = (set(covered) | auto_packaged) - set(RUNTIME_PRODUCTS)
    work = Path(tempfile.mkdtemp(prefix="radar-rel-identity-"))
    failures: List[str] = []
    try:
        for entry in entries:
            name = entry["name"]
            try:
                path = ctx.download_asset(name, work)
            except EnvironmentMissing as exc:
                failures.append(str(exc))
                continue
            try:
                with tarfile.open(str(path), "r:*") as archive:
                    members = {
                        member.name.split("/", 1)[1]: archive.extractfile(member).read()
                        for member in archive.getmembers()
                        if member.isfile() and "/" in member.name
                    }
            except tarfile.TarError as exc:
                failures.append("附件 %r 不是可读的 tar 包：%s" % (name, exc))
                continue
            missing = sorted(expected - set(members))
            extra = sorted(set(members) - expected - _PACKAGE_METADATA)
            if missing:
                failures.append(
                    "附件 %r 缺 MANIFEST 覆盖的 %d 个文件：%s" % (name, len(missing), missing[:5])
                )
            if extra:
                failures.append(
                    "附件 %r 有 MANIFEST 未覆盖的 %d 个文件：%s" % (name, len(extra), extra[:5])
                )
            runtime_leaks = sorted(
                rel for rel in members if rel.rsplit("/", 1)[-1] in RUNTIME_PRODUCTS
            )
            if runtime_leaks:
                failures.append("附件 %r 含运行产物：%s" % (name, runtime_leaks))
            differing = sorted(rel for rel in expected & set(members) if tree.get(rel) != members[rel])
            if differing:
                failures.append(
                    "附件 %r 与 tag 树内容不一致（%d 个文件）：%s"
                    % (name, len(differing), differing[:5])
                )
        return failures[:10]
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def _ledger(ctx: Context) -> Dict[str, Any]:
    path = ctx.root / ASSET_LEDGER_RELPATH
    if not path.is_file():
        # 登记文件缺席 = 发布流程没走完（tag 后追加提交还没做），不是环境缺失。
        raise ReleaseNotAchieved(
            "缺少附件登记 %s：先用 --record-assets 生成，并作为 tag 之后的追加提交入库"
            % ASSET_LEDGER_RELPATH
        )
    return json.loads(_read(path))


def check_release_assets_match_ledger(ctx: Context) -> List[str]:
    """O05 Release 附件集合与登记一致（名字 + 字节数；多传/漏传都红）。"""
    ledger = _ledger(ctx)
    expected = {entry["name"]: int(entry["size"]) for entry in ledger.get("assets", [])}
    if not expected:
        return ["附件登记为空：Release 必须带手工上传的源码包"]
    payload = ctx.gh_json("repos/%s/releases/tags/%s" % (ctx.slug, ctx.tag))
    actual = {asset.get("name"): int(asset.get("size", -1)) for asset in payload.get("assets", [])}
    failures: List[str] = []
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        failures.append("Release 缺少登记过的附件：%s" % missing)
    if extra:
        failures.append("Release 有未登记的附件：%s" % extra)
    for name in sorted(set(expected) & set(actual)):
        if expected[name] != actual[name]:
            failures.append("附件 %r 字节数 %d ≠ 登记 %d" % (name, actual[name], expected[name]))
    return failures


def check_assets_sha256_recomputed(ctx: Context) -> List[str]:
    """O06 逐个下载附件复算 sha256（登记值必须能从网上重新算出来）。"""
    ledger = _ledger(ctx)
    work = Path(tempfile.mkdtemp(prefix="radar-rel-download-"))
    failures: List[str] = []
    try:
        for entry in ledger.get("assets", []):
            name = entry["name"]
            try:
                path = ctx.download_asset(name, work)
            except EnvironmentMissing as exc:
                failures.append(str(exc))
                continue
            actual = _sha256(path)
            if actual != entry["sha256"]:
                failures.append("附件 %r 的 sha256 %s ≠ 登记 %s" % (name, actual, entry["sha256"]))
        if not ledger.get("assets"):
            failures.append("附件登记为空：无可复算对象")
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return failures


#: README 里的**机读条数锚**：`release-gate-counts offline=<n> online=<n> mutations=<n>`。
#: 为什么要有它：M6 发布物的 README 曾写"离线 10 条 + 在线 6 条"（=16），同一页又写
#: "18 组变异"——16 ≠ 18 自相矛盾，而**没有任何判据**把这两个数字钉住。文档里的条数必须由
#: 代码对账，否则"改门必须同步改文档"只是注释里的君子协定。
_GATE_COUNTS_ANCHOR_RE = re.compile(
    r"release-gate-counts\s+offline=(\d+)\s+online=(\d+)\s+mutations=(\d+)"
)

#: README 里的检查编号区间（`离线 C01–C… / 在线 O01–O…`）：读者据此知道"该跑几条"。
_GATE_RANGE_RE = re.compile(r"离线\s*C01[–-]C(\d+)\s*/\s*在线\s*O01[–-]O(\d+)")


def documented_gate_counts(text: str) -> Optional[Dict[str, int]]:
    """从 README 文本里抽出发布门的登记条数；抽不到返回 `None`（= 锚缺席，不是"零条"）。"""
    match = _GATE_COUNTS_ANCHOR_RE.search(text)
    if not match:
        return None
    return {
        "offline": int(match.group(1)),
        "online": int(match.group(2)),
        "mutations": int(match.group(3)),
    }


def check_documented_gate_counts(ctx: Context) -> List[str]:
    """C12 文档登记的发布门条数 == 检查表实际条数（数字不靠人记）。

    判据落在**代码算出来的** `len(OFFLINE_CHECKS)` / `len(ONLINE_CHECKS)` / `len(_mutation_worlds())`
    上，而不是"文档里那个数字看起来合理"。顺带把编号区间也对齐：区间写"到 C11"而表里已有 C12，
    同样是"读者照文档跑会少跑一条"。
    """
    readme = ctx.read("README.md")
    declared = documented_gate_counts(readme)
    if declared is None:
        return [
            "README 缺少机读条数锚 `release-gate-counts offline=… online=… mutations=…`："
            "文档里的条数必须能被代码核对（否则改门后文档必然漂移）"
        ]
    actual = {
        "offline": len(OFFLINE_CHECKS),
        "online": len(ONLINE_CHECKS),
        "mutations": len(_mutation_worlds()),
    }
    failures = [
        "登记 %s=%d ≠ 检查表实际 %d" % (key, declared[key], actual[key])
        for key in ("offline", "online", "mutations")
        if declared[key] != actual[key]
    ]
    ranges = _GATE_RANGE_RE.search(readme)
    if ranges is None:
        failures.append(
            "README 缺少检查编号区间 `离线 C01–C… / 在线 O01–O…`：读者据此知道该跑几条"
        )
    else:
        if int(ranges.group(1)) != actual["offline"]:
            failures.append(
                "README 的离线区间写到 C%s ≠ 实际 %d 条" % (ranges.group(1), actual["offline"])
            )
        if int(ranges.group(2)) != actual["online"]:
            failures.append(
                "README 的在线区间写到 O%s ≠ 实际 %d 条" % (ranges.group(2), actual["online"])
            )
    return failures


OFFLINE_CHECKS: List[Tuple[str, str, Callable[[Context], List[str]]]] = [
    ("C01", "工作树 = 历史（无未提交改动）", check_worktree_clean),
    ("C02", "跟踪面不含运行/构建产物", check_no_ignored_artifacts),
    ("C03", "名字四向一致（K14）", check_name_four_ways),
    ("C04", "退出码只有 0/1/2/3（K1 不回潮）", check_exit_codes_frozen),
    ("C05", "冻结矩阵自检（K10）", check_matrix_self_check),
    ("C06", "矩阵机器无关（K17）", check_matrix_machine_independent),
    ("C07", "提交面脱敏（含提交邮箱）", check_commit_surface_desensitized),
    ("C08", "MANIFEST.in 覆盖 bench/ 且无兜底规则", check_manifest_coverage),
    ("C09", "真建 sdist 并逐条核对内容", check_sdist_contents),
    ("C10", "解包即用（从解包目录之外跑 CLI）", check_extracted_self_sufficient),
    ("C11", "发布件可复现（同 ref 两次构建逐字节相同）", check_asset_build_is_deterministic),
    ("C12", "文档登记的发布门条数与检查表一致", check_documented_gate_counts),
]

ONLINE_CHECKS: List[Tuple[str, str, Callable[[Context], List[str]]]] = [
    ("O01", "仓库公开", check_repo_public),
    ("O02", "annotated tag 指向发布提交", check_tag_points_at_release_commit),
    ("O03", "CI 逐 job 全 success", check_ci_jobs_green),
    ("O04", "push 事件 ↔ run 对账（tag/branch 各一条且都绿）", check_push_runs_reconciled),
    ("O05", "Release 附件集合与登记一致", check_release_assets_match_ledger),
    ("O06", "逐个下载附件复算 sha256", check_assets_sha256_recomputed),
    ("O07", "附件与 tag 树逐字节同源", check_attachment_matches_tag_tree),
]


# --------------------------------------------------------------------------------------
# 变异验证：每条检查至少被一条变异打红；检查项数 == 变异组数
# --------------------------------------------------------------------------------------


def _tmp_tree(files: Dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="radar-rel-mut-"))
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return root


def _tmp_git_repo(files: Dict[str, str]) -> Path:
    root = _tmp_tree(files)
    _run(["git", "init", "-q"], cwd=root)
    _run(["git", "config", "user.email", "282769740+yuluo554@users.noreply.github.com"], cwd=root)
    _run(["git", "config", "user.name", "yuluo554"], cwd=root)
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-q", "-m", "base"], cwd=root)
    return root


class Mutation(object):
    def __init__(self, ident: str, check_id: str, note: str, build: Callable[[], Context]):
        self.ident = ident
        self.check_id = check_id
        self.note = note
        self.build = build


def _mutation_worlds() -> List[Mutation]:
    """19 条变异——每条对应一条检查项（`run_mutation` 断言数量相等）。"""

    def c01() -> Context:
        root = _tmp_git_repo({"README.md": "x\n"})
        with open(str(root / "README.md"), "a", encoding="utf-8") as handle:
            handle.write("dirty\n")
        return Context(root)

    def c02() -> Context:
        root = _tmp_git_repo({"README.md": "x\n", "out/report.md": "stale\n"})
        return Context(root)

    def c03() -> Context:
        files = {
            "README.md": "# 拼错的名字\n",
            "pyproject.toml": '[project]\nname = "wrong-name"\n',
            "src/agent_conflict_radar/__init__.py": '__version__ = "0.0.1"\n',
        }
        root = _tmp_tree(files)
        return Context(
            root,
            tree_files=lambda: dict((rel, text.encode("utf-8")) for rel, text in files.items()),
        )

    def c04() -> Context:
        root = _tmp_tree({"src/agent_conflict_radar/exit_codes.py": "EXIT_NOT_READY = 4\n"})
        return Context(root)

    def c05() -> Context:
        return Context(REPO_ROOT, bench_dir=tempfile.mkdtemp(prefix="radar-rel-emptybench-"))

    def c06() -> Context:
        bench = Path(tempfile.mkdtemp(prefix="radar-rel-leakbench-"))
        leak = bench / "manifest.json"
        leak.write_text('{"path": "C:/Users/%s/repo"}\n' % getpass.getuser(), encoding="utf-8")
        return Context(REPO_ROOT, bench_dir=bench)

    def c07() -> Context:
        leaked = "root = C:/Users/%s/project\n" % getpass.getuser()
        root = _tmp_tree({"leak.txt": leaked})
        return Context(
            root,
            tracked=lambda: ["leak.txt"],
            tree_files=lambda: {"leak.txt": leaked.encode("utf-8")},
            git=lambda *args: "real.person@example.com\n",
        )

    def c08() -> Context:
        tracked = ["bench/scenarios/s01/truth.json", "bench/scenarios/s01/sessions/a.jsonl", "README.md"]
        root = _tmp_tree(
            {
                "MANIFEST.in": "include README.md\nrecursive-include bench *.json\n",
                "README.md": "x\n",
                "bench/scenarios/s01/truth.json": "{}\n",
                "bench/scenarios/s01/sessions/a.jsonl": "{}\n",
            }
        )
        files = {
            name: (root / name).read_bytes()
            for name in tracked
            if (root / name).is_file()
        }
        return Context(root, tracked=lambda: list(tracked), tree_files=lambda: dict(files))

    def c09() -> Context:
        members = {"README.md": b"x\n", "pyproject.toml": b"", "LICENSE": b"MIT\n"}
        return Context(
            REPO_ROOT,
            tracked=lambda: list(REQUIRED_PACKAGE_FILES),
            sdist_members=lambda: dict(members),
        )

    def c10() -> Context:
        # 缺 config/radar.toml 的"源码包"：解包后 selftest 必然失败。
        members = {
            "README.md": b"x\n",
            "pyproject.toml": _read(REPO_ROOT / "pyproject.toml").encode("utf-8"),
            "LICENSE": b"MIT\n",
            "src/agent_conflict_radar/__init__.py": b'__version__ = "0.0.1"\n',
            "src/agent_conflict_radar/__main__.py": _read(
                REPO_ROOT / "src" / "agent_conflict_radar" / "__main__.py"
            ).encode("utf-8"),
        }
        return Context(
            REPO_ROOT,
            tracked=lambda: list(REQUIRED_PACKAGE_FILES),
            sdist_members=lambda: dict(members),
        )

    def o01() -> Context:
        return Context(REPO_ROOT, tag="v0.0.1", gh_json=lambda path: {"private": True, "visibility": "private"})

    def o02() -> Context:
        def gh(path: str) -> Any:
            if "/git/ref/tags/" in path:
                return {"object": {"type": "tag", "sha": "tagobj"}}
            return {"object": {"sha": "deadbeef"}}

        return Context(REPO_ROOT, tag="v0.0.1", git=lambda *a: "cafebabe\n", gh_json=gh)

    def o03() -> Context:
        def gh(path: str) -> Any:
            if "head_sha=" in path:
                return {"workflow_runs": [{"id": 1, "conclusion": "success"}]}
            if "/jobs" in path:
                return {"jobs": [{"name": "ubuntu / py3.12", "conclusion": "failure"}]}
            return {"default_branch": "main"}

        return Context(REPO_ROOT, tag="v0.0.1", git=lambda *a: "cafebabe\n", gh_json=gh)

    def o04() -> Context:
        def gh(path: str) -> Any:
            if "?event=push" in path:
                return {
                    "workflow_runs": [
                        {"id": 1, "event": "push", "head_branch": "main", "head_sha": "sha1", "conclusion": "success"}
                    ]
                }
            return {"default_branch": "main"}

        return Context(REPO_ROOT, tag="v0.0.1", gh_json=gh)

    def o05() -> Context:
        ledger = Path(tempfile.mkdtemp(prefix="radar-rel-ledger-")) / "release-assets.json"

        def gh(path: str) -> Any:
            if "/releases/tags/" in path:
                return {"assets": [{"name": "other.tar.gz", "size": 1}]}
            return {"default_branch": "main"}

        root = _tmp_tree({"plan/release-assets.json": json.dumps({
            "assets": [{"name": "agent-conflict-radar-0.0.1.tar.gz", "sha256": "0" * 64, "size": 123}]
        })})
        del ledger
        return Context(root, tag="v0.0.1", gh_json=gh)

    def o06() -> Context:
        root = _tmp_tree({"plan/release-assets.json": json.dumps({
            "assets": [{"name": "a.tar.gz", "sha256": "0" * 64, "size": 1}]
        })})

        def download(name: str, dest: Path) -> Path:
            target = Path(dest) / name
            target.write_bytes(b"tampered")
            return target

        return Context(root, tag="v0.0.1", download_asset=download)

    def o07() -> Context:
        # 附件里 tag 树中那个文件的内容被改了一个字节：sha256 登记可以照样对（因为登记也按坏包算），
        # 但"与 tag 树逐字节同源"必须变红。
        root = _tmp_tree({"plan/release-assets.json": json.dumps({
            "assets": [{"name": "a.tar.gz", "sha256": "0" * 64, "size": 1}]
        })})

        def download(name: str, dest: Path) -> Path:
            target = Path(dest) / name
            inner = Path(dest) / "_inner"
            (inner / "src").mkdir(parents=True, exist_ok=True)
            (inner / "src" / "mod.py").write_text("TAMPERED = 1\n", encoding="utf-8")
            with tarfile.open(str(target), "w:gz") as archive:
                archive.add(str(inner / "src" / "mod.py"), arcname="pkg-0.0.1/src/mod.py")
            return target

        return Context(
            root,
            tag="v0.0.1",
            download_asset=download,
            # O07 现在按 MANIFEST 覆盖取期望集合，因此变异世界也要给一份 MANIFEST；
            # 否则它会在读 MANIFEST 时抛 FileNotFoundError（被误报成"变异世界异常"）。
            read=lambda rel: "recursive-include src *.py\n" if rel == "MANIFEST.in" else "",
            tree_files=lambda: {"src/mod.py": b"GOOD = 1\n"},
        )

    def c11() -> Context:
        # 把归档归一换成"原样拷贝"：同 ref 两次构建必然不同（mtime / uid 变了），C11 必须红。
        def passthrough(src, dst):
            shutil.copyfile(str(src), str(dst))

        # C11 必须真建两次 sdist，而构建要一个 git 仓库；用仓库自身（HEAD）但**只换归一函数**。
        return Context(REPO_ROOT, tree_ref=lambda: "HEAD", normalize_archive=passthrough)

    def c12() -> Context:
        # README 的机读锚写成与实际条数不符（离线 1 / 在线 1 / 变异 1）→ C12 必红。
        readme = "release-gate-counts offline=1 online=1 mutations=1\n离线 C01–C1 / 在线 O01–O1\n"
        return Context(_tmp_tree({}), read=lambda rel: readme if rel == "README.md" else "")

    return [
        Mutation("R01", "C01", "工作树脏 → C01 必红", c01),
        Mutation("R02", "C02", "跟踪面含 out/ → C02 必红", c02),
        Mutation("R03", "C03", "README/名字写错 → C03 必红", c03),
        Mutation("R04", "C04", "EXIT_NOT_READY 复活 → C04 必红", c04),
        Mutation("R05", "C05", "矩阵目录为空 → C05 必红", c05),
        Mutation("R06", "C06", "矩阵含真实主目录 → C06 必红", c06),
        Mutation("R07", "C07", "入库内容/提交邮箱含真实值 → C07 必红", c07),
        Mutation("R08", "C08", "MANIFEST 漏 *.jsonl → C08 必红", c08),
        Mutation("R09", "C09", "源码包缺文件 → C09 必红", c09),
        Mutation("R10", "C10", "解包后不可用（缺配置） → C10 必红", c10),
        Mutation("R11", "O01", "仓库私有 → O01 必红", o01),
        Mutation("R12", "O02", "tag 指向别的提交 → O02 必红", o02),
        Mutation("R13", "O03", "某个 job 失败 → O03 必红", o03),
        Mutation("R14", "O04", "缺 tag push 的 run → O04 必红", o04),
        Mutation("R15", "O05", "附件集合与登记不符 → O05 必红", o05),
        Mutation("R16", "O06", "下载内容与 sha256 不符 → O06 必红", o06),
        Mutation("R17", "O07", "附件内容与 tag 树不一致 → O07 必红", o07),
        Mutation("R18", "C11", "归档归一被去掉（同 ref 两次构建不同）→ C11 必红", c11),
        Mutation("R19", "C12", "README 条数锚与实际不符 → C12 必红", c12),
    ]


# --------------------------------------------------------------------------------------
# 运行
# --------------------------------------------------------------------------------------


def _all_checks() -> List[Tuple[str, str, Callable[[Context], List[str]]]]:
    return list(OFFLINE_CHECKS) + list(ONLINE_CHECKS)


def run_checks(ctx: Context, checks, verbose: bool = True) -> List[str]:
    """逐条跑检查，返回 FAIL 列表（空 = 全过）。"""
    failures: List[str] = []
    for ident, title, func in checks:
        try:
            problems = func(ctx)
        except EnvironmentMissing:
            raise
        except ReleaseNotAchieved as exc:
            problems = [str(exc)]
        except Exception:  # 检查自身炸掉也必须算 FAIL，不能静默跳过
            problems = ["检查内部异常：%s" % traceback.format_exc(limit=2).strip().replace("\n", " | ")]
        if problems:
            failures.append(ident)
            if verbose:
                print("[FAIL] %s %s" % (ident, title))
                for item in problems:
                    print("       - %s" % item)
        elif verbose:
            print("[PASS] %s %s" % (ident, title))
    return failures


def run_mutation(verbose: bool = True) -> int:
    """门自身的变异验证。返回退出码（0 = 每条检查都有且仅有一条变异打红它）。"""
    checks = _all_checks()
    mutations = _mutation_worlds()
    check_ids = [ident for ident, _title, _func in checks]
    mutation_targets = [mutation.check_id for mutation in mutations]
    failures: List[str] = []

    if len(mutations) != len(checks):
        failures.append(
            "检查项数 %d ≠ 变异组数 %d：有检查项其实没在查东西（或缺一条变异）"
            % (len(checks), len(mutations))
        )
    for ident in check_ids:
        hits = [mutation for mutation in mutations if mutation.check_id == ident]
        if len(hits) != 1:
            failures.append("检查项 %s 有 %d 条变异（要求恰好 1 条）" % (ident, len(hits)))
    extra = sorted(set(mutation_targets) - set(check_ids))
    if extra:
        failures.append("变异指向了不存在的检查项：%s" % extra)

    by_id = {ident: func for ident, _title, func in checks}
    for mutation in mutations:
        func = by_id.get(mutation.check_id)
        if func is None:
            continue
        # ⚠️ 三种结局必须分开：「被检查打红」（真抓到）、「检查无法执行」（环境缺失 → 既不算抓到
        # 也不算漏报，必须显式报成 inconclusive）、「检查自身炸了」（同样不算抓到）。
        # 首版把三者混成 `problems = [...]` 再取 bool，于是"环境缺失"会被打印成 CAUGHT——
        # 那是变异验证里最坏的一种假绿（本机复核时发现）。
        caught = False
        inconclusive = ""
        try:
            problems = func(mutation.build())
            caught = bool(problems)
        except EnvironmentMissing as exc:
            inconclusive = "变异世界触发环境缺失：%s" % exc
        except ReleaseNotAchieved as exc:
            caught = True
            problems = [str(exc)]
        except Exception as exc:  # 变异世界构造失败也要报，不能当成"抓到了"
            inconclusive = "变异世界自身异常：%r" % exc
        if verbose:
            verdict = "CAUGHT" if caught else ("INCONCLUSIVE" if inconclusive else "MISSED")
            print("[%s] %s → %s（%s）" % (verdict, mutation.ident, mutation.check_id, mutation.note))
        if inconclusive:
            failures.append(
                "%s 的变异 %s 无法判定（%s）：环境缺失/构造失败都不能算「被抓到」"
                % (mutation.check_id, mutation.ident, inconclusive)
            )
        elif not caught:
            failures.append("%s 未被 %s 抓到：该项检查是假门" % (mutation.check_id, mutation.ident))

    if failures:
        print("\n变异验证未通过（%d 项）：" % len(failures))
        for item in failures:
            print("  - %s" % item)
        return EXIT_FAIL
    print("\n变异验证通过：%d 条检查 ↔ %d 条变异，逐条被打红。" % (len(checks), len(mutations)))
    return EXIT_PASS


def _normalize_sdist_archive(source: Path, target: Path) -> None:
    """把 setuptools 产出的 sdist 归一成**确定性归档**（同一 tag 重跑 → 逐字节相同）。

    为什么必须做：本机实测 setuptools 的 sdist **不是**逐字节可复现的——tar 成员带解包时刻的
    `mtime`、属主 `uid/gid`，gzip 头也带当前时间。同一 tag 连跑两次得到两个 sha256，
    "本地副本 + sha256 留档可复验"就退化成"只有那一次跑出来的那份对得上"。

    归一口径（只改**打包元数据**，不改任何文件内容）：
    * 成员 `mtime` = 固定纪元、`uid/gid` = 0、`uname/gname` = 空、去掉 `pax_global_header`；
    * gzip 头 `mtime` = 固定纪元。
    文件内容与成员顺序保持原样——所以 O07（与 tag 树逐字节同源）依然成立。
    """
    fixed = 0  # 结构化常量：归档纪元，不是策略阈值
    with tarfile.open(str(source), "r:gz") as source_archive:
        members = []
        for member in source_archive.getmembers():
            if member.name == "pax_global_header" or not (member.isfile() or member.isdir()):
                continue
            member.mtime = fixed
            member.uid = member.gid = fixed
            member.uname = member.gname = ""
            member.mode = 0o755 if member.isdir() else 0o644
            payload = source_archive.extractfile(member) if member.isfile() else None
            members.append((member, payload.read() if payload is not None else None))
    import gzip

    with gzip.GzipFile(filename="", mode="wb", fileobj=open(str(target), "wb"), mtime=fixed) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as out:
            for member, payload in members:
                if payload is None:
                    out.addfile(member)
                else:
                    import io

                    out.addfile(member, io.BytesIO(payload))


def _build_sdist_argv(outdir: str, source_dir: Path) -> List[str]:
    """`python -m build --sdist` 的参数；能离线就离线。

    为什么默认要 `--no-isolation`：构建隔离会去 PyPI 抓 `setuptools`/`wheel`，而本项目的
    运行前提是"断网可跑"。Python 3.8 那台环境里 `setuptools`/`wheel` 都在，隔离反而让
    sdist 构建**因为没网**而失败（本机实测：3.12 通过、3.8 报
    `No matching distribution found for wheel`）。

    取舍写在明处：只有当**本解释器**已经能 import `setuptools` 与 `wheel` 时才关隔离；
    否则退回默认隔离（那种情况下必然联网，属于环境问题而不是门的问题）。
    """
    argv = [sys.executable, "-m", "build", "--sdist", "--outdir", outdir]
    # ⚠️ 不能用 `import wheel` 判断：setuptools 自带一个 `_vendor/wheel`，`import wheel` 会命中
    # 它，而 `build` 认的是**安装元数据**里的 `wheel` 发行包（本机实测：import 成功、build 仍报
    # `wheel: found: not installed`）。判据必须落在 importlib.metadata 上。
    try:
        import importlib.metadata as metadata

        metadata.version("setuptools")
        metadata.version("wheel")
        argv.append("--no-isolation")
    except Exception:
        pass
    argv.append(str(source_dir))
    return argv


def _raw_sdist_archive(root: Path, ref: str) -> Tuple[Path, str]:
    """从受控树建一份**原始** sdist，返回 `(临时目录, 归档文件名)`。

    调用方负责清理返回的临时目录。抽成函数是为了让 `--build-asset` 与发布门 C11
    （归档确定性）走**同一条构建路径**——"门验的和上传的不是同一条路"是这次要防的形态。
    """
    export_dir = tempfile.mkdtemp(prefix="radar-rel-asset-src-")
    outdir = tempfile.mkdtemp(prefix="radar-rel-asset-out-")
    try:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", ref], cwd=str(root), stdout=subprocess.PIPE
        )
        if completed.returncode != EXIT_PASS:
            raise EnvironmentMissing("git archive %s 失败" % ref)
        archive_path = Path(export_dir) / "_tree.tar"
        with open(str(archive_path), "wb") as handle:
            handle.write(completed.stdout)
        tree_dir = Path(export_dir) / "tree"
        tree_dir.mkdir()
        with tarfile.open(str(archive_path), "r:") as archive:
            _extract_tar(archive, tree_dir)
        code, out, err = _run(_build_sdist_argv(outdir, tree_dir), cwd=outdir)
        if code != EXIT_PASS:
            raise EnvironmentMissing("构建 sdist 失败：%s" % ((err or out).strip().splitlines()[-1:]))
        archives = sorted(Path(outdir).glob("*.tar.gz"))
        if not archives:
            raise EnvironmentMissing("构建声称成功但没有产出 .tar.gz")
        return Path(outdir), archives[0].name
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)


def build_asset(dest_dir: Path, tag: str, root: Path) -> int:
    """从 **tag 树** 建出要上传的源码包，落到 `dest_dir`（同名副本即上传件）。

    为什么走这个模式而不是手敲 `python -m build`：上传件必须与发布门 C09/O07 验的是**同一条
    构建路径**（`git archive <tag>` → 导出的受控树 → `build --sdist`）。手敲时若漏了导出一层，
    工作树里的 `*.egg-info` 就会混进去，而门验的和你上传的就不是同一个东西。

    幂等：归档经 `_normalize_sdist_archive` 归一（固定 mtime / uid / gid / uname / gzip 头时间），
    同一 tag 重跑得到**同一组字节**，sha256 因此可复算。这是本机实测出来的要求——
    未归一时同 tag 连跑两次 sha256 不同（发布门 C11 把这条钉住）。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ref = "%s^{commit}" % tag if tag else "HEAD"
    code, _out, err = _run(["git", "rev-parse", "--verify", ref], cwd=root)
    if code != EXIT_PASS:
        raise ReleaseNotAchieved("本地不存在 tag %r：%s" % (tag, err.strip()))
    members = _build_sdist_members(root, ref)
    outdir, name = _raw_sdist_archive(root, ref)
    try:
        produced = outdir / name
        target = dest_dir / name
        _normalize_sdist_archive(produced, target)
        digest = _sha256(target)
        print("已构建发布附件：%s" % target)
        print("  sha256  %s" % digest)
        print("  字节数  %d" % target.stat().st_size)
        print("  来源    git archive %s → sdist（与发布门 C09/O07 同一条路径）" % ref)
        print("  成员数  %d" % len(members))
        return EXIT_PASS
    finally:
        shutil.rmtree(str(outdir), ignore_errors=True)


def record_assets(local_dir: Path, tag: str, slug: str, root: Path) -> int:
    """把本地附件副本的 sha256 记进 `plan/release-assets.json`（K2 原子写）。

    这是**唯一的写盘点**。顺序是 **tag 之前**入库（登记 → 提交 → 打 tag）：
    登记文件不在 sdist 内，所以它进树不改变包字节——而 tag 树自带登记，
    O05/O06/O07 三条"发布物自证"检查才可能成立（v0.0.1 时是反的，实测 4 FAIL）。
    zip/tar 内仍不写自身 sha256（K17 自指必过期）。
    """
    local_dir = Path(local_dir)
    if not local_dir.is_dir():
        print("附件目录不存在：%s" % local_dir, file=sys.stderr)
        return EXIT_USAGE_ERROR
    files = sorted(path for path in local_dir.iterdir() if path.is_file() and not path.name.endswith(".sha256"))
    if not files:
        print("附件目录为空：%s" % local_dir, file=sys.stderr)
        return EXIT_USAGE_ERROR
    assets = [
        {"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size} for path in files
    ]
    payload = {
        "tag": tag,
        "repository": slug,
        "recorded_at": Context(root).now_utc(),
        "note": (
            "发布附件登记（**tag 之前**入库；本文件不在 sdist 内，故不改变包字节）。"
            "zip/tar 内不写自身 sha256：自指必过期（K17）。"
            "本文件由 scripts/check_release.py --record-assets 生成，经 serialize.write_atomic 落盘（K2）。"
        ),
        "assets": assets,
    }
    target = Path(root) / ASSET_LEDGER_RELPATH
    serialize.write_json_atomic(target, payload)
    print("已写入 %s（%d 个附件）" % (target, len(assets)))
    for asset in assets:
        print("  %s  %s  %d" % (asset["sha256"], asset["name"], asset["size"]))
    return EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_release.py",
        description="发布终态自检门（离线 / --online / --mutation），刻意不进 CI。",
    )
    parser.add_argument("--online", action="store_true", help="额外检查远端发布状态（需要已登录的 gh）")
    parser.add_argument("--mutation", action="store_true", help="门自身变异验证（检查项数 == 变异组数）")
    parser.add_argument("--build-asset", metavar="DIR", default=None, help="从 tag 树建出要上传的源码包并落到 DIR")
    parser.add_argument("--record-assets", metavar="DIR", default=None, help="把本地附件副本的 sha256 记进登记文件")
    parser.add_argument("--tag", default="", help="发布 tag（--online / --build-asset / --record-assets 必填）")
    parser.add_argument("--slug", default=CANONICAL_SLUG, help="仓库坐标（默认 %(default)s）")
    parser.add_argument("--root", default=str(REPO_ROOT), help="仓库根（默认本脚本所在仓库）")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # K8：入口编码守卫（失败不阻断）
    except (AttributeError, ValueError, OSError):
        pass
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    root = Path(args.root)
    if args.build_asset:
        if not args.tag:
            print("--build-asset 需要 --tag", file=sys.stderr)
            return EXIT_USAGE_ERROR
        try:
            return build_asset(Path(args.build_asset), args.tag, root)
        except ReleaseNotAchieved as exc:
            print("发布未达成：%s" % exc, file=sys.stderr)
            return EXIT_FAIL
        except EnvironmentMissing as exc:
            print("环境缺失：%s" % exc, file=sys.stderr)
            return EXIT_MISSING_ENV
    if args.record_assets:
        if not args.tag:
            print("--record-assets 需要 --tag", file=sys.stderr)
            return EXIT_USAGE_ERROR
        try:
            return record_assets(Path(args.record_assets), args.tag, args.slug, root)
        except EnvironmentMissing as exc:
            print("环境缺失：%s" % exc, file=sys.stderr)
            return EXIT_MISSING_ENV
    if args.mutation:
        try:
            return run_mutation()
        except EnvironmentMissing as exc:
            print("环境缺失：%s" % exc, file=sys.stderr)
            return EXIT_MISSING_ENV
    if args.online and not args.tag:
        print("--online 需要 --tag", file=sys.stderr)
        return EXIT_USAGE_ERROR
    ctx = Context(root, tag=args.tag, slug=args.slug)
    checks = list(OFFLINE_CHECKS) + (list(ONLINE_CHECKS) if args.online else [])
    print("发布门（%s）：%d 条检查\n" % ("离线 + 在线" if args.online else "离线", len(checks)))
    try:
        failures = run_checks(ctx, checks)
    except EnvironmentMissing as exc:
        print("环境缺失：%s" % exc, file=sys.stderr)
        return EXIT_MISSING_ENV
    if failures:
        print("\n发布门未通过：%s" % ", ".join(failures))
        return EXIT_FAIL
    print("\n发布门通过：%d 条检查无 FAIL。" % len(checks))
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
