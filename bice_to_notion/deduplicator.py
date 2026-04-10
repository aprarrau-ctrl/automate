"""
Evita procesar el mismo email dos veces usando un archivo de IDs procesados.
"""
from pathlib import Path


class Deduplicator:
    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ids: set[str] = self._load()

    def _load(self) -> set[str]:
        if not self._path.exists():
            return set()
        return {line.strip() for line in self._path.read_text().splitlines() if line.strip()}

    def is_processed(self, gmail_id: str) -> bool:
        return gmail_id in self._ids

    def mark_processed(self, gmail_id: str) -> None:
        if gmail_id in self._ids:
            return
        self._ids.add(gmail_id)
        with self._path.open("a") as f:
            f.write(gmail_id + "\n")
