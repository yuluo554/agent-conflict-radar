"""数值口径单点（K3）+ 底线解释器能力缺口显式标记（K6）。

两条被反复验证过的失败形态，本文件各配一条断言：

* **回落默认值**：代码里藏一份默认阈值 → 配置改了但行为不变，且永不报错。
  这里用"改配置文件 → 取值必须跟着变"来证伪（真读，而不是只断言"文件存在"）。
* **静默跳过**：解析器遇到不认识的 TOML 形态就跳过该行 → 数值凭空消失。
  这里逐形态断言"必须抛错"，包括表数组 / 内联表 / 多行字符串 / 点号键 / 裸值。
"""

import pytest

from agent_conflict_radar import config as config_module
from agent_conflict_radar.config import Config, ConfigError, TomlUnsupportedError, load, parse_toml_subset


def test_real_config_loads(config_path):
    cfg = load(str(config_path))
    assert isinstance(cfg, Config)
    assert cfg.get("schema", "version") == config_module.SCHEMA_VERSION
    assert cfg.get("window", "active_minutes") > 0
    assert cfg.get("git", "merge_tree_enabled") in (True, False)


def test_config_exposes_exactly_the_frozen_key_space(config_path):
    """键空间必须与 `_schema()` 完全一致（多一个键 = 出现了未被消费的真相）。"""
    cfg = load(str(config_path))
    actual = {section: sorted(values) for section, values in cfg.as_dict().items()}
    expected = {section: sorted(keys) for section, keys in config_module._schema().items()}  # noqa: SLF001
    assert actual == expected


@pytest.mark.parametrize(
    "section,key",
    [("window", "active_minutes"), ("window", "scan_days"), ("symbol", "adjacent_tolerance"), ("severity", "same_symbol")],
)
def test_values_are_really_read_from_the_file(make_config, section, key, config_path):
    """真读证明：改文件里的数值 → `Config.get` 必须返回新值。

    判据 = "把代码里的默认值当真相的实现在这里会红吗？"——会，因为它返回的是旧值。
    """
    original = load(str(config_path)).get(section, key)
    marker = "%s = %d" % (key, original)
    replacement = "%s = %d" % (key, original + 1)

    def mutate(text):
        assert marker in text, "测试自身失配：%r 未出现在配置里（锚点漂了，测试会静默失效）" % marker
        return text.replace(marker, replacement)

    path = make_config(mutate=mutate)
    assert load(str(path)).get(section, key) == original + 1


# --------------------------------------------------------------------------------------
# 缺键 / 未知键 / 类型不符 / 版本不符 → 一律报错
# --------------------------------------------------------------------------------------


def test_missing_key_is_rejected_not_defaulted(make_config):
    path = make_config(drop_keys=["symbol.min_overlap_lines"])
    with pytest.raises(ConfigError) as excinfo:
        load(str(path))
    assert "min_overlap_lines" in str(excinfo.value)


def test_removed_section_is_rejected(make_config):
    """整节缺失也必须报错（不是只有缺单个键才报）。"""

    def mutate(text):
        lines = []
        skipping = False
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                skipping = stripped == "[symbol]"
            if not skipping:
                lines.append(line)
        result = "\n".join(lines)
        assert "[symbol]" not in result, "测试自身失配：整节未删除，测试会静默失效"
        return result

    path = make_config(mutate=mutate)
    with pytest.raises(ConfigError) as excinfo:
        load(str(path))
    assert "symbol" in str(excinfo.value)


def test_unknown_key_is_rejected(make_config):
    path = make_config(extra_lines=["", "[symbol]", "unknown_threshold = 7"])
    with pytest.raises(ConfigError) as excinfo:
        load(str(path))
    assert "unknown_threshold" in str(excinfo.value)


def test_unknown_section_is_rejected(make_config):
    path = make_config(extra_lines=["", "[not_a_section]", "value = 1"])
    with pytest.raises(ConfigError) as excinfo:
        load(str(path))
    assert "not_a_section" in str(excinfo.value)


def test_boolean_is_not_accepted_as_integer(make_config):
    """`true` 不能被当成 1 静默通过（Python 里 bool 是 int 的子类，必须显式排除）。"""

    def mutate(text):
        assert "active_minutes = 30" in text
        return text.replace("active_minutes = 30", "active_minutes = true")

    path = make_config(mutate=mutate)
    with pytest.raises(ConfigError) as excinfo:
        load(str(path))
    assert "整数" in str(excinfo.value)


def test_type_mismatch_on_boolean_key_is_rejected(make_config):
    def mutate(text):
        assert "notify = false" in text
        return text.replace("notify = false", "notify = 0")

    path = make_config(mutate=mutate)
    with pytest.raises(ConfigError):
        load(str(path))


def test_unsupported_schema_version_is_rejected(make_config):
    def mutate(text):
        return text.replace("version = 1", "version = 99")

    path = make_config(mutate=mutate)
    with pytest.raises(ConfigError) as excinfo:
        load(str(path))
    assert "99" in str(excinfo.value)


