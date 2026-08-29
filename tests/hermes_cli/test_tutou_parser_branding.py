"""Tutou-facing contracts for the top-level CLI parser."""


def test_top_level_parser_uses_tutou_product_identity():
    from hermes_cli._parser import build_top_level_parser

    parser, _, _ = build_top_level_parser()
    help_text = parser.format_help()

    assert parser.prog == "tutou"
    assert "Tutou Agent" in (parser.description or "")
    assert "tutou chat" in help_text
    assert "tutou <command> --help" in help_text
