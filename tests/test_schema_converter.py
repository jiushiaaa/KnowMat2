import math

from knowmat import schema_converter as schema_converter_module
from knowmat.schema_converter import SchemaConverter


converter = SchemaConverter()


def test_parse_temperature_to_k_from_at_k():
    assert converter.parse_temperature_to_k("measured at 298 K in air") == 298
    assert converter.parse_temperature_to_k("AT 873 K; compression") == 873


def test_parse_temperature_to_k_from_celsius():
    assert converter.parse_temperature_to_k("tested at 25 C") == 298.15
    assert converter.parse_temperature_to_k("at 100 c in vacuum") == 373.15


def test_parse_temperature_to_k_from_k_without_at():
    assert converter.parse_temperature_to_k("873K tensile test") == 873


def test_parse_temperature_to_k_for_room_temperature_alias():
    assert converter.parse_temperature_to_k("room temperature test") == 298.15


def test_parse_temperature_to_k_returns_none_when_no_temperature():
    assert converter.parse_temperature_to_k("tensile test under argon") is None


def test_validate_composition_json_warns_on_sum_far_from_100():
    comp = {"Ti": 30.0, "Nb": 30.0, "Zr": 30.0}
    cleaned, warnings = converter.validate_composition_json(comp, "Ti30Nb30Zr30")
    assert any("Normalised to 100 at%" in w for w in warnings)
    assert abs(sum(cleaned.values()) - 100.0) < 1e-6


def test_build_composition_json_defaults_missing_amounts_to_one():
    comp = converter.build_composition_json("FeCoCrNiMo0.5")
    assert set(comp.keys()) == {"Fe", "Co", "Cr", "Ni", "Mo"}
    if schema_converter_module._PymatgenComposition is not None:
        assert math.isclose(sum(comp.values()), 100.0, rel_tol=1e-6, abs_tol=1e-6)
        assert math.isclose(comp["Fe"], comp["Co"], rel_tol=1e-6)
        assert math.isclose(comp["Cr"], comp["Ni"], rel_tol=1e-6)
        assert comp["Mo"] < comp["Fe"]
    else:
        assert comp["Fe"] == 1.0
        assert comp["Co"] == 1.0
        assert comp["Cr"] == 1.0
        assert comp["Ni"] == 1.0
        assert math.isclose(comp["Mo"], 0.5)


def test_build_composition_json_handles_balance_notation_without_barium_leak():
    comp = converter.build_composition_json(
        "NiBalCr21.49W13.13Mo2.22Fe1.57Co1.30Al0.46Mn0.34Si0.30La0.029C0.48"
    )
    assert "Ba" not in comp
    assert "Ni" in comp
    if schema_converter_module._PymatgenComposition is not None:
        assert math.isclose(sum(comp.values()), 100.0, rel_tol=1e-6, abs_tol=1e-6)
        assert comp["Ni"] > 50.0


def test_build_composition_json_handles_ti_v_amount_tokens_without_crashing():
    comp = converter.build_composition_json("Ti4V10")
    assert "Ti" in comp
    assert "V" in comp
    if schema_converter_module._PymatgenComposition is not None:
        assert math.isclose(sum(comp.values()), 100.0, rel_tol=1e-6, abs_tol=1e-6)


