# Visual FoxPro MCP per Gitea (Windows)

MCP **separato** dal server Gitea: espone `get_vfp_file_contents`, legge file da Gitea
via REST API, converte i binari con FoxBin2Prg in una cartella temporanea e
restituisce testo paginato. Non effettua commit, push né scritture nel repository.

## Prerequisiti

- Windows e Python >=3.11.
- FoxBin2Prg.exe **funzionante**, compilato/distribuito per la tua versione Visual
  FoxPro, con `_FileName_Caps.exe` e runtime necessari installati. Scarica il
  pacchetto compilato/distribuito appropriato; il clone del codice sorgente potrebbe
  non contenere già l'EXE compilato.
- Un account Gitea con un token limitato ai repository necessari e ai soli permessi
  di lettura.

## Installazione (PowerShell)

```powershell
cd C:\vfp-gitea-mcp
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Modifica `.env` con URL Gitea, token, percorso effettivo dell'eseguibile e repository
consentiti. Usa in `GITEA_URL` la radice del server, eventualmente con il prefisso
applicativo, **non** aggiungere `/api/v1`. Per un server interno con HTTPS devi
avere un certificato CA attendibile in Windows/Python; non disabilitare la verifica TLS.

## Configurazione di FoxBin2Prg

FoxBin2Prg accetta `FoxBin2Prg.exe "C:\path\file.scx" BIN2PRG`.
Configura il **FoxBin2Prg.cfg accanto all'EXE** per evitare finestre/modali:

```
ShowProgressbar: 0
DontShowErrors: 1
ExtraBackupLevels: 0
OptimizeByFilestamp: 0
UseClassPerFile: 0
```

Integra queste opzioni nel tuo CFG anziché sovrascrivere tutto: altre opzioni,
in particolare `UseClassPerFile` ed estensioni di output, possono cambiare il
nome del file generato. L'implementazione cerca il default `form.sc2`, `class.vc2`,
etc. Se hai output personalizzati, modifica `BINARIES`/`convert_file`.

Prova prima **manualmente** in PowerShell su una COPIA di una coppia reale
`clienti.scx` + `clienti.sct` nella stessa directory:

```powershell
& 'C:\Tools\FoxBin2Prg\FoxBin2Prg.exe' 'C:\Temp\VFPTEST\clienti.scx' 'BIN2PRG'
$LASTEXITCODE
Get-Content 'C:\Temp\VFPTEST\clienti.sc2' -TotalCount 15
```

Non inserire `FoxBin2Prg.exe` nel repository MCP e non distribuire il runtime VFP
senza verificarne le licenze.

## Avvio

Nel client MCP che già usa Gitea, aggiungi **un secondo server** seguendo
`mcp-client-example.json`, correggendo i due percorsi assoluti. Il server usa
`stdio`: è avviato automaticamente dal client MCP, **senza porta HTTP**.

Per ispezionare il tool con MCP Inspector (richiede Node.js / `npx`):

```powershell
.\.venv\Scripts\mcp.exe dev server.py
```

`python server.py` senza client resta in ascolto su stdin: **non è un blocco**.
Non scrivere messaggi su stdout quando funziona in stdio.

## Esempio di tool

`get_vfp_file_contents(owner="azienda", repo="gestionale-vfp", path="forms/clienti.scx", ref="main", start_line=1, max_lines=200)`

Risposta (schema sintetico):

```json
{
  "owner": "azienda", "repo": "gestionale-vfp",
  "path": "forms/clienti.scx", "ref": "main",
  "converted_to": "clienti.sc2",
  "source_files": ["forms/clienti.scx", "forms/clienti.sct"],
  "encoding_fallback": "cp1252",
  "total_lines": 1240, "start_line": 1, "returned_lines": 200,
  "next_start_line": 201, "text": "..."
}
```

Il valore `ref` può indicare una branch, un tag o uno SHA. Per garantire che tutti
i file della coppia siano della stessa revisione, **usa uno SHA** quando possibile:
se la branch cambia esattamente fra le due richieste, potrebbero esserci contenuti
di commit diversi.

## Cosa gestisce

- Binari `.scx/.sct`, `.vcx/.vct`, `.frx/.frt`, `.lbx/.lbt`, `.mnx/.mnt`,
  `.pjx/.pjt`, `.dbc/.dct`, `.dbf` con `.fpt` facoltativo, `.mem`, `.fky`.
- Testo `.prg`, `.h`, `.qpr`, `.mpr`, `.spr`, `.sql`, `.txt`, `.ini`, `.cfg`, `.xml`,
  `.json` e le estensioni testuali FoxBin2Prg.
- Limiti: 12 MiB/file, 24 MiB richieste totali, 30 MiB output, timeout 45 secondi,
  paginazione 1-1000 righe/chiamata, cartella temporanea cancellata sempre.
- Codifica: prova prima UTF-8 e poi `VFP_ENCODING` (di default `cp1252`); per
  applicazioni che utilizzano DOS/OEM configura ad esempio `cp850`.

## Limiti importanti

- `.PJX` è convertito come singolo file: il server **non** importa automaticamente
  gli altri file citati dal progetto. Non usare la modalità batch `*` di FoxBin2Prg.
- Il repository Gitea distingue maiuscole/minuscole. Per i file memo si provano
  la capitalizzazione corrispondente, quella minuscola e quella maiuscola.
- I redirect HTTP da Gitea vengono rifiutati per non inoltrare il token a host terzi.
- Attenzione ai file memorizzati in Git LFS: l'endpoint `/raw` non sostituisce
  automaticamente il download del contenuto LFS; se usi LFS, adatta il lettore
  verso `/media` per la tua versione Gitea.
- Questa è una base di implementazione, **non ancora provata sul tuo Windows**
  con la tua distribuzione di FoxBin2Prg. Test locali verificano il flusso con un
  convertitore fittizio, non l'eseguibile reale.
- Il server non cerca classi/metodi al suo interno; si possono aggiungere tool
  `get_vfp_class` e `get_vfp_method` che riusano `read_vfp` e il parser `.VC2`.
- Usalo con un token Gitea di sola lettura e `VFP_ALLOWED_REPOS` (obbligatorio), meglio se con
  un account isolato. Non aggiungere strumenti di scrittura.

## Dove modificare

1. `vfp_core.py` / `BINARIES` e `memo_candidates`: aggiungere formati e file memo.
2. `vfp_core.py` / `GiteaReader.read`: cambiare la modalità di accesso a Gitea.
3. `vfp_core.py` / `convert_file`: modificare le opzioni del convertitore.
4. `vfp_core.py` / `read_vfp`: cambiare formato della risposta, limiti e paginazione.
5. `server.py`: registrare nuovi `@mcp.tool()`.

Fonti ufficiali:
- https://github.com/fdbozzo/foxbin2prg/blob/master/docs/FoxBin2Prg_Run.md
- https://docs.gitea.com/api/operations/repo-get-raw-file/
- https://py.sdk.modelcontextprotocol.io/

## License

This project is licensed under the GNU Affero
General Public License v3.0 (AGPL-3.0).
See the [LICENSE](LICENSE) file for details.

Copyright (C) 2026 Marek K. Wierzba (marek.wierzba@gmail.com)