from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest

from rnds_data_lab.sources import (
    RNDS_PUBLIC_INDICATORS,
    DownloadLimitError,
    SourceManifestError,
    UnsafeDownloadError,
    download_csv_zip,
    load_manifest,
    parse_csv_zip_bytes,
    validate_csv_zip_url,
)


def csv_zip_bytes(*, additional_csv: bool = False) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("indicadores.csv", "codigo,valor\nsdigi008,10\n")
        if additional_csv:
            archive.writestr("outro.csv", "codigo,valor\nsdigi009,20\n")
    return buffer.getvalue()


def test_manifest_is_typed_and_contains_the_seven_public_indicators() -> None:
    manifest = load_manifest()

    source = manifest.by_id("rnds_public_indicators")
    assert {indicator.code for indicator in source.indicators} == set(RNDS_PUBLIC_INDICATORS)
    assert manifest.by_id("sinan_dengue").granularity.startswith("notificação")


def test_manifest_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    path = tmp_path / "sources.yml"
    path.write_text(
        "schema_version: 1\nsources:\n"
        "  - id: rnds_public_indicators\n    name: x\n    url: https://x.test\n"
        "    format: x\n    granularity: x\n    update_frequency: x\n    license: x\n"
        "    limitations: [x]\n    indicators: []\n"
        "  - id: rnds_public_indicators\n    name: y\n    url: https://y.test\n"
        "    format: y\n    granularity: y\n    update_frequency: y\n    license: y\n"
        "    limitations: [y]\n    indicators: []\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceManifestError, match="únicos"):
        load_manifest(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/source.csv.zip",
        "https://user:secret@example.test/source.csv.zip",
        "https://example.test/source.json.zip",
    ],
)
def test_csv_zip_url_requires_https_and_csv_zip(url: str) -> None:
    with pytest.raises(UnsafeDownloadError):
        validate_csv_zip_url(url)


def test_download_is_limited_hashed_and_atomic(tmp_path: Path) -> None:
    payload = csv_zip_bytes()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-length": str(len(payload))}, content=payload
        )
    )
    destination = tmp_path / "dengue.csv.zip"

    receipt = download_csv_zip(
        "https://example.test/dengue.csv.zip",
        destination,
        max_bytes=len(payload),
        transport=transport,
    )

    assert destination.read_bytes() == payload
    assert receipt.bytes_downloaded == len(payload)
    assert receipt.sha256 == sha256(payload).hexdigest()
    assert receipt.extracted_at.tzinfo is not None


def test_download_rejects_redirect_and_oversized_response(tmp_path: Path) -> None:
    redirect = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "https://other.test/file.csv.zip"})
    )
    with pytest.raises(UnsafeDownloadError, match="Redirecionamentos"):
        download_csv_zip(
            "https://example.test/file.csv.zip",
            tmp_path / "redirect.csv.zip",
            max_bytes=100,
            transport=redirect,
        )

    oversized = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-length": "101"}, content=b"x")
    )
    with pytest.raises(DownloadLimitError, match="Content-Length"):
        download_csv_zip(
            "https://example.test/file.csv.zip",
            tmp_path / "large.csv.zip",
            max_bytes=100,
            transport=oversized,
        )


def test_parser_uses_polars_and_rejects_unsafe_archives() -> None:
    frame = parse_csv_zip_bytes(csv_zip_bytes())
    assert frame.to_dicts() == [{"codigo": "sdigi008", "valor": 10}]

    with pytest.raises(UnsafeDownloadError, match="exatamente um"):
        parse_csv_zip_bytes(csv_zip_bytes(additional_csv=True))
    with pytest.raises(UnsafeDownloadError, match="ZIP válido"):
        parse_csv_zip_bytes(b"not-a-zip")
    with pytest.raises(DownloadLimitError, match="descompactado"):
        parse_csv_zip_bytes(csv_zip_bytes(), max_uncompressed_bytes=4)
