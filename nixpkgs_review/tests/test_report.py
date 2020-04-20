import unittest

from nixpkgs_review.nix import Attr
from nixpkgs_review.report import Report

from .cli_mocks import read_asset


def mkAttr(name: str, success: bool) -> Attr:
    "Helper to construct a mock Attr result for the report"
    res = Attr(
        name=name,
        exists=True,
        broken=False,
        blacklisted=False,
        path="some_out_path",
        drv_path="some_drv_path",
    )
    res._path_verified = success
    return res


class ReportTestcase(unittest.TestCase):
    def test_markdown_report(self) -> None:
        "Test that the markdown report format is as expected"
        foo = mkAttr("foo", True)
        bar = mkAttr("bar", True)
        baz = mkAttr("baz", False)

        report = Report([foo, bar, baz])

        expected = read_asset("expected_pr_report_1234.md")
        actual = report.markdown(1234)

        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main(failfast=True)
