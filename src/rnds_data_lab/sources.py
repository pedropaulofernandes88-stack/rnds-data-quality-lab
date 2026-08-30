"""Manifesto e utilitários seguros para fontes públicas do laboratório.

O módulo deliberadamente não contém credenciais nem acesso à RNDS. Downloads
são explícitos e os testes podem usar ``httpx.MockTransport`` sem rede.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

import httpx
import polars as pl
import yaml


class SourceManifestError(ValueError):
    """Indica que o manifesto não atende ao contrato mínimo do laboratório."""


class UnsafeDownloadError(ValueError):
    """Indica uma URL, resposta ou arquivo inadequado para ingestão."""


class DownloadLimitError(UnsafeDownloadError):
    """Indica que o tamanho permitido da transferência foi excedido."""


@dataclass(frozen=True, slots=True)
class RndsIndicator:
    """Identificador e rótulo de um indicador público agregado da RNDS."""

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class Source:
    """Metadados mínimos necessários para uma fonte reproduzível."""

    id: str
    name: str
    url: str
    format: str
    granularity: str
    update_frequency: str
    license: str
    limitations: tuple[str, ...]
    indicators: tuple[RndsIndicator, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Manifesto tipado carregado de ``data/sources.yml``."""

    schema_version: int
    sources: tuple[Source, ...]

    def by_id(self, source_id: str) -> Source:
        """Retorna uma fonte por identificador estável."""

        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(f"Fonte não encontrada: {source_id}")


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    """Proveniência produzida após transferir um arquivo com sucesso."""

    url: str
    path: Path
    bytes_downloaded: int
    sha256: str
    extracted_at: datetime


RNDS_PUBLIC_INDICATORS: Final[Mapping[str, RndsIndicator]] = MappingProxyType(
    {
        "sdigi008": RndsIndicator("sdigi008", "Total de registros na RNDS"),
        "sdigi009": RndsIndicator(
            "sdigi009", "Total de Registros de Imunobiológicos Administrados (RIA)"
        ),
        "sdigi010": RndsIndicator("sdigi010", "Total de Registros de Atendimento Clínico (RAC)"),
        "sdigi011": RndsIndicator(
            "sdigi011", "Total de registros de atestados médico/odontológicos"
        ),
        "sdigi013": RndsIndicator("sdigi013", "Total de registros de prescrição de medicamento"),
        "sdigi014": RndsIndicator("sdigi014", "Total de registros de exames laboratoriais (REL)"),
        "sdigi015": RndsIndicator(
            "sdigi015", "Total de registros de informações de regulação assistencial (RIRA)"
        ),
    }
)


def default_manifest_path() -> Path:
    """Localiza o manifesto distribuído no repositório, sem depender do CWD."""

    repository_path = Path(__file__).resolve().parents[2] / "data" / "sources.yml"
    if repository_path.is_file():
        return repository_path
    return Path(__file__).resolve().parent / "data" / "sources.yml"


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SourceManifestError(f"Campo obrigatório inválido: {field}")
    return value.strip()


def _parse_source(payload: object) -> Source:
    if not isinstance(payload, Mapping):
        raise SourceManifestError("Cada fonte deve ser um objeto")

    limitations_value = payload.get("limitations")
    if not isinstance(limitations_value, Sequence) or isinstance(limitations_value, str):
        raise SourceManifestError("limitations deve ser uma lista de textos")
    limitations = tuple(
        _required_text({"limitation": value}, "limitation") for value in limitations_value
    )

    indicators_value = payload.get("indicators", ())
    if not isinstance(indicators_value, Sequence) or isinstance(indicators_value, str):
        raise SourceManifestError("indicators deve ser uma lista")
    indicators: list[RndsIndicator] = []
    for indicator_payload in indicators_value:
        if not isinstance(indicator_payload, Mapping):
            raise SourceManifestError("Cada indicador deve ser um objeto")
        indicators.append(
            RndsIndicator(
                code=_required_text(indicator_payload, "code"),
                name=_required_text(indicator_payload, "name"),
            )
        )

    return Source(
        id=_required_text(payload, "id"),
        name=_required_text(payload, "name"),
        url=_required_text(payload, "url"),
        format=_required_text(payload, "format"),
        granularity=_required_text(payload, "granularity"),
        update_frequency=_required_text(payload, "update_frequency"),
        license=_required_text(payload, "license"),
        limitations=limitations,
        indicators=tuple(indicators),
    )


