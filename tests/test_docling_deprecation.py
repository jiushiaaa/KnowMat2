import warnings

from knowmat.nodes.docling_parse_pdf import parse_pdf_with_docling


def test_parse_pdf_with_docling_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        try:
            parse_pdf_with_docling({})
        except Exception:
            pass
        assert any(
            issubclass(w.category, DeprecationWarning) for w in caught
        ), "expected DeprecationWarning when calling legacy docling alias"