def test_duplicate_key_is_rejected():
    with pytest.raises(ConfigError) as excinfo:
        parse_toml_subset("[window]\nactive_minutes = 1\nactive_minutes = 2\n")
    assert "重复" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# K6：TOML 超集形态必须显式报错（不静默跳过）
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet,expected_hint",
    [
        ("[[scenario]]\nid = 1\n", "表数组"),
        ("[window]\nvalue = {a = 1}\n", "内联表"),
        ('[window]\ntext = """多行"""\n', "多行字符串"),
        ("[window]\na.b = 1\n", "点号键"),
        ("[window]\nvalue = bareword\n", "裸值"),
        ("[window]\nmissing_equals\n", "不是合法的"),
        ("[window\nvalue = 1\n", "未闭合"),
        ("[window]\nvalue = 1\n", "节"),  # 正常形态走另一条断言（见下）
    ],
)
def test_toml_superset_forms_are_reported(snippet, expected_hint):
    """逐形态断言"必须抛错，不能在信息里含糊"。

    ⚠️ 最后一项是**阴性对照**：正常形态必须**不**抛错——否则本测试变成"任何输入都报错"，
    那就证明不了"超集形态被识别"，只证明了解析器坏了。
    """
    if expected_hint == "节":
        assert parse_toml_subset(snippet) == {"window": {"value": 1}}
        return
    with pytest.raises(TomlUnsupportedError) as excinfo:
        parse_toml_subset(snippet, source="<probe>")
    assert expected_hint in str(excinfo.value), "报错信息应点名形态与位置：%s" % excinfo.value


def test_toml_errors_carry_line_numbers():
    with pytest.raises(TomlUnsupportedError) as excinfo:
        parse_toml_subset("# 注释\n\n[window]\nvalue = {a = 1}\n", source="<probe>")
    assert "第 4 行" in str(excinfo.value)
    assert "<probe>" in str(excinfo.value)


def test_supported_subset_round_trip():
    text = (
        "# 注释\n"
        "[section]\n"
        "answer = 42\n"
        "ratio = 0.5\n"
        "enabled = true\n"
        'name = "radar"\n'
        "items = [1, 2, 3]\n"
        "empty = []\n"
        'quoted = "带 # 号的字符串"\n'
    )
    parsed = parse_toml_subset(text)
    assert parsed == {
        "section": {
            "answer": 42,
            "ratio": 0.5,
            "enabled": True,
            "name": "radar",
            "items": [1, 2, 3],
            "empty": [],
            "quoted": "带 # 号的字符串",
        }
    }


def test_multiline_array_is_supported():
    parsed = parse_toml_subset("[section]\nitems = [\n  1,\n  2,\n]\n")
    assert parsed == {"section": {"items": [1, 2]}}


def test_crlf_and_bom_are_normalized():
    parsed = parse_toml_subset("\ufeff[section]\r\nvalue = 1\r\n")
    assert parsed == {"section": {"value": 1}}


# --------------------------------------------------------------------------------------
# 路径解析：显式 > 环境变量 > 仓库根；找不到不回落 CWD
# --------------------------------------------------------------------------------------


def test_env_var_config_path_is_honored(tmp_path, monkeypatch, config_path):
    monkeypatch.setenv(config_module.ENV_CONFIG_PATH, str(config_path))
    cfg = load()
    assert str(cfg.source_path) == str(config_path)


def test_missing_config_does_not_fall_back_to_cwd(tmp_path, monkeypatch, clean_cwd):
    monkeypatch.delenv(config_module.ENV_CONFIG_PATH, raising=False)
    from agent_conflict_radar.errors import ConfigError as _ConfigError

    with pytest.raises(_ConfigError) as excinfo:
        config_module.resolve_config_path(None, start=tmp_path)
    message = str(excinfo.value)
    assert "找不到配置文件" in message
    assert config_module.ENV_CONFIG_PATH in message


def test_explicit_config_wins_over_env(make_config, monkeypatch, config_path):
    other = make_config(filename="other.toml")
    monkeypatch.setenv(config_module.ENV_CONFIG_PATH, str(other))
    cfg = load(str(config_path))
    assert str(cfg.source_path) == str(config_path)


def test_config_error_exit_code_is_environment():
    """配置类错误必须落在 K1 的"依赖或环境缺失"（3），不能落成用法错误。"""
    from agent_conflict_radar.exit_codes import EXIT_ENVIRONMENT

    assert ConfigError.exit_code == EXIT_ENVIRONMENT
    assert TomlUnsupportedError.exit_code == EXIT_ENVIRONMENT


# --------------------------------------------------------------------------------------
# 只读覆盖（`Config.with_override`）：CLI 的 `--window` 走这条，配置文件仍是唯一权威
# --------------------------------------------------------------------------------------


def test_with_override_returns_a_new_view_and_leaves_the_original_alone(config_path):
    cfg = load(str(config_path))
    original = cfg.get("window", "scan_days")
    narrowed = cfg.with_override("window", "scan_days", original + 1)
    assert narrowed.get("window", "scan_days") == original + 1
    assert cfg.get("window", "scan_days") == original, "覆盖必须返回新视图，不得就地改原对象"
    assert narrowed.as_dict()["window"]["scan_days"] == original + 1
    assert str(narrowed.source_path) == str(cfg.source_path), "来源路径要跟着新视图一起带过去（可核验）"


def test_with_override_does_not_touch_the_config_file(config_path, tmp_path):
    """覆盖只在内存里：写盘就会让 `config/radar.toml` 出现第二处真相（K3）。"""
    before = config_path.read_bytes()
    cfg = load(str(config_path))
    cfg.with_override("window", "active_minutes", 5)
    assert config_path.read_bytes() == before


def test_with_override_rejects_unknown_keys_and_wrong_types(config_path):
    cfg = load(str(config_path))
    for section, key, value in (
        ("nope", "scan_days", 1),
        ("scan", "nope", 1),
        ("scan", "max_line_bytes", "not-an-int"),
        ("git", "merge_tree_enabled", 1),
    ):
        with pytest.raises(ConfigError):
            cfg.with_override(section, key, value)


def test_with_override_rejects_none_so_callers_must_not_pass_it():
    """`None` 必须报错：调用方该做的是"不调用覆盖"，而不是传 None 混过去。"""
    cfg = load()
    with pytest.raises(ConfigError):
        cfg.with_override("window", "scan_days", None)
