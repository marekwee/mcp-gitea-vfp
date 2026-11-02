"""Servizi di sola lettura per Visual FoxPro (Gitea + FoxBin2Prg)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

# Estensione binaria -> (estensione testuale, estensione memo obbligatoria o facoltativa)
BINARIES: dict[str, tuple[str, str | None, bool]] = {
    ".scx": (".sc2", ".sct", True),
    ".vcx": (".vc2", ".vct", True),
    ".frx": (".fr2", ".frt", True),
    ".lbx": (".lb2", ".lbt", True),
    ".mnx": (".mn2", ".mnt", True),
    ".pjx": (".pj2", ".pjt", True),
    ".dbc": (".dc2", ".dct", True),
    ".dbf": (".db2", ".fpt", False),
    ".mem": (".me2", None, False),
    ".fky": (".fk2", None, False),
}
TEXT_EXTENSIONS = {
    ".prg", ".h", ".qpr", ".mpr", ".spr", ".txt", ".sql",
    ".ini", ".cfg", ".xml", ".json", ".sc2", ".vc2", ".fr2",
    ".lb2", ".mn2", ".pj2", ".dc2", ".db2", ".me2", ".fk2",
}
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MAX_OUTPUT_BYTES = 30 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class VFPError(ValueError):
    """Errore di configurazione, rete o conversione riferibile all'utente."""


def valid_repo_piece(value: str, label: str) -> str:
    if not NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise VFPError(f"{label} non valido")
    return value


def valid_repo_path(path: str) -> PurePosixPath:
    """Il percorso è un path *Git*, mai un path locale."""
    if not isinstance(path, str) or not path or len(path) > 512:
        raise VFPError("Percorso repository vuoto o troppo lungo")
    if path.startswith("/") or "\\" in path or ":" in path or "\x00" in path:
        raise VFPError("Usa un percorso relativo POSIX, es. forms/clienti.scx")
    parts = path.split("/")
    if any(p in {"", ".", ".."} or any(ord(c) < 32 for c in p) for p in parts):
        raise VFPError("Il percorso contiene componenti non consentiti")
    filename = parts[-1]
    if filename.split(".")[0].upper() in WINDOWS_RESERVED or filename.endswith((".", " ")):
        raise VFPError("Nome file non supportato su Windows")
    return PurePosixPath(path)


def validate_ref(ref: str) -> str:
    if not ref or len(ref) > 200 or any(ord(c) < 32 for c in ref):
        raise VFPError("Ref Git non valido")
    return ref


@dataclass(frozen=True)
class Settings:
    gitea_url: str
    token: str
    foxbin_exe: Path
    encoding: str
    allowed_repos: frozenset[str]
    timeout: int = 45

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.environ.get("GITEA_URL", "").rstrip("/")
        token = os.environ.get("GITEA_TOKEN", "")
        exe = Path(os.environ.get("FOXBIN2PRG_EXE", ""))
        encoding = os.environ.get("VFP_ENCODING", "cp1252")
        allowed = frozenset(x.strip().lower() for x in os.environ.get("VFP_ALLOWED_REPOS", "").split(",") if x.strip())
        try:
            timeout = int(os.environ.get("VFP_CONVERT_TIMEOUT", "45"))
        except ValueError as exc:
            raise VFPError("VFP_CONVERT_TIMEOUT deve essere un intero") from exc
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise VFPError("GITEA_URL deve essere un URL HTTP(S) valido, senza credenziali o query")
        if not token:
            raise VFPError("Imposta GITEA_TOKEN con un token di sola lettura")
        if not allowed:
            raise VFPError("Configura VFP_ALLOWED_REPOS (es. azienda/gestionale-vfp)")
        if not exe.is_file() or exe.suffix.lower() != ".exe":
            raise VFPError("FOXBIN2PRG_EXE deve puntare all'eseguibile Windows esistente")
        if not 1 <= timeout <= 180:
            raise VFPError("VFP_CONVERT_TIMEOUT deve essere tra 1 e 180 secondi")
        import codecs
        try:
            codecs.lookup(encoding)
        except LookupError as exc:
            raise VFPError(f"VFP_ENCODING sconosciuta: {encoding}") from exc
        return cls(url, token, exe.resolve(), encoding, allowed, timeout)


class _NoRedirect(HTTPRedirectHandler):
    """Evita che il token Gitea venga inoltrato a host di redirect esterni."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GiteaReader:
    def __init__(self, settings: Settings):
        self.settings = settings

    def read(self, owner: str, repo: str, path: str, ref: str, optional: bool = False) -> bytes | None:
        valid_repo_piece(owner, "owner")
        valid_repo_piece(repo, "repo")
        repository = f"{owner}/{repo}".lower()
        if self.settings.allowed_repos and repository not in self.settings.allowed_repos:
            raise VFPError(f"Repository non autorizzato: {owner}/{repo}")
        repo_path = valid_repo_path(path)
        validate_ref(ref)
        encoded_path = "/".join(quote(x, safe="") for x in repo_path.parts)
        url = (f"{self.settings.gitea_url}/api/v1/repos/"
               f"{quote(owner, safe='')}/{quote(repo, safe='')}/raw/{encoded_path}"
               f"?{urlencode({'ref': ref})}")
        req = Request(url, headers={
            "Authorization": f"token {self.settings.token}",
            "Accept": "application/octet-stream",
            "User-Agent": "visualfoxpro-mcp/0.1",
        })
        try:
            with build_opener(_NoRedirect).open(req, timeout=20) as response:
                data = response.read(MAX_FILE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404 and optional:
                return None
            if exc.code == 404:
                raise VFPError(f"File non trovato in Gitea: {path} (ref {ref})") from exc
            raise VFPError(f"Gitea HTTP {exc.code} per {path}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise VFPError(f"Impossibile leggere {path} da Gitea: {type(exc).__name__}") from exc
        if len(data) > MAX_FILE_BYTES:
            raise VFPError(f"File troppo grande (> {MAX_FILE_BYTES // (1024 * 1024)} MiB): {path}")
        return data


def memo_candidates(path: PurePosixPath, memo_ext: str) -> list[str]:
    """Prova prima la stessa capitalizzazione del suffisso, poi l'alternativa."""
    suffix = memo_ext.upper() if path.suffix == path.suffix.upper() else memo_ext
    base = str(path.with_suffix(""))
    return list(dict.fromkeys([base + suffix, base + memo_ext, base + memo_ext.upper()]))


