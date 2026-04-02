"""
Backward-compatible wrapper for the legacy docling parser module.

The pipeline now uses PaddleOCR-VL. Existing imports of
`parse_pdf_with_docling` are mapped to the new parser implementation.
"""

import warnings

from knowmat.nodes.paddleocrvl_parse_pdf import parse_pdf_with_paddleocrvl


def parse_pdf_with_docling(state):
    """Compatibility alias to the PaddleOCR-VL parser."""
    warnings.warn(
        "parse_pdf_with_docling() is deprecated; use "
        "parse_pdf_with_paddleocrvl() from knowmat.nodes.paddleocrvl_parse_pdf instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return parse_pdf_with_paddleocrvl(state)
