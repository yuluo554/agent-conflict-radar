"""配置加载：数值口径的唯一读取点（K3 / K6）。

两条硬纪律：

1. **唯一权威**：`config/radar.toml` 是全项目唯一的数值定义处。本模块是全项目唯一读它的地方
   （其他模块一律经 `Config.get` 取值）。代码里**零内联默认值**——缺失、未知、类型不符一律报错，
   **绝不回落默认值**（回落等于出现第二份真相，阈值漂移从此无告警）。
2. **底线解释器能力缺口显式标记**：项目底线是 Python 3.8，没有 `tomllib`（3.11+ 才有）。
   处置不是"引运行时依赖"也不是"解析不了就跳过"，而是**自写受限子集解析器** + 遇到超集形态
   显式报 `TomlUnsupportedError`（带行号）。静默跳过会让配置里的数值凭空消失（K6）。
"""

import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import ConfigError, TomlUnsupportedError
from .paths import find_repo_root, normalize_path

#: 配置文件相对仓库根的路径（唯一权威；改名必须同步 plan/07 K3 与 README）。
CONFIG_RELATIVE_PATH = os.path.join("config", "radar.toml")

#: 环境变量覆盖位（显式 > 环境变量 > 仓库根默认）。
ENV_CONFIG_PATH = "RADAR_CONFIG"

#: 键空间版本；解析器比对它，不认识的版本显式报错，不按最宽松规则猜测。
SCHEMA_VERSION = 1


def _schema() -> Dict[str, Dict[str, type]]:
    """键空间模式（冻结契约）。新增键 = 改本模式 + 改 config/radar.toml + 改消费方，三处同步。"""
    return {
        "schema": {"version": int},
        "window": {"active_minutes": int, "scan_days": int},
        "scan": {"max_line_bytes": int},
        "symbol": {"adjacent_tolerance": int, "min_overlap_lines": int},
        "severity": {
            "same_symbol": int,
            "same_file_diff_symbol": int,
            "adjacent_lines": int,
            "file_only": int,
        },
        "git": {"timeout_seconds": int, "merge_tree_enabled": bool},
        "report": {"max_evidence_items": int, "notify": bool},
        "paths": {"claude_root": str, "codex_root": str},
    }


# --------------------------------------------------------------------------------------
# 受限 TOML 子集解析器
# --------------------------------------------------------------------------------------

_SUPPORTED_HINT = (
    "本解析器支持：注释、[section]、key = 整数/浮点/布尔/带引号字符串/标量数组。"
    "不支持的形态一律显式报错（K6），不静默跳过。"
)


def _strip_comment(line: str) -> str:
    """去掉行尾注释；引号内的 `#` 不算注释。"""
    quote = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "#":
            return line[:index]
    return line


def _split_key_value(text: str, line_no: int) -> Tuple[str, str]:
    """按第一个引号外的 `=` 切分键值。"""
    quote = None
    for index, char in enumerate(text):
        if quote is not None:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "=":
            return text[:index], text[index + 1:]
    raise TomlUnsupportedError("第 %d 行：不是合法的 `键 = 值` 形式：%r。%s" % (line_no, text, _SUPPORTED_HINT))


def _parse_scalar(raw: str, line_no: int) -> Any:
    text = raw.strip()
    if text == "":
        raise TomlUnsupportedError("第 %d 行：`=` 后面没有值。%s" % (line_no, _SUPPORTED_HINT))
    if text.startswith('"""') or text.startswith("'''"):
        raise TomlUnsupportedError("第 %d 行：不支持多行字符串（\"\"\" / '''）。%s" % (line_no, _SUPPORTED_HINT))
    if text.startswith("{"):
        raise TomlUnsupportedError("第 %d 行：不支持内联表 `{...}`。%s" % (line_no, _SUPPORTED_HINT))
    if text[0] in ("'", '"'):
        quote = text[0]
        if len(text) < 2 or not text.endswith(quote):
            raise TomlUnsupportedError("第 %d 行：字符串引号未闭合：%r" % (line_no, text))
        body = text[1:-1]
        if quote == '"':
            body = body.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n").replace("\\t", "\t")
        return body
    if text == "true":
        return True
    if text == "false":
        return False
    if text.startswith("["):
        return _parse_array(text, line_no)
    # 裸值：TOML 要求字符串必须带引号，裸词在这里一律显式报错（可能是引号漏写）。
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    raise TomlUnsupportedError(
        "第 %d 行：无法识别的值 %r（裸值必须加引号）。%s" % (line_no, text, _SUPPORTED_HINT)
    )


