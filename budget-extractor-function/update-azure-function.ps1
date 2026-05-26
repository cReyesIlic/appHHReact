[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ResourceGroup = "appHH",
    [string]$FunctionAppName = "apphh-budget-extractor",
    [string]$FunctionProjectPath = "",
    [string]$BackendAppName = "apphhshimin",
    [switch]$UpdateBackendSettings,
    [string]$ApiKey,
    [switch]$SkipAppSettings,
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($FunctionProjectPath)) {
    $FunctionProjectPath = $PSScriptRoot
}

function Invoke-Step {
    param(
        [string]$Description,
        [scriptblock]$Action
    )

    Write-Host "`n==> $Description" -ForegroundColor Cyan
    & $Action
}

function Get-RequiredCommand {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "No se encontró el comando requerido: $Name"
    }
    return $command
}

Get-RequiredCommand az | Out-Null
Get-RequiredCommand func | Out-Null

if (-not (Test-Path $FunctionProjectPath)) {
    throw "No existe la ruta del proyecto Function: $FunctionProjectPath"
}

$resolvedProjectPath = (Resolve-Path $FunctionProjectPath).Path
$functionUrl = "https://$FunctionAppName.azurewebsites.net"

Invoke-Step "Verificando Function App destino" {
    $exists = az functionapp show -g $ResourceGroup -n $FunctionAppName --query name -o tsv 2>$null
    if (-not $exists) {
        throw "No existe la Function App '$FunctionAppName' en el resource group '$ResourceGroup'."
    }
    Write-Host "Function App encontrada: $exists"
}

if (-not $SkipAppSettings) {
    Invoke-Step "Asegurando app settings de build/runtime" {
        $settings = @(
            "AzureWebJobsFeatureFlags=EnableWorkerIndexing",
            "SCM_DO_BUILD_DURING_DEPLOYMENT=true",
            "ENABLE_ORYX_BUILD=true"
        )
        if ($ApiKey) {
            $settings += "BUDGET_EXTRACTOR_API_KEY=$ApiKey"
        }

        if ($PSCmdlet.ShouldProcess($FunctionAppName, "Actualizar app settings de la Function")) {
            az functionapp config appsettings set -g $ResourceGroup -n $FunctionAppName --settings $settings | Out-Null
        }
    }
}

if (-not $SkipPublish) {
    Invoke-Step "Publicando código de la Function" {
        Push-Location $resolvedProjectPath
        try {
            if ($PSCmdlet.ShouldProcess($FunctionAppName, "Publicar budget extractor con Azure Functions Core Tools")) {
                func azure functionapp publish $FunctionAppName --python
            }
        }
        finally {
            Pop-Location
        }
    }
}

if ($UpdateBackendSettings) {
    Invoke-Step "Sincronizando app settings del backend" {
        $backendSettings = @("BUDGET_EXTRACTOR_URL=$functionUrl")
        if ($ApiKey) {
            $backendSettings += "BUDGET_EXTRACTOR_API_KEY=$ApiKey"
        }

        if ($PSCmdlet.ShouldProcess($BackendAppName, "Actualizar app settings del backend")) {
            az webapp config appsettings set -g $ResourceGroup -n $BackendAppName --settings $backendSettings | Out-Null
            az webapp restart -g $ResourceGroup -n $BackendAppName | Out-Null
        }
    }
}

Invoke-Step "Resumen final" {
    Write-Host "Function App: $FunctionAppName"
    Write-Host "Resource Group: $ResourceGroup"
    Write-Host "Project Path: $resolvedProjectPath"
    Write-Host "URL: $functionUrl"
    if ($UpdateBackendSettings) {
        Write-Host "Backend sincronizado: $BackendAppName"
    }
    if ($ApiKey) {
        Write-Host "API key aplicada durante la actualización."
    }
}
