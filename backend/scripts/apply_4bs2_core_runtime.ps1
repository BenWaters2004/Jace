param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$RepoRoot    = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$Timestamp   = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot  = Join-Path $ScriptDir "backups\4bs2-$Timestamp"

function Read-Text {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Required file not found: $Path"
    }

    $text = [System.IO.File]::ReadAllText($Path)

    # Normalise while patching. Files are written as UTF-8 without BOM.
    return ($text -replace "`r`n", "`n")
}

function Write-Text {
    param(
        [string]$Path,
        [string]$Text
    )

    if ($DryRun) {
        Write-Host "[DRY RUN] Would update: $Path" -ForegroundColor Cyan
        return
    }

    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

    if (Test-Path $Path) {
        $backupName = (Split-Path -Leaf $Path)
        $backupPath = Join-Path $BackupRoot $backupName
        Copy-Item $Path $backupPath -Force
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)

    Write-Host "[UPDATED] $Path" -ForegroundColor Green
}

function Replace-Between {
    param(
        [string]$Text,
        [string]$StartMarker,
        [string]$EndMarker,
        [string]$Replacement,
        [string]$Label
    )

    $start = $Text.IndexOf($StartMarker)

    if ($start -lt 0) {
        throw "Could not find start marker for $Label"
    }

    $end = $Text.IndexOf($EndMarker, $start)

    if ($end -lt 0) {
        throw "Could not find end marker for $Label"
    }

    return (
        $Text.Substring(0, $start) +
        $Replacement +
        $Text.Substring($end)
    )
}

Write-Host ""
Write-Host "Jace 4B.S2 - Core Runtime Modes" -ForegroundColor Magenta
Write-Host "Backend: $BackendRoot"
Write-Host "Mode: $(if ($DryRun) { 'DRY RUN' } else { 'APPLY' })"
Write-Host ""

# ---------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------

$configPath = Join-Path $BackendRoot "jace\config.py"
$config = Read-Text $configPath

if (-not $config.Contains("from typing import Literal")) {
    if (-not $config.Contains("from pathlib import Path`n")) {
        throw "Could not locate pathlib import in config.py"
    }

    $config = $config.Replace(
        "from pathlib import Path`n",
        "from pathlib import Path`nfrom typing import Literal`n"
    )
}

if (-not $config.Contains("# JACE_4BS2_RUNTIME_CONFIG")) {
    $runtimeFields = @"

    # JACE_4BS2_RUNTIME_CONFIG
    # Jace Core may run locally or on a central server. Local remains the
    # default so existing desktop development continues to work unchanged.
    mode: Literal["local", "server"] = "local"
    host: str = "127.0.0.1"
    port: int = 8000
    server_name: str = "Jace Core"
    public_url: str = ""

    # Leave blank to use data/jace.db through async SQLite.
    # A future server deployment can use:
    # postgresql+asyncpg://user:password@host/database
    database_url: str = ""

    # Comma-separated browser/client origins. Local mode additionally allows
    # localhost and the standard Tauri origins through the local CORS regex.
    cors_allowed_origins: str = ""
"@

    $versionMatch = [regex]::Match(
        $config,
        '(?m)^    app_version: str = .+$'
    )

    if (-not $versionMatch.Success) {
        throw "Could not locate app_version in config.py"
    }

    $insertAt = $versionMatch.Index + $versionMatch.Length
    $config = $config.Insert($insertAt, $runtimeFields)
}

if (-not $config.Contains("# JACE_4BS2_RUNTIME_HELPERS")) {
    $helpers = @"
    # JACE_4BS2_RUNTIME_HELPERS

    @property
    def is_server_mode(self) -> bool:
        return self.mode == "server"

    @property
    def resolved_database_url(self) -> str:
        configured = self.database_url.strip()
        if configured:
            return configured

        return "sqlite+aiosqlite:///" + DATABASE_PATH.as_posix()

    @property
    def database_backend(self) -> str:
        scheme = self.resolved_database_url.split(":", 1)[0]
        return scheme.split("+", 1)[0]

    @property
    def configured_cors_origins(self) -> list[str]:
        origins: list[str] = []

        for item in self.cors_allowed_origins.split(","):
            origin = item.strip().rstrip("/")
            if origin and origin not in origins:
                origins.append(origin)

        return origins

"@

    $marker = "    model_config = SettingsConfigDict("

    $position = $config.IndexOf($marker)

    if ($position -lt 0) {
        throw "Could not locate model_config in config.py"
    }

    $config = $config.Insert($position, $helpers)
}

