# Bharat Police Intelligence - one-click local start for Windows (PowerShell).
# Usage:  powershell -ExecutionPolicy Bypass -File .\start.ps1  [-Seed]
param([switch]$Seed)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example (edit SECRET_KEY!)" }

Write-Host "1/5 Starting PostgreSQL + pgvector (Docker)..."
docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw "Docker is required for the database. Start Docker Desktop and retry." }

Write-Host "2/5 Python environment..."
if (-not (Test-Path backend\.venv)) { py -3.11 -m venv backend\.venv; if ($LASTEXITCODE -ne 0) { python -m venv backend\.venv } }
$py = "backend\.venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r backend\requirements.txt
& $py -c "import sentence_transformers" 2>$null
if ($LASTEXITCODE -ne 0) {
  & $py -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu
  & $py -m pip install -q -r backend\requirements-ml.txt
}

Write-Host "3/5 Database migrations..."
Start-Sleep -Seconds 3
Push-Location backend; & ..\$py -m alembic upgrade head; Pop-Location

if ($Seed) {
  Write-Host "Generating and loading the synthetic demo case (downloads models on first run)..."
  & $py scripts\generate_sample_data.py
  Push-Location backend
  & ..\$py -m app.cli download-models --yes
  & ..\$py -m app.cli seed-demo
  Pop-Location
}

Write-Host "4/5 Starting API on http://localhost:8000 ..."
Start-Process -FilePath (Resolve-Path $py) -ArgumentList "-m","uvicorn","app.main:app","--port","8000" -WorkingDirectory (Resolve-Path backend)

Write-Host "5/5 Starting frontend on http://localhost:5173 ..."
Push-Location frontend
if (-not (Test-Path node_modules)) { npm install }
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm run dev"
Pop-Location

Write-Host ""
Write-Host "Open http://localhost:5173 . Make sure Ollama is running:  ollama serve  /  ollama pull llama3.2:3b"
