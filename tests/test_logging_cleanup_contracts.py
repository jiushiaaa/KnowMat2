from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_nodes_do_not_use_print_for_runtime_logging():
    targets = [
        ROOT / "src" / "knowmat" / "nodes" / "validator.py",
        ROOT / "src" / "knowmat" / "nodes" / "evaluation.py",
        ROOT / "src" / "knowmat" / "nodes" / "aggregator.py",
        ROOT / "src" / "knowmat" / "nodes" / "paddleocrvl_parse_pdf.py",
        ROOT / "src" / "knowmat" / "orchestrator.py",
        ROOT / "src" / "knowmat" / "__main__.py",
    ]
    for path in targets:
        assert "print(" not in path.read_text(encoding="utf-8"), f"{path.name} still uses print()"