def _parse_array(text: str, line_no: int) -> list:
    """解析标量数组。嵌套数组允许，内联表拒绝。"""
    if not text.endswith("]"):
        raise TomlUnsupportedError("第 %d 行：数组未闭合（缺少 `]`）：%r" % (line_no, text))
    inner = text[1:-1].strip()
    if inner == "":
        return []
    items = []
    depth = 0
    quote = None
    current = []
    for char in inner:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if char == "[":
            depth += 1
            current.append(char)
            continue
        if char == "]":
            depth -= 1
            current.append(char)
            continue
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    if quote is not None:
        raise TomlUnsupportedError("第 %d 行：数组中字符串引号未闭合：%r" % (line_no, text))
    tail = "".join(current)
    if tail.strip():
        items.append(tail)
    # 尾随逗号（`[1, 2,]`）合法：最后一个逗号后为空即尾逗号，直接忽略。
    # 空元素（`[1,,2]`）不在这里拦——它会作为空标量送进 `_parse_scalar` 并显式报错。
    return [_parse_scalar(item, line_no) for item in items]


def parse_toml_subset(text: str, source: str = "<memory>") -> Dict[str, Any]:
    """把受限 TOML 子集解析成嵌套 dict。遇到不支持的形态抛 `TomlUnsupportedError`。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    root: Dict[str, Any] = {}
    current = root
    current_section = ""
    lines = text.split("\n")
    index = 0
    try:
        while index < len(lines):
            line_no = index + 1
            raw = lines[index]
            index += 1
            line = _strip_comment(raw).strip()
            if line == "":
                continue
            if line.startswith("[["):
                raise TomlUnsupportedError(
                    "第 %d 行：不支持表数组 `[[...]]`。%s" % (line_no, _SUPPORTED_HINT)
                )
            if line.startswith("["):
                if not line.endswith("]"):
                    raise TomlUnsupportedError("第 %d 行：节名未闭合：%r" % (line_no, raw))
                section = line[1:-1].strip()
                if section == "":
                    raise TomlUnsupportedError("第 %d 行：节名为空" % (line_no,))
                parts = [part.strip() for part in section.split(".")]
                if any(part == "" for part in parts):
                    raise TomlUnsupportedError("第 %d 行：节名含空段：%r" % (line_no, section))
                node = root
                for part in parts:
                    existing = node.get(part)
                    if existing is None:
                        node[part] = {}
                        existing = node[part]
                    if not isinstance(existing, dict):
                        raise ConfigError("%s 第 %d 行：节名 %r 与已有键冲突" % (source, line_no, section))
                    node = existing
                current = node
                current_section = section
                continue

            # 可能是跨行数组：先看 `=` 之后是否有未闭合的 `[`
            key_part, value_part = _split_key_value(line, line_no)
            key = key_part.strip()
            value_text = value_part.strip()
            while value_text.count("[") > value_text.count("]") and index < len(lines):
                value_text = value_text + " " + _strip_comment(lines[index]).strip()
                index += 1
            if key == "":
                raise TomlUnsupportedError("第 %d 行：键名为空" % (line_no,))
            if "." in key:
                raise TomlUnsupportedError(
                    "第 %d 行：不支持点号键 %r（请用 [section] 分组）。%s" % (line_no, key, _SUPPORTED_HINT)
                )
            if key in current:
                raise ConfigError("%s 第 %d 行：键 %r 重复定义（节 %r）" % (source, line_no, key, current_section))
            current[key] = _parse_scalar(value_text, line_no)
    except TomlUnsupportedError as exc:
        # 统一补上来源：只说"第 N 行"而不知道是哪个文件，用户无法定位。
        if source and source not in str(exc):
            raise TomlUnsupportedError("%s %s" % (source, exc))
        raise
    return root


# --------------------------------------------------------------------------------------
# 配置对象
# --------------------------------------------------------------------------------------


class Config:
    """只读配置视图。构造即完成校验；不提供任何"取不到就用默认值"的接口。"""

    def __init__(self, data: Mapping[str, Any], source_path: Path) -> None:
        self._data = data
        self.source_path = Path(source_path)

    def section(self, name: str) -> Mapping[str, Any]:
        try:
            return self._data[name]
        except KeyError:
            raise ConfigError(
                "配置节 %r 不存在（来源：%s）：请检查 %s 是否完整。"
                % (name, self.source_path, CONFIG_RELATIVE_PATH)
            )

    def get(self, section: str, key: str) -> Any:
        node = self.section(section)
        if key not in node:
            raise ConfigError("配置项 %s.%s 不存在（来源：%s）" % (section, key, self.source_path))
        return node[key]

    def as_dict(self) -> Dict[str, Any]:
        """深拷贝成普通 dict（可 JSON 序列化）。用于 `radar config` 的可核验输出。"""
        return {name: dict(self._data[name]) for name in sorted(self._data)}

    def with_override(self, section: str, key: str, value: Any) -> "Config":
        """返回一个**只读覆盖**后的新视图：原对象不变、不写盘、不改配置文件。

        为什么需要它：CLI 的 `--window` 要覆盖 `window.scan_days`。把 CLI 参数直接塞进
        "唯一权威文件"会毁掉 K3（数值就有了第二处来源）；在下游再读一次参数则会让
        "生效值从哪来"变得说不清。所以覆盖**只作用于本次调用的内存视图**，并复用同一套
        校验（缺键 / 未知键 / 类型不符一律报错），下游仍然只有一个取值入口 `get()`。
        """
        schema = _schema()
        if section not in schema:
            raise ConfigError("不能覆盖未知配置节 %r（可选：%s）" % (section, sorted(schema)))
        if key not in schema[section]:
            raise ConfigError("不能覆盖未知配置项 %s.%s（可选：%s）" % (section, key, sorted(schema[section])))
        if value is None:
            raise ConfigError("覆盖值不能为空：%s.%s（调用方应在本处不传覆盖，而不是传 None）" % (section, key))
        checked = _check_type(section, key, value, schema[section][key], self.source_path)
        data = {name: dict(self._data[name]) for name in self._data}
        data[section][key] = checked
        frozen = {name: MappingProxyType(data[name]) for name in data}
        return Config(MappingProxyType(frozen), self.source_path)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Config(source_path=%r, sections=%r)" % (str(self.source_path), sorted(self._data))


def _validate(raw: Mapping[str, Any], source_path: Path) -> Config:
    schema = _schema()
    unknown_sections = [name for name in raw if name not in schema]
    if unknown_sections:
        raise ConfigError(
            "配置含未知节 %s（来源：%s）：未知键绝不忽略——那会让数值从「唯一权威」里漏出去。"
            % (sorted(unknown_sections), source_path)
        )
    frozen: Dict[str, Mapping[str, Any]] = {}
    for section, keys in schema.items():
        if section not in raw:
            raise ConfigError("配置缺少节 [%s]（来源：%s）" % (section, source_path))
        node = raw[section]
        if not isinstance(node, dict):
            raise ConfigError("配置节 [%s] 不是键值组（来源：%s）" % (section, source_path))
        unknown_keys = [key for key in node if key not in keys]
        if unknown_keys:
            raise ConfigError(
                "配置节 [%s] 含未知键 %s（来源：%s）" % (section, sorted(unknown_keys), source_path)
            )
        values: Dict[str, Any] = {}
        for key, expected in keys.items():
            if key not in node:
                raise ConfigError(
                    "配置缺少 %s.%s（来源：%s）：缺失即报错，绝不回落默认值（K3）。"
                    % (section, key, source_path)
                )
            value = node[key]
            values[key] = _check_type(section, key, value, expected, source_path)
        frozen[section] = MappingProxyType(values)
    version = frozen["schema"]["version"]
    if version != SCHEMA_VERSION:
        raise ConfigError(
            "配置键空间版本 %r 不被支持（本程序支持 %r，来源：%s）：不按最宽松规则猜测。"
            % (version, SCHEMA_VERSION, source_path)
        )
    return Config(MappingProxyType(frozen), source_path)


def _check_type(section: str, key: str, value: Any, expected: type, source_path: Path) -> Any:
    if expected is bool:
        if not isinstance(value, bool):
            raise ConfigError("配置项 %s.%s 应为布尔（来源：%s）" % (section, key, source_path))
        return value
    if expected is int:
        # bool 是 int 的子类，必须排除——否则 true 会被当成 1 静默通过。
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(
                "配置项 %s.%s 应为整数（来源：%s，实际 %r）" % (section, key, source_path, value)
            )
        return value
    if expected is str:
        if not isinstance(value, str):
            raise ConfigError("配置项 %s.%s 应为字符串（来源：%s）" % (section, key, source_path))
        return value
    raise ConfigError("内部错误：%s.%s 的模式类型不受支持" % (section, key))  # pragma: no cover


def resolve_config_path(explicit: Optional[str] = None, start: Optional[Path] = None) -> Path:
    """解析配置路径：显式参数 > 环境变量 > 仓库根下 `config/radar.toml`。

    找不到就报错并列出探测过的位置；**不回落 CWD**（回落会把"配置不在"伪装成"配置在别处"）。
    """
    tried = []
    if explicit:
        candidate = normalize_path(explicit)
        tried.append(str(candidate))
        if candidate.is_file():
            return candidate
        raise ConfigError("--config 指定的文件不存在：%s" % candidate)
    env_value = os.environ.get(ENV_CONFIG_PATH)
    if env_value:
        candidate = normalize_path(env_value)
        tried.append("%s=%s" % (ENV_CONFIG_PATH, candidate))
        if candidate.is_file():
            return candidate
        raise ConfigError("环境变量 %s 指向的文件不存在：%s" % (ENV_CONFIG_PATH, candidate))
    root = find_repo_root(start)
    if root is not None:
        candidate = root / CONFIG_RELATIVE_PATH
        tried.append(str(candidate))
        if candidate.is_file():
            return candidate
    raise ConfigError(
        "找不到配置文件。已探测：%s。请用 --config 显式指定，或设置 %s。"
        % (tried or ["仓库根下 " + CONFIG_RELATIVE_PATH], ENV_CONFIG_PATH)
    )


def load(path: Optional[str] = None, start: Optional[Path] = None) -> Config:
    """加载并校验配置。任何异常都落在 `ConfigError`（exit 3）语义内。"""
    source_path = resolve_config_path(path, start)
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("配置文件不可读：%s（%s）" % (source_path, exc))
    raw = parse_toml_subset(text, source=str(source_path))
    return _validate(raw, source_path)
