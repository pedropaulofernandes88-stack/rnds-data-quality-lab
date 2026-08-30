"""Configuração local e determinística do laboratório."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Caminhos e limites usados pelo pipeline.

    A configuração padrão funciona sem variáveis de ambiente e mantém todos os
    artefatos gerados fora do controle de versão.
    """

    project_root: Path
    data_dir: Path
    database_path: Path
    artifacts_dir: Path
    manifest_path: Path
    minimum_public_cell_size: int = 5
    contract_version: str = "rnds-lab-contract/1.0.0"

    @classmethod
    def load(cls, project_root: Path | None = None) -> Settings:
        root_override = os.getenv("RNDS_LAB_HOME")
        root = (
            Path(root_override).expanduser().resolve()
            if root_override
            else (project_root or Path.cwd()).resolve()
        )
        data_dir = root / "data"
        database_override = os.getenv("RNDS_LAB_DB")
        database_path = (
            Path(database_override).expanduser().resolve()
            if database_override
            else data_dir / "generated" / "rnds_lab.duckdb"
        )
        return cls(
            project_root=root,
            data_dir=data_dir,
            database_path=database_path,
            artifacts_dir=root / "artifacts",
            manifest_path=data_dir / "sources.yml",
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "quarantine").mkdir(parents=True, exist_ok=True)
