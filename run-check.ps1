$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path '.env')) {
    Copy-Item .env.example .env
    Write-Host 'Creato .env: INSERISCI i valori reali prima del test.'
}
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
Write-Host 'Per avviare lo stdio MCP: .\.venv\Scripts\python.exe server.py'
