"""git 只读封装（K4 / K8）。

三层保护，缺一层都不算"只读"：

1. **子命令白名单**：只允许枚举出的只读形态（`worktree list` / `status` / `diff` / `log` /
   `rev-parse` / `merge-tree` / `cat-file` / `ls-tree` / `rev-list` / `show` / `symbolic-ref` /
   `ls-files` / `for-each-ref` / `hash-object`）。任何 merge / rebase / reset / checkout /
   commit / apply / stash / worktree add|remove … 一律抛 `ReadOnlyViolation`。
2. **禁写标志**：`-w` / `--write` / `--hard` / `--force` / `--prune` / `--amend` 一律拒绝
   （**例外**：`merge-tree --write-tree` 是题面指定的无副作用试合并形态，显式放行并记录其边界）。
3. **可选锁关闭**：子进程环境置 `GIT_OPTIONAL_LOCKS=0`，防止 `status` 之类刷新索引而**写 .git**。

`--write-tree` 的如实边界（不得声称"零任何写入"）：它会在对象库写入临时 tree/blob 对象，
但**不改索引、不改工作区、不建分支**。这条边界写进 README 与报告。

编码（K8）：子进程显式 `encoding="utf-8"`。`py -X utf8` 只改我们自己进程的 stdio，
**改不了子进程的解码通路**——子进程解码走 locale，不显式指定就会在 CI（cp1252）上炸。
"""

import os
import shutil
import subprocess
from typing import List, NamedTuple, Optional, Sequence

from .errors import EnvironmentError_, ReadOnlyViolation

#: `merge-tree --write-tree` 的输出形态（M3 实测，git 2.54.0.windows.1，见 `data/README.md` §6.1）：
#: * exit 0 → stdout **只有一行** tree sha（自动合并成功，没有冲突块）；
#: * exit 1 → 第一行 tree sha，随后是 `<mode> <sha> <stage>\t<path>` 三元组行与
#:   `CONFLICT (...): Merge conflict in <path>` / `CONFLICT (modify/delete): <path> ...` 行；
#: * exit 128 → 环境问题（无共同祖先 / 非 git 目录），只给 `fatal:` 文案。
#: 路径既可能出现在三元组的 **tab 之后**，也可能出现在 `CONFLICT` 文案里——两条都收，
#: 只认一条会漏（`modify/delete` 形态**没有**三元组行）。
_MERGE_TREE_CONFLICT_PREFIX = "CONFLICT ("
_MERGE_TREE_MERGE_CONFLICT_MARK = "Merge conflict in "
_MERGE_TREE_STAGE_FIELD = "\t"
#: 三元组的 stage 编号（1=base / 2=ours / 3=theirs），只出现这几个值。
_MERGE_TREE_CONFLICT_STAGES = frozenset({"1", "2", "3"})

#: 允许的首个参数（子命令）。
READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "worktree",
        "status",
        "diff",
        "log",
        "rev-parse",
        "merge-tree",
        "cat-file",
        "ls-tree",
        "rev-list",
        "show",
        "symbolic-ref",
        "ls-files",
        "for-each-ref",
        "hash-object",
        "version",
        "--version",
        "--no-pager",
    }
)

#: 会被误用成写操作的标志：一律拒绝（例外见 `_ALLOWED_WRITE_FLAGS`）。
MUTATING_FLAGS = frozenset({"-w", "--write", "--hard", "--force", "--prune", "--amend"})

#: 显式放行的"名字里有 write 但语义只读"的形态。
_ALLOWED_WRITE_FLAGS = frozenset({"--write-tree"})

#: `worktree` 只允许 `list` 子形态（`add` / `remove` / `prune` / `lock` 都会改磁盘）。
_WORKTREE_ALLOWED = frozenset({"list"})


class GitResult(NamedTuple):
    args: List[str]
    returncode: int
    stdout: str
    stderr: str


def git_available() -> bool:
    """git 是否可用（只做存在性探测，不执行任何 git 命令）。"""
    return shutil.which("git") is not None


def ensure_git_available() -> str:
    """返回 git 可执行文件路径；不可用则抛 `EnvironmentError_`（exit 3）。"""
    path = shutil.which("git")
    if path is None:
        raise EnvironmentError_(
            "找不到 git 可执行文件：本工具的多项能力（worktree 枚举、无副作用试合并、未提交 diff）"
            "依赖 git。请安装 git 并确保它在 PATH 上。"
        )
    return path


def _assert_read_only(args: Sequence[str]) -> None:
    if not args:
        raise ReadOnlyViolation("空的 git 参数：拒绝执行（只读纪律要求显式声明子命令）")
    head = args[0]
    if head not in READ_ONLY_SUBCOMMANDS:
        raise ReadOnlyViolation(
            "拒绝执行非只读 git 子命令 %r（K4）：本工具绝不写 git 索引、不执行 merge/rebase、"
            "不修改工作区。" % head
        )
    if head == "worktree":
        if len(args) < 2 or args[1] not in _WORKTREE_ALLOWED:
            raise ReadOnlyViolation(
                "`git worktree` 只允许 `list`（add/remove/prune/lock 都会改磁盘）：收到 %r" % list(args)
            )
    for token in args:
        if token in _ALLOWED_WRITE_FLAGS:
            continue
        if token in MUTATING_FLAGS:
            raise ReadOnlyViolation("拒绝执行含写操作标志 %r 的 git 命令：%r" % (token, list(args)))


def _git_env() -> dict:
    env = dict(os.environ)
    # 关掉可选锁：`git status` 一类命令默认可能刷新并写索引，这就破坏了"不改工作区/索引"。
    env["GIT_OPTIONAL_LOCKS"] = "0"
    # 永不提示凭据、永不分页（分页器会把输出挂住）。
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    return env


