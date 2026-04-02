import importlib
import sys
import warnings


def test_importing_extractors_does_not_emit_langgraph_send_deprecation():
    for module_name in list(sys.modules):
        if module_name == "knowmat.extractors" or module_name.startswith("trustcall"):
            sys.modules.pop(module_name, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        importlib.import_module("knowmat.extractors")

    assert not any(
        "Importing Send from langgraph.constants is deprecated" in str(w.message)
        for w in caught
    )
