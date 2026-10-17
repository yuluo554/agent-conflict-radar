"""冻结序列化契约（K2）+ 零外链断言（K13）。

"逐字节一致"这类承诺只有在**字节层**断言才算数：文本层 `==` 看不出 CRLF、BOM、尾换行差异，
而这三样正是跨平台漂移的常见来源。
"""

import json

from agent_conflict_radar.serialize import (
    FROZEN_JSON_KWARGS,
    LINE_ENDING,
    assert_no_external_resources,
    dumps_json,
    find_external_resources,
    normalize_newlines,
    write_atomic,
    write_json_atomic,
)


def test_frozen_kwargs_are_what_they_claim():
    """契约参数本身也要被断言——否则"冻结"只是注释里的一句话。"""
    assert FROZEN_JSON_KWARGS == {"sort_keys": True, "ensure_ascii": False, "indent": 2}


def test_dumps_json_matches_expected_bytes():
    expected = '{\n  "a": "中文",\n  "b": 1\n}\n'
    assert dumps_json({"b": 1, "a": "中文"}) == expected
    assert dumps_json({"b": 1, "a": "中文"}).encode("utf-8") == expected.encode("utf-8")


def test_keys_are_sorted_and_chinese_is_not_escaped():
    text = dumps_json({"z": 1, "a": "中文"})
    assert text.index('"a"') < text.index('"z"')
    assert "中文" in text
    assert "\\u4e2d" not in text, "ensure_ascii=False 是中文项目的必选项（否则 diff 不可读）"


def test_write_atomic_produces_lf_and_trailing_newline(tmp_path):
    target = write_atomic(tmp_path / "out.json", '{\r\n  "a": 1\r\n}\r\n')
    raw = target.read_bytes()
    assert b"\r" not in raw, "落盘字节里不得出现 CR（跨平台逐字节一致的前提）"
    assert raw.endswith(b"\n")
    assert raw.decode("utf-8").count("\n") == 3


def test_write_atomic_leaves_no_temp_file(tmp_path):
    write_atomic(tmp_path / "out.json", "x\n")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftovers == []


def test_same_input_written_twice_is_byte_identical(tmp_path):
    payload = {"b": [1, 2], "a": {"中文": True, "n": None}}
    first = write_json_atomic(tmp_path / "one.json", payload).read_bytes()
    second = write_json_atomic(tmp_path / "two.json", payload).read_bytes()
    assert first == second
    assert json.loads(first.decode("utf-8")) == payload


def test_normalize_newlines_cases():
    assert normalize_newlines("a\r\nb") == "a\nb\n"
    assert normalize_newlines("a") == "a\n"
    assert normalize_newlines("a\n\n\n") == "a\n"
    assert normalize_newlines("") == "\n"


# --------------------------------------------------------------------------------------
# 零外链（K13）：报告必须断网可打开
# --------------------------------------------------------------------------------------


def test_external_resource_detection_positive_and_negative():
    assert find_external_resources("普通文本，只有 config/radar.toml 这样的相对路径") == []
    assert "http://" in find_external_resources("见 http://example.com")
    assert "https://" in find_external_resources("![图](https://cdn.example.com/a.png)")
    assert "<img" in find_external_resources('<img src="a.png">')


def test_assert_no_external_resources_raises_with_context():
    import pytest

    with pytest.raises(ValueError) as excinfo:
        assert_no_external_resources("![x](https://cdn.example.com/x.png)", where="report.md")
    message = str(excinfo.value)
    assert "report.md" in message
    assert "零外链" in message


def test_assert_no_external_resources_passes_on_relative_paths():
    assert_no_external_resources("| 文件 | 行区间 |\n| src/alpha.py | 10-14 |\n")


def test_line_ending_constant_is_lf():
    assert LINE_ENDING == "\n"
