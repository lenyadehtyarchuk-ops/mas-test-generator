$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
        throw 'Created .env. Set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL, then run again.'
    }
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop in Linux containers mode first.' }
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration.' }
    docker compose up --build --detach --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Inspect docker compose logs.' }
    Write-Host 'MAS API: http://127.0.0.1:8000/docs'
} finally { Pop-Location }
