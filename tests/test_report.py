from pathlib import Path

from nixpkgs_review.report import Report, ReportOptions
from nixpkgs_review.utils import PackageFilter


def test_header_shows_host_system(tmp_path: Path) -> None:
    report = Report(
        "abc123", {}, PackageFilter(), ReportOptions(host_system="aarch64-darwin")
    )
    assert "Host: `aarch64-darwin`\n" in report.markdown(tmp_path, 1)


def test_header_omits_host_system_when_unknown(tmp_path: Path) -> None:
    report = Report("abc123", {}, PackageFilter())
    assert "Host:" not in report.markdown(tmp_path, 1)


def test_systems_without_packages_get_no_section(tmp_path: Path) -> None:
    report = Report("abc123", {}, PackageFilter())
    assert "###" not in report.markdown(tmp_path, 1)
