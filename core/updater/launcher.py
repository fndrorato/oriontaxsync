"""Inicialização segura do instalador depois do download validado."""
import os
from pathlib import Path
import subprocess
import sys


def launch_installer(installer: Path):
    if sys.platform != "win32":
        raise RuntimeError("A instalação automática está disponível somente no Windows.")
    installer = Path(installer).resolve(strict=True)
    if installer.suffix.lower() != ".exe":
        raise ValueError("O pacote de atualização não é um executável Windows.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
         "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
        cwd=str(installer.parent), close_fds=True, creationflags=flags,
    )