def test_recover_formula_from_paper_text_prefers_explicit_balance_line():
    paper_text = (
        "The powder's elemental composition is 21.49 Cr - 13.13 W - 2.22 Mo - "
        "1.57 Fe - 1.30 Co - 0.46 Al - 0.34 Mn - 0.30 Si - 0.029 La - 0.48 C - Bal Ni "
        "(weight percent, wt.%)."
    )
    recovered = converter._recover_formula_from_paper_text(
        paper_text=paper_text,
        comp_raw="SD3230 [As-Built, Horizontal BD]",
        fallback_formula="Ni21.18Cr13.27W2.84Mo0.92Fe1.12Co0.88Al0.68Mn0.25Si0.43C1.59La0.008",
        target_count=1,
    )
    assert recovered is not None
    assert recovered.startswith("Ni58.681")
    comp = converter.build_composition_json(recovered)
    if schema_converter_module._PymatgenComposition is not None:
        assert math.isclose(comp["Ni"], 58.681, rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(comp["Cr"], 21.49, rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(sum(comp.values()), 100.0, rel_tol=1e-6, abs_tol=1e-6)


def test_validate_composition_json_drops_invalid_element():
    comp = {"Ti": 50.0, "Xx": 50.0}
    cleaned, warnings = converter.validate_composition_json(comp, "Ti50Xx50")
    assert "Xx" not in cleaned
    assert any("Invalid element" in w for w in warnings)


def test_parse_key_params_tolerates_noisy_numeric_tokens():
    params = converter.parse_key_params("laser power=10V2 W; scan speed=900 mm/s")
    assert "Scanning_Speed_mm_s" in params


def test_convert_bootstraps_datasheet_compositions_when_llm_returns_none():
    data = {"compositions": []}
    paper_text = (
        "Common Name: Iodide Ti\n"
        "Specifications and Compositions.\n"
        "| Specification designation | Form(s) | C | H | N | O | Cu | Fe | Mn | Sn | Si | Zr | Cl | Mg | Tibal |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| Typical %, electrolytic T1 | ... | 0.008 | ... | 0.004 | 0.037 | 0.007 | 0.009 | <0.001 | <0.020 | 0.002 | <0.001 | 0.073 | <0.001 | 99.837 |\n"
    )
    out = converter.convert(data, "High-Purity Ti.md", paper_text=paper_text)
    assert len(out["items"]) >= 1
    comp = out["items"][0]["Composition_Info"]["Nominal_Composition"]["Elements_Normalized"]
    assert "Ti" in comp


def test_convert_preserves_legacy_materials_envelope_support():
    data = {
        "Paper_Metadata": {"Paper_Title": "Legacy Sample", "DOI": "10.1000/legacy"},
        "Materials": [
            {
                "Composition_Info": {
                    "Alloy_Name": "Ti-6Al-4V",
                    "Nominal_Composition": {
                        "Formula": "Ti6Al4V",
                        "Elements": {"Ti": 90.0, "Al": 6.0, "V": 4.0},
                    },
                },
                "Properties_Info": [{"Property_Name": "Hardness", "Value": "350", "Unit": "HV"}],
            }
        ],
    }
    out = converter.convert(data, "legacy.md")
    assert out["Paper_Metadata"]["Paper_Title"] == "Legacy Sample"
    assert out["Paper_Metadata"]["DOI"] == "10.1000/legacy"
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert item["Composition_Info"]["Alloy_Name_Raw"] == "Ti-6Al-4V"
    assert item["Composition_Info"]["Nominal_Composition"]["Elements_Normalized"]["Ti"] == 90.0


def test_convert_expands_step_keyed_runtime_composition_maps():
    data = {
        "compositions": [
            {
                "composition": "Multigraded Ti6Al4V-IN718 specimen",
                "alloy_name_raw": "Multigraded Ti6Al4V-IN718 specimen",
                "nominal_composition": {
                    "0": {"Ti": 88.93, "Al": 6.4, "V": 4.1, "Fe": 0.18, "other": 0.39},
                    "5": {
                        "Ti": 86.7,
                        "Al": 5.52,
                        "V": 3.68,
                        "Ni": 2.5,
                        "Cr": 0.98,
                        "Fe": 0.87,
                        "Nb": 0.24,
                        "Mo": 0.14,
                    },
                    "20 wt%": {
                        "Ti": 74.36,
                        "Al": 3.85,
                        "V": 2.91,
                        "Ni": 10.0,
                        "Cr": 3.92,
                        "Fe": 3.5,
                        "Nb": 0.95,
                        "Mo": 0.53,
                    },
                },
                "nominal_composition_type": "wt%",
                "processing_conditions": (
                    "original: Multi-material SLM graded transition from Ti6Al4V to IN718: "
                    "42 layers at 0% IN718, then 12 layers each at 5%, 10%, 15%, 20% IN718. "
                    "|| simplified: graded Ti6Al4V/IN718 transition"
                ),
                "process_category": "AM_LPBF + Graded_Composition",
                "properties_of_composition": [
                    {
                        "property_name": "hardness",
                        "value": "400-700",
                        "value_numeric": 550.0,
                        "value_type": "range",
                        "unit": "HV",
                    }
                ],
                "characterisation": {},
            }
        ]
    }
    out = converter.convert(data, "graded.md")
    names = [item["Composition_Info"]["Alloy_Name_Raw"] for item in out["items"]]
    assert names == [
        "Graded Ti6Al4V/IN718 - Ti6Al4V base layer (0 wt% IN718)",
        "Graded Ti6Al4V/IN718 - 5 wt% IN718 step",
        "Graded Ti6Al4V/IN718 - 20 wt% IN718 step",
    ]
    assert all(item["Properties_Info"] == [] for item in out["items"])
