from pathlib import Path

from nixpkgs_review.report import Report, ReportOptions
from nixpkgs_review.utils import PackageFilter


def test_empty_results_list_systems(tmp_path: Path) -> None:
    report = Report(
        "abc123",
        {},
        PackageFilter(),
        ReportOptions(systems=["x86_64-linux", "aarch64-darwin"]),
    )
    markdown = report.markdown(tmp_path, 1)
    assert "### `x86_64-linux`\nNo packages to build.\n" in markdown
    assert "### `aarch64-darwin`\nNo packages to build.\n" in markdown
    assert markdown.index("x86_64-linux") < markdown.index("aarch64-darwin")


def test_no_systems_no_sections(tmp_path: Path) -> None:
    report = Report("abc123", {}, PackageFilter())
    assert "###" not in report.markdown(tmp_path, 1)


def test_header_shows_host_system(tmp_path: Path) -> None:
    report = Report(
        "abc123", {}, PackageFilter(), ReportOptions(host_system="aarch64-darwin")
    )
    assert "Host: `aarch64-darwin`\n" in report.markdown(tmp_path, 1)


def test_header_omits_host_system_when_unknown(tmp_path: Path) -> None:
    report = Report("abc123", {}, PackageFilter())
    assert "Host:" not in report.markdown(tmp_path, 1)