Write-Text $configPath $config

# ---------------------------------------------------------------------
# database.py
# ---------------------------------------------------------------------

$databasePath = Join-Path $BackendRoot "jace\database.py"
$database = Read-Text $databasePath

if (-not $database.Contains("# JACE_4BS2_DATABASE_RUNTIME")) {

    $oldImport = "from jace.config import DATABASE_PATH, DATA_DIRECTORY"

    if (-not $database.Contains($oldImport)) {
        throw "database.py config import has changed. Patch stopped safely."
    }

    $database = $database.Replace(
        $oldImport,
        "from jace.config import DATA_DIRECTORY, settings"
    )

    $databaseTop = @"
# JACE_4BS2_DATABASE_RUNTIME
DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

DATABASE_URL = settings.resolved_database_url

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
)

DATABASE_BACKEND = engine.url.get_backend_name()
IS_SQLITE = DATABASE_BACKEND == "sqlite"

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


if IS_SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, connection_record):
        del connection_record

        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


"@

    $database = Replace-Between `
        -Text $database `
        -StartMarker "DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)" `
        -EndMarker "async def _ensure_step4a5_columns" `
        -Replacement $databaseTop `
        -Label "database engine configuration"

    $migrationFunction = "async def _ensure_step4a5_columns(connection) -> None:`n"

    if (-not $database.Contains($migrationFunction)) {
        throw "Could not locate _ensure_step4a5_columns in database.py"
    }

    $database = $database.Replace(
        $migrationFunction,
        @"
async def _ensure_step4a5_columns(connection) -> None:
    # JACE_4BS2_SQLITE_COMPAT
    # This is an existing ad-hoc SQLite migration. Fresh PostgreSQL databases
    # receive the current schema from SQLAlchemy. Formal migrations arrive in
    # the later database-migrations phase.
    if not IS_SQLITE:
        return

"@
    )

    $newInit = @"
async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        if IS_SQLITE:
            await _ensure_step4a5_columns(connection)
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")


"@

    $database = Replace-Between `
        -Text $database `
        -StartMarker "async def init_database() -> None:" `
        -EndMarker "async def close_database() -> None:" `
        -Replacement $newInit `
        -Label "database initialisation"
}

Write-Text $databasePath $database

# ---------------------------------------------------------------------
# main.py
# ---------------------------------------------------------------------

$mainPath = Join-Path $BackendRoot "jace\main.py"
$main = Read-Text $mainPath

if ($main.Contains('description="Local backend for the Jace AI assistant."')) {
    $main = $main.Replace(
        'description="Local backend for the Jace AI assistant."',
        'description="Jace Core backend for the Jace AI assistant."'
    )
}

if (-not $main.Contains("# JACE_4BS2_MODE_AWARE_CORS")) {

    $cors = @"
# JACE_4BS2_MODE_AWARE_CORS
#
# Local mode keeps the existing localhost/Tauri behaviour.
#
# Server mode intentionally has no wildcard fallback. Browser origins must be
# explicitly configured through JACE_CORS_ALLOWED_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.configured_cors_origins,
    allow_origin_regex=(
        (
            r"^(http://localhost(:\d+)?|"
            r"http://127\.0\.0\.1(:\d+)?|"
            r"http://tauri\.localhost|"
            r"https://tauri\.localhost|"
            r"tauri://localhost)$"
        )
        if settings.mode == "local"
        else None
    ),
    allow_credentials=False,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Jace-Client-ID",
        "X-Jace-Request-ID",
    ],
)


"@

    $main = Replace-Between `
        -Text $main `
        -StartMarker "app.add_middleware(" `
        -EndMarker "app.include_router(system_router)" `
        -Replacement $cors `
        -Label "FastAPI CORS middleware"
}

if (-not $main.Contains("# JACE_4BS2_STARTUP_MODE")) {
    $lifespanMarker = "    del app`n"

    if (-not $main.Contains($lifespanMarker)) {
        throw "Could not locate lifespan startup marker in main.py"
    }

    $main = $main.Replace(
        $lifespanMarker,
        @"
    del app

    # JACE_4BS2_STARTUP_MODE
    logger.info(
        "Starting %s in %s mode",
        settings.server_name,
        settings.mode,
    )

"@
    )
}