def load_manifest(path: Path | None = None) -> SourceManifest:
    """Carrega e valida o manifesto de fontes públicas."""

    manifest_path = path or default_manifest_path()
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SourceManifestError(f"Não foi possível ler {manifest_path}") from exc
    if not isinstance(raw, Mapping):
        raise SourceManifestError("O manifesto deve ser um objeto YAML")

    schema_version = raw.get("schema_version")
    sources_value = raw.get("sources")
    if not isinstance(schema_version, int) or schema_version < 1:
        raise SourceManifestError("schema_version deve ser um inteiro positivo")
    if not isinstance(sources_value, Sequence) or isinstance(sources_value, str):
        raise SourceManifestError("sources deve ser uma lista")

    sources = tuple(_parse_source(item) for item in sources_value)
    source_ids = [source.id for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise SourceManifestError("Os identificadores das fontes devem ser únicos")

    manifest = SourceManifest(schema_version=schema_version, sources=sources)
    indicator_source = manifest.by_id("rnds_public_indicators")
    found_codes = {indicator.code for indicator in indicator_source.indicators}
    if found_codes != set(RNDS_PUBLIC_INDICATORS):
        raise SourceManifestError(
            "O manifesto deve conter exatamente os sete indicadores RNDS públicos"
        )
    return manifest


def validate_csv_zip_url(url: str) -> None:
    """Recusa URLs que não sejam HTTPS e arquivos CSV ZIP explícitos."""

    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise UnsafeDownloadError("O download deve usar uma URL HTTPS absoluta")
    if parts.username or parts.password:
        raise UnsafeDownloadError("URLs com credenciais não são permitidas")
    if not parts.path.lower().endswith(".csv.zip"):
        raise UnsafeDownloadError("O recurso deve terminar em .csv.zip")


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError as exc:
        raise UnsafeDownloadError("Content-Length inválido") from exc
    if length < 0:
        raise UnsafeDownloadError("Content-Length inválido")
    return length


def download_csv_zip(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> DownloadReceipt:
    """Baixa um CSV ZIP por HTTPS, respeitando teto, timeout e escrita atômica."""

    validate_csv_zip_url(url)
    if max_bytes <= 0:
        raise ValueError("max_bytes deve ser positivo")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds deve ser positivo")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    digest = sha256()
    bytes_downloaded = 0
    try:
        with (
            httpx.Client(
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
                transport=transport,
            ) as client,
            client.stream("GET", url) as response,
        ):
            if response.is_redirect:
                raise UnsafeDownloadError("Redirecionamentos não são permitidos")
            response.raise_for_status()
            declared_length = _content_length(response)
            if declared_length is not None and declared_length > max_bytes:
                raise DownloadLimitError("Content-Length excede o teto configurado")

            with NamedTemporaryFile(
                mode="wb", prefix=f".{destination.name}.", dir=destination.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                for chunk in response.iter_bytes():
                    bytes_downloaded += len(chunk)
                    if bytes_downloaded > max_bytes:
                        raise DownloadLimitError("Transferência excede o teto configurado")
                    digest.update(chunk)
                    temporary_file.write(chunk)

        if bytes_downloaded == 0:
            raise UnsafeDownloadError("O arquivo baixado está vazio")
        if temporary_path is None:  # pragma: no cover
            raise UnsafeDownloadError("Arquivo temporário não foi criado")
        temporary_path.replace(destination)
        return DownloadReceipt(
            url=url,
            path=destination,
            bytes_downloaded=bytes_downloaded,
            sha256=digest.hexdigest(),
            extracted_at=datetime.now(UTC),
        )
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def parse_csv_zip_bytes(
    payload: bytes, *, max_uncompressed_bytes: int = 50_000_000
) -> pl.DataFrame:
    """Lê um único CSV de um ZIP em memória, sem extrair caminhos ao disco."""

    if max_uncompressed_bytes <= 0:
        raise ValueError("max_uncompressed_bytes deve ser positivo")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            files = [
                item
                for item in archive.infolist()
                if not item.is_dir() and item.filename.lower().endswith(".csv")
            ]
            if len(files) != 1:
                raise UnsafeDownloadError("O ZIP deve conter exatamente um arquivo CSV")
            info = files[0]
            if info.flag_bits & 0x1:
                raise UnsafeDownloadError("ZIPs criptografados não são permitidos")
            if info.file_size > max_uncompressed_bytes:
                raise DownloadLimitError("CSV descompactado excede o teto configurado")
            with archive.open(info) as csv_file:
                csv_payload = csv_file.read(max_uncompressed_bytes + 1)
    except BadZipFile as exc:
        raise UnsafeDownloadError("O recurso não é um ZIP válido") from exc

    if len(csv_payload) > max_uncompressed_bytes:
        raise DownloadLimitError("CSV descompactado excede o teto configurado")
    return pl.read_csv(BytesIO(csv_payload))


def parse_csv_zip(path: Path, *, max_uncompressed_bytes: int = 50_000_000) -> pl.DataFrame:
    """Lê um arquivo CSV ZIP local usando o mesmo parser seguro e puro."""

    payload = Path(path).read_bytes()
    return parse_csv_zip_bytes(payload, max_uncompressed_bytes=max_uncompressed_bytes)