def fetch_sources(reader: GiteaReader, owner: str, repo: str, path: str, ref: str) -> tuple[dict[str, bytes], list[str]]:
    remote = valid_repo_path(path)
    ext = remote.suffix.lower()
    if ext not in BINARIES and ext not in TEXT_EXTENSIONS:
        raise VFPError(f"Estensione {ext or '(assente)'} non supportata")
    main = reader.read(owner, repo, path, ref)
    assert main is not None
    files = {remote.name: main}
    downloaded = [path]
    if ext in BINARIES:
        _, memo_ext, required = BINARIES[ext]
        if memo_ext:
            memo_data = None
            memo_path = ""
            for candidate in memo_candidates(remote, memo_ext):
                memo_data = reader.read(owner, repo, candidate, ref, optional=True)
                if memo_data is not None:
                    memo_path = candidate
                    break
            if memo_data is None and required:
                raise VFPError(f"Manca il file memo associato a {path} ({memo_ext}); conversione annullata")
            if memo_data is not None:
                # Nome del file memo con il medesimo stem del file principale
                local_memo = remote.with_suffix(memo_ext).name
                files[local_memo] = memo_data
                downloaded.append(memo_path)
    if sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise VFPError("Dimensione complessiva dei file oltre 24 MiB")
    return files, downloaded


def decode_text(data: bytes, encoding: str) -> str:
    # utf-8-sig gestisce anche l'eventuale BOM.
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode(encoding, errors="replace")


def convert_file(settings: Settings, main_name: str, files: dict[str, bytes]) -> tuple[str, str]:
    ext = Path(main_name).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return main_name, decode_text(files[main_name], settings.encoding)
    if ext not in BINARIES:
        raise VFPError(f"Formato non supportato: {ext}")
    out_ext = BINARIES[ext][0]
    with tempfile.TemporaryDirectory(prefix="vfp-mcp-") as tmp:
        temp_dir = Path(tmp)
        for filename, data in files.items():
            # La funzione accetta solo nomi base, validati prima di scrivere.
            if Path(filename).name != filename or filename in (".", "..") or "\\" in filename or ":" in filename:
                raise VFPError("Nome temporaneo non valido")
            (temp_dir / filename).write_bytes(data)
        input_file = temp_dir / main_name
        # Non si converte mai una directory o un progetto intero con '*'.
        argv = [str(settings.foxbin_exe), str(input_file), "BIN2PRG"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                argv, cwd=settings.foxbin_exe.parent,
                capture_output=True, timeout=settings.timeout,
                creationflags=flags, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VFPError(f"FoxBin2Prg timeout ({settings.timeout}s)") from exc
        except OSError as exc:
            raise VFPError(f"Avvio FoxBin2Prg fallito: {type(exc).__name__}") from exc
        if result.returncode != 0:
            detail = decode_text((result.stderr + b"\n" + result.stdout)[:1200], settings.encoding)
            raise VFPError(f"FoxBin2Prg ErrorLevel={result.returncode}: {detail.strip()}")
        output_file = temp_dir / (Path(main_name).stem + out_ext)
        if not output_file.is_file():
            raise VFPError(f"FoxBin2Prg ha terminato senza generare {output_file.name}. "
                           "Controlla la configurazione delle estensioni e dei messaggi interattivi.")
        if output_file.stat().st_size > MAX_OUTPUT_BYTES:
            raise VFPError("Output della conversione troppo grande (>30 MiB)")
        return output_file.name, decode_text(output_file.read_bytes(), settings.encoding)


def read_vfp(owner: str, repo: str, path: str, ref: str = "main", start_line: int = 1, max_lines: int = 250) -> dict:
    """Entry point esposto dal tool MCP; pagina il testo *dopo* la conversione."""
    if start_line < 1 or not 1 <= max_lines <= 1000:
        raise VFPError("start_line >= 1 e max_lines tra 1 e 1000")
    settings = Settings.from_env()
    files, sources = fetch_sources(GiteaReader(settings), owner, repo, path, ref)
    generated, text = convert_file(settings, PurePosixPath(path).name, files)
    lines = text.splitlines()
    idx = start_line - 1
    selected = lines[idx:idx + max_lines]
    return {
        "owner": owner, "repo": repo, "path": path, "ref": ref,
        "converted_to": generated, "source_files": sources,
        "encoding_fallback": settings.encoding,
        "total_lines": len(lines), "start_line": start_line,
        "returned_lines": len(selected),
        "next_start_line": start_line + len(selected) if idx + len(selected) < len(lines) else None,
        "text": "\n".join(selected),
    }
