from pathlib import Path

from knowmat.schema_converter import SchemaConverter


ROOT = Path(__file__).resolve().parents[1]


def test_schema_converter_drops_variable_family_dead_helpers():
    converter = SchemaConverter()
    removed_helpers = [
        "_expand_variable_materials_in_target_schema",
        "_expand_variable_composition_families",
        "_extract_variable_family_spec",
        "_extract_numeric_series",
        "_extract_numeric_series_best",
        "_format_x_code",
        "_format_x_label",
        "_extract_variant_code",
    ]
    for helper_name in removed_helpers:
        assert not hasattr(converter, helper_name)


def test_runtime_manifests_drop_legacy_langchain_and_pandas_entries():
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements_text = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert '"langchain>=' not in pyproject_text
    assert '"pandas>=' not in pyproject_text
    assert "\nlangchain==" not in requirements_text
    assert "\npandas>=" not in requirements_text