def run_readonly(
    args: Sequence[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> GitResult:
    """以只读方式执行一条 git 命令。

    * 白名单不通过 → `ReadOnlyViolation`（在**起进程之前**拒绝，零副作用）；
    * git 不可用 → `EnvironmentError_`（exit 3）；
    * 超时 → `EnvironmentError_`（exit 3）——超时绝不降级成"无冲突"。
    """
    ordered = list(args)
    _assert_read_only(ordered)
    binary = ensure_git_available()
    command = [binary, "--no-pager"] + ordered
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=_git_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise EnvironmentError_(
            "git 命令超时（%s 秒）：%r。超时不代表没有冲突，请调大 config 的 git.timeout_seconds "
            "或检查仓库是否被锁。" % (timeout, ordered)
        )
    except OSError as exc:
        raise EnvironmentError_("git 命令无法执行：%r（%s）" % (ordered, exc))
    return GitResult(
        args=ordered,
        returncode=completed.returncode,
        # 显式 utf-8：子进程解码不继承 `py -X utf8`（K8）。
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )


# --------------------------------------------------------------------------------------
# 无副作用试合并（M3 区块级；`plan/04` M3）
# --------------------------------------------------------------------------------------

#: 三元组行的字段数（`<mode> <sha> <stage>`）。
_MERGE_TREE_TRIPLET_FIELDS = ("mode", "sha", "stage")


class MergeTreeResult(NamedTuple):
    """`git merge-tree --write-tree <base> <other>` 的解析结果。

    `tree` 是 stdout 首行的 tree sha（exit 0/1 时有；128 时为空串）。
    `conflict_paths` 是**有序去重**的冲突路径（既从三元组行取，也从 `CONFLICT` 文案取）。
    `returncode` 原样保留：判据在调用方（detect），本层只做"跑 + 解析"。
    """

    base: str
    other: str
    returncode: int
    tree: str
    conflict_paths: tuple
    stdout: str
    stderr: str

    def diagnostic(self) -> str:
        """失败时给人看的片段（stdout 优先，128 的 `fatal:` 可能在任一通道上）。"""
        text = self.stdout.strip() or self.stderr.strip()
        return text.split("\n")[0].strip() if text else ""


def parse_merge_tree_conflicts(stdout: str) -> List[str]:
    """从 `merge-tree --write-tree` 的 stdout 里取冲突路径（有序去重）。

    两条来源都要收（M3 实测）：
    * `100644 <sha> 2\\t<path>` 三元组行的 **tab 之后**（content 冲突的形态）；
    * `CONFLICT (modify/delete): <path> deleted in ...` 这类文案（**没有**三元组行）。

    只收"确实冲突"的行：exit 0 时 stdout 只有一行 tree sha，两条来源都不会命中。
    """
    found: List[str] = []
    for raw in stdout.replace("\r\n", "\n").split("\n"):
        if not raw:
            continue
        candidate = None
        if raw.startswith(_MERGE_TREE_CONFLICT_PREFIX):
            if _MERGE_TREE_MERGE_CONFLICT_MARK in raw:
                candidate = raw.split(_MERGE_TREE_MERGE_CONFLICT_MARK, 1)[1].strip()
            else:
                _head, _sep, tail = raw.partition("): ")
                candidate = tail.split(" ")[0].strip().strip('"')
        elif _MERGE_TREE_STAGE_FIELD in raw:
            prefix, _sep, tail = raw.partition(_MERGE_TREE_STAGE_FIELD)
            fields = prefix.split()
            if len(fields) == len(_MERGE_TREE_TRIPLET_FIELDS) and fields[-1] in _MERGE_TREE_CONFLICT_STAGES:
                candidate = tail.strip()
        if candidate and candidate not in found:
            found.append(candidate)
    return found


def merge_tree(
    repo: str,
    base: str,
    other: str,
    timeout: Optional[float] = None,
) -> MergeTreeResult:
    """只读试合并：`git merge-tree --write-tree <base> <other>`（K4）。

    只读边界（**如实披露，不得声称"零任何写入"**）：`--write-tree` 会在**对象库**写入临时
    tree/blob 对象；它**不改索引、不改工作区、不建分支**，也不动 HEAD。这条边界写进 README 与报告。

    退出码 0 / 1 / 128 都是**正常返回**（判据在调用方）；只有"git 不可用"与"超时"会抛
    `EnvironmentError_`——超时**绝不**降级成"无冲突"，由调用方决定降级形态。
    """
    result = run_readonly(["merge-tree", "--write-tree", base, other], cwd=repo, timeout=timeout)
    lines = result.stdout.split("\n")
    tree = lines[0].strip() if lines and lines[0].strip() else ""
    return MergeTreeResult(
        base=base,
        other=other,
        returncode=result.returncode,
        tree=tree,
        conflict_paths=tuple(parse_merge_tree_conflicts(result.stdout)),
        stdout=result.stdout,
        stderr=result.stderr,
    )


def git_common_dir(repo: str, timeout: Optional[float] = None) -> Optional[str]:
    """返回 `git rev-parse --git-common-dir`（同一仓库的多个 worktree 共享同一个 common dir）。

    用途：两个 workspace 可能是**同一个仓库的两个 worktree**——那时 `merge-tree` 在哪个
    worktree 里跑都一样（对象库是共享的）。取不到就返回 `None`（调用方按"不可判定"降级）。
    """
    result = run_readonly(["rev-parse", "--git-common-dir"], cwd=repo, timeout=timeout)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    absolute = text if os.path.isabs(text) else os.path.join(repo, text)
    return os.path.normcase(os.path.normpath(absolute))
