from knowmat import nodes


def test_nodes_all_hides_legacy_docling_wrapper():
    assert "docling_parse_pdf" not in nodes.__all__
