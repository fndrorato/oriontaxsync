"""Consulta, valida e baixa releases do OrionTax Sync."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    installer_url: str
    sha256: str
    size: int
    mandatory: bool = False
    minimum_supported_version: str = "0"
    release_notes: str = ""


class UpdateChecker:
    def __init__(self, manifest_url: str, current_version: str, timeout: int = 15):
        self.manifest_url = manifest_url
        self.current_version = Version(current_version)
        self.timeout = timeout

    @staticmethod
    def _https(url: str):
        if urlparse(url).scheme != "https":
            raise UpdateError("Atualizações exigem uma URL HTTPS.")

    def check(self):
        self._https(self.manifest_url)
        with urlopen(Request(self.manifest_url, headers={"Accept": "application/json"}), timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        try:
            info = UpdateInfo(
                version=str(payload["version"]), installer_url=str(payload["installer_url"]),
                sha256=str(payload["sha256"]).lower(), size=int(payload["size"]),
                mandatory=bool(payload.get("mandatory", False)),
                minimum_supported_version=str(payload.get("minimum_supported_version", "0")),
                release_notes=str(payload.get("release_notes", "")),
            )
            remote = Version(info.version)
        except (KeyError, TypeError, ValueError, InvalidVersion) as exc:
            raise UpdateError(f"Manifesto de atualização inválido: {exc}") from exc
        self._https(info.installer_url)
        if len(info.sha256) != 64 or any(c not in "0123456789abcdef" for c in info.sha256):
            raise UpdateError("SHA-256 inválido no manifesto.")
        return info if remote > self.current_version else None

    def download(self, info: UpdateInfo) -> Path:
        self._https(info.installer_url)
        update_dir = Path(tempfile.mkdtemp(prefix="oriontax-update-"))
        target = update_dir / f"OrionTaxSync_Setup_{info.version}.exe"
        digest = hashlib.sha256()
        total = 0
        with urlopen(Request(info.installer_url), timeout=max(self.timeout, 60)) as response, target.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk); digest.update(chunk); total += len(chunk)
        if total != info.size:
            target.unlink(missing_ok=True)
            raise UpdateError(f"Tamanho inválido: esperado {info.size}, recebido {total}.")
        if digest.hexdigest().lower() != info.sha256:
            target.unlink(missing_ok=True)
            raise UpdateError("O instalador baixado falhou na validação SHA-256.")
        return target
