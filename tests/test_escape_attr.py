from nixpkgs_review.utils import escape_attr


def test_escape_attr() -> None:
    assert escape_attr("hello") == "hello"
    assert escape_attr("haskellPackages.if") == 'haskellPackages."if"'
    assert escape_attr("haskellPackages.if.doc") == 'haskellPackages."if"."doc"'