Write-Text $mainPath $main

# ---------------------------------------------------------------------
# system.py
# ---------------------------------------------------------------------

$systemPath = Join-Path $BackendRoot "jace\api\system.py"
$system = Read-Text $systemPath

if (-not $system.Contains("# JACE_4BS2_RUNTIME_INFO")) {

    $rootEndpoint = @"
@router.get("/")
async def root():
    # JACE_4BS2_RUNTIME_INFO
    return {
        "name": settings.app_name,
        "server_name": settings.server_name,
        "version": settings.app_version,
        "status": "running",
        "mode": settings.mode,
        "public_url": settings.public_url or None,
        "database_backend": settings.database_backend,
    }


"@

    $system = Replace-Between `
        -Text $system `
        -StartMarker '@router.get("/")' `
        -EndMarker '@router.get("/health"' `
        -Replacement $rootEndpoint `
        -Label "system runtime endpoint"

    $system = $system.Replace(
        "database_path=str(DATABASE_PATH),",
        @"
database_path=(
                str(DATABASE_PATH)
                if settings.database_backend == "sqlite"
                else settings.database_backend
            ),
"@
    )
}

Write-Text $systemPath $system

# ---------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------

$requirementsPath = Join-Path $BackendRoot "requirements.txt"
$requirements = Read-Text $requirementsPath

if (-not $requirements.Contains("asyncpg")) {

    if (-not $requirements.Contains("aiosqlite`n")) {
        throw "Could not locate aiosqlite in requirements.txt"
    }

    $requirements = $requirements.Replace(
        "aiosqlite`n",
        @"
aiosqlite
# Phase 4B.S2 - PostgreSQL async driver for future server deployments.
asyncpg>=0.30,<1
"@
    )
}

Write-Text $requirementsPath $requirements

# ---------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------

$envExamplePath = Join-Path $BackendRoot ".env.example"
$envExample = Read-Text $envExamplePath

if (-not $envExample.Contains("# Phase 4B.S2 - Jace Core runtime")) {

    $runtimeEnv = @"
# ---------------------------------------------------------------------------
# Phase 4B.S2 - Jace Core runtime
# ---------------------------------------------------------------------------

# local  = current desktop/local backend behaviour
# server = centrally hosted Jace Core
JACE_MODE=local

# Used by the configuration-aware `python -m jace` launcher.
JACE_HOST=127.0.0.1
JACE_PORT=8000

JACE_SERVER_NAME=Jace Core

# Blank in local development.
# Future example:
# JACE_PUBLIC_URL=https://jace.example.com
JACE_PUBLIC_URL=

# Blank = existing data/jace.db SQLite database.
#
# Future PostgreSQL example:
# JACE_DATABASE_URL=postgresql+asyncpg://jace:password@127.0.0.1/jace
JACE_DATABASE_URL=

# Comma-separated explicit origins.
#
# Local mode automatically retains localhost and Tauri origins.
#
# Future server example:
# JACE_CORS_ALLOWED_ORIGINS=https://jace.example.com,tauri://localhost
JACE_CORS_ALLOWED_ORIGINS=

"@

    $envExample = $runtimeEnv + $envExample
}

Write-Text $envExamplePath $envExample

# ---------------------------------------------------------------------
# python -m jace launcher
# ---------------------------------------------------------------------

$launcherPath = Join-Path $BackendRoot "jace\__main__.py"

if (-not (Test-Path $launcherPath)) {

    $launcher = @"
"""Configuration-aware Jace Core launcher."""

import uvicorn

from jace.config import settings


def main() -> None:
    uvicorn.run(
        "jace.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
"@

    if ($DryRun) {
        Write-Host "[DRY RUN] Would create: $launcherPath" -ForegroundColor Cyan
    }
    else {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($launcherPath, $launcher, $utf8NoBom)

        Write-Host "[CREATED] $launcherPath" -ForegroundColor Green
    }
}
else {
    Write-Host "[SKIP] jace\__main__.py already exists." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "4B.S2 patch complete." -ForegroundColor Green

if (-not $DryRun) {
    Write-Host "Backups: $BackupRoot" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Next: run the validation commands shown with this patch." -ForegroundColor Cyan
