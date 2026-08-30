from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rnds_data_lab.security import (
    SAFE_DOCUMENTATION_ALLOWLIST,
    is_plausible_cns,
    is_plausible_cpf,
    scan_file,
    scan_text,
    suppress_small_cells,
)


def _valid_cns(prefix: str = "7") -> str:
    base = prefix + "1234567890123"
    for check_digit in range(10):
        candidate = f"{base}{check_digit}"
        if is_plausible_cns(candidate):
            return candidate
    raise AssertionError("não foi possível montar CNS de teste")


def _valid_cpf() -> str:
    base = "529982247"
    first = sum(int(digit) * weight for digit, weight in zip(base, range(10, 1, -1), strict=True))
    first_check = (first * 10 % 11) % 10
    partial = f"{base}{first_check}"
    second = sum(
        int(digit) * weight for digit, weight in zip(partial, range(11, 1, -1), strict=True)
    )
    second_check = (second * 10 % 11) % 10
    return f"{partial}{second_check}"


def test_cpf_plausibility() -> None:
    assert is_plausible_cpf(_valid_cpf())
    assert not is_plausible_cpf("1" * 11)


def test_cns_plausibility() -> None:
    assert is_plausible_cns(_valid_cns())
    assert not is_plausible_cns("1" * 15)


def test_scanner_detects_prohibited_patterns_without_echoing_value() -> None:
    cpf = _valid_cpf()
    cns = _valid_cns()
    secret = "token=" + "realistic" + "SecretValue123"
    email = "pessoa" + "@" + "hospital.org"
    phone = "+55 (11) " + "99876" + "-5432"
    certificate = "-----BEGIN " + "PRIVATE KEY-----"
    endpoint = "https://api." + "production.health.example/v1"
    text = (
        f"CPF {cpf}; CNS {cns}; contato {email}; telefone {phone}; {secret}; "
        f"{certificate}; {endpoint}"
    )

    findings = scan_text(text, path="fixture.txt", allowlist=())

    assert {finding.kind for finding in findings} == {
        "cpf",
        "cns",
        "email",
        "telefone",
        "segredo",
        "certificado",
        "endpoint-producao",
    }
    assert all(secret not in repr(finding) for finding in findings)
    assert all(cpf not in repr(finding) for finding in findings)
    assert all(finding.path == "fixture.txt" and finding.line == 1 for finding in findings)


def test_explicit_documentation_allowlist_suppresses_only_known_placeholder() -> None:
    placeholder = "token=EXAMPLE_TOKEN_NOT_A_SECRET"
    findings = scan_text(placeholder)
    assert findings == []
    assert placeholder in SAFE_DOCUMENTATION_ALLOWLIST
    other_token = "token=" + "different" + "SecretValue123"
    assert scan_text(other_token)


def test_scan_file_reports_path_without_secret(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    email = "pessoa" + "@" + "hospital.org"
    target.write_text(f"email: {email}", encoding="utf-8")
    findings = scan_file(target, allowlist=())
    assert len(findings) == 1
    assert findings[0].path == str(target)
    assert email not in repr(findings[0])


@given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(min_value=0, max_value=100)))
def test_suppression_never_reveals_counts_below_threshold(cells: dict[str, int]) -> None:
    minimum = 5
    suppressed = suppress_small_cells(cells, minimum=minimum)
    assert all(suppressed[key] is None for key, value in cells.items() if value < minimum)
    assert all(suppressed[key] == value for key, value in cells.items() if value >= minimum)


def test_suppression_rejects_invalid_threshold_and_count() -> None:
    with pytest.raises(ValueError, match="minimum"):
        suppress_small_cells({"a": 1}, minimum=0)
    with pytest.raises(ValueError, match="contagens"):
        suppress_small_cells({"a": -1})
