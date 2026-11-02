"""Server MCP Visual FoxPro indipendente dal Gitea MCP ufficiale."""
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import MCPServer

from vfp_core import read_vfp

# Sempre relativo a questo file, non alla working directory del client MCP.
load_dotenv(Path(__file__).with_name(".env"))

mcp = MCPServer("Visual FoxPro Gitea Reader")


@mcp.tool()
def get_vfp_file_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str = "main",
    start_line: int = 1,
    max_lines: int = 250,
) -> dict:
    """Legge sorgenti Visual FoxPro da Gitea in SOLA LETTURA.

    Per SCX, VCX, FRX, LBX, MNX, PJX, DBC e DBF recupera il binario
    (incluso l'eventuale memo) ed esegue FoxBin2Prg BIN2PRG su Windows.
    Per PRG e altri file testuali restituisce direttamente il contenuto.
    Usa ref=commit SHA per una revisione riproducibile, e start_line
    per leggere altre pagine. Non modifica mai il repository.
    """
    return read_vfp(owner, repo, path, ref, start_line, max_lines)


if __name__ == "__main__":
    mcp.run()  # stdio; nessun print su stdout
