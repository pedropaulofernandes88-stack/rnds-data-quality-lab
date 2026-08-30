"""Controles locais para impedir a inclusão acidental de material sensível.

Este módulo é uma barreira preventiva para um repositório educacional. Ele não
substitui DLP, revisão humana, avaliação jurídica ou controles institucionais.
Os achados nunca carregam o valor encontrado, para que o relatório do scanner
não se torne uma nova fonte de exposição.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

CellCount: TypeAlias = int | None


@dataclass(frozen=True, slots=True)
class Finding:
    """Metadados seguros de um possível dado ou segredo proibido."""

    kind: str
    rule: str
    path: str
    line: int
    column: int


# A lista é deliberadamente pequena, literal e auditável. Ela contém somente
# placeholders reservados para documentação; nunca acrescente valores reais.
SAFE_DOCUMENTATION_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "docs.safe@example.invalid",
        "token=EXAMPLE_TOKEN_NOT_A_SECRET",
        "https://api.production.example.invalid/v1",
    }
)

_CPF_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(?:\d{3}[.\s]?\d{3}[.\s]?\d{3}-?\d{2})(?!\d)")
_CNS_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)[12789]\d{14}(?!\d)")
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.+-])[A-Z0-9][A-Z0-9._%+-]{0,63}@[A-Z0-9.-]+\.[A-Z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)
_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?:\+55\s*)?(?:\([1-9]\d\)|[1-9]\d)[\s.-]?(?:9\d{4}|\d{4})[-\s]\d{4}(?!\d)"
)
_ASSIGNMENT_SECRET_RE: Final[re.Pattern[str]] = re.compile(
    r"(?im)\b(?:api[_-]?key|token|secret|password|client[_-]?secret|authorization)"
    r"\s*[:=]\s*(?:bearer\s+)?[\"']?[A-Za-z0-9_./+=-]{12,}"
)
_JWT_RE: Final[re.Pattern[str]] = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_CERTIFICATE_RE: Final[re.Pattern[str]] = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*(?:CERTIFICATE|PRIVATE KEY)-----"
)
_PRODUCTION_ENDPOINT_RE: Final[re.Pattern[str]] = re.compile(
    r"https?://[^\s/\"']*(?:\bprod(?:uction)?\b|ehr-services\.saude\.gov\.br|api\.rnds)"
    r"[^\s\"']*",
    re.IGNORECASE,
)


def is_plausible_cpf(value: str) -> bool:
    """Retorna se ``value`` tem os dígitos verificadores válidos de um CPF."""

    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 11 or len(set(digits)) == 1:
        return False

    first = sum(
        int(digit) * weight for digit, weight in zip(digits[:9], range(10, 1, -1), strict=True)
    )
    first_check = (first * 10 % 11) % 10
    second = sum(
        int(digit) * weight for digit, weight in zip(digits[:10], range(11, 1, -1), strict=True)
    )
    second_check = (second * 10 % 11) % 10
    return digits[-2:] == f"{first_check}{second_check}"


def is_plausible_cns(value: str) -> bool:
    """Valida o checksum ponderado de um CNS de 15 dígitos."""

    if not re.fullmatch(r"[12789]\d{14}", value):
        return False
    total = sum(int(digit) * weight for digit, weight in zip(value, range(15, 0, -1), strict=True))
    return total % 11 == 0


def _position(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    return line, offset - last_newline


def _add_matches(
    findings: list[Finding],
    *,
    text: str,
    path: str,
    pattern: re.Pattern[str],
    kind: str,
    rule: str,
    allowlist: frozenset[str],
    predicate: Callable[[str], bool] | None = None,
) -> None:
    for match in pattern.finditer(text):
        candidate = match.group(0)
        if candidate in allowlist or (predicate is not None and not predicate(candidate)):
            continue
        line, column = _position(text, match.start())
        findings.append(Finding(kind=kind, rule=rule, path=path, line=line, column=column))


def scan_text(
    text: str,
    *,
    path: str = "<text>",
    allowlist: Iterable[str] = SAFE_DOCUMENTATION_ALLOWLIST,
) -> list[Finding]:
    """Varre texto e retorna achados seguros, sem reproduzir o conteúdo encontrado."""

    approved = frozenset(allowlist)
    findings: list[Finding] = []
    _add_matches(
        findings,
        text=text,
        path=path,
        pattern=_CPF_RE,
        kind="cpf",
        rule="cpf-plausivel",
        allowlist=approved,
        predicate=is_plausible_cpf,
    )
    _add_matches(
        findings,
        text=text,
        path=path,
        pattern=_CNS_RE,
        kind="cns",
        rule="cns-plausivel",
        allowlist=approved,
        predicate=is_plausible_cns,
    )
    for pattern, kind, rule in (
        (_EMAIL_RE, "email", "email"),
        (_PHONE_RE, "telefone", "telefone-br"),
        (_ASSIGNMENT_SECRET_RE, "segredo", "atribuicao-de-segredo"),
        (_JWT_RE, "token", "jwt"),
        (_CERTIFICATE_RE, "certificado", "pem"),
        (_PRODUCTION_ENDPOINT_RE, "endpoint-producao", "endpoint-producao"),
    ):
        _add_matches(
            findings,
            text=text,
            path=path,
            pattern=pattern,
            kind=kind,
            rule=rule,
            allowlist=approved,
        )
    return findings


def scan_file(
    file_path: str | Path,
    *,
    allowlist: Iterable[str] = SAFE_DOCUMENTATION_ALLOWLIST,
) -> list[Finding]:
    """Varre arquivo UTF-8, substituindo bytes inválidos sem interromper a auditoria."""

    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return scan_text(text, path=str(path), allowlist=allowlist)


def scan_paths(
    paths: Iterable[str | Path],
    *,
    allowlist: Iterable[str] = SAFE_DOCUMENTATION_ALLOWLIST,
) -> list[Finding]:
    """Varre arquivos e diretórios, ignorando diretórios de ferramentas."""

    findings: list[Finding] = []
    excluded = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
    for item in (Path(value) for value in paths):
        files = (
            (entry for entry in item.rglob("*") if entry.is_file()) if item.is_dir() else (item,)
        )
        for file_path in files:
            if any(part in excluded for part in file_path.parts):
                continue
            findings.extend(scan_file(file_path, allowlist=allowlist))
    return findings


def suppress_small_cells(
    cells: Mapping[str, int],
    *,
    minimum: int = 5,
    marker: CellCount = None,
) -> dict[str, CellCount]:
    """Oculta contagens pequenas; totais ainda podem exigir supressão complementar."""

    if minimum < 1:
        raise ValueError("minimum deve ser maior ou igual a 1")
    if any(isinstance(count, bool) or count < 0 for count in cells.values()):
        raise ValueError("células devem conter contagens inteiras não negativas")
    return {key: count if count >= minimum else marker for key, count in cells.items()}
