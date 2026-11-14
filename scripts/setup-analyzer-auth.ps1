param(
  [string[]]$Contexts = @("docker-desktop", "kind-cilium-validation")
)

$ErrorActionPreference = "Stop"

function New-RandomToken {
  param([int]$ByteCount = 32)
  $bytes = New-Object byte[] $ByteCount
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function ConvertTo-SecretData {
  param([hashtable]$Values)
  $encoded = @{}
  foreach ($key in $Values.Keys) {
    $encoded[$key] = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$Values[$key]))
  }
  return $encoded
}

function Apply-Secret {
  param(
    [string]$Context,
    [string]$Namespace,
    [string]$Name,
    [hashtable]$Values
  )
  $manifest = @{
    apiVersion = "v1"
    kind = "Secret"
    metadata = @{ name = $Name; namespace = $Namespace }
    type = "Opaque"
    data = (ConvertTo-SecretData $Values)
  } | ConvertTo-Json -Depth 8

  $tempFile = Join-Path $env:TEMP ("traffic-secret-{0}.json" -f [guid]::NewGuid().ToString("N"))
  try {
    Set-Content -LiteralPath $tempFile -Value $manifest -Encoding ascii
    kubectl --context $Context apply -f $tempFile
    if ($LASTEXITCODE -ne 0) { throw "Could not apply Secret $Name to context $Context." }
  } finally {
    if (Test-Path -LiteralPath $tempFile) { Remove-Item -LiteralPath $tempFile -Force }
  }
}

$adminPassword = New-RandomToken
$viewerPassword = New-RandomToken
$sessionSecret = New-RandomToken
$internalApiToken = New-RandomToken
$metricsToken = New-RandomToken
$authValues = @{
  "admin-username" = "admin"
  "admin-password" = $adminPassword
  "viewer-username" = "viewer"
  "viewer-password" = $viewerPassword
  "session-secret" = $sessionSecret
  "internal-api-token" = $internalApiToken
  "metrics-token" = $metricsToken
}

foreach ($context in $Contexts) {
  Apply-Secret -Context $context -Namespace "smart-traffic" -Name "traffic-analyzer-auth" -Values $authValues
  if ($context -eq "docker-desktop") {
    kubectl --context $context get namespace monitoring *> $null
    if ($LASTEXITCODE -ne 0) {
      kubectl --context $context create namespace monitoring
      if ($LASTEXITCODE -ne 0) { throw "Could not create the monitoring namespace in context $context." }
    }
    Apply-Secret -Context $context -Namespace "monitoring" -Name "traffic-analyzer-auth-metrics" -Values @{ token = $metricsToken }
  }
}

Write-Host "Analyzer authentication Secrets were created. Save these credentials securely:"
Write-Host "Administrator username: admin"
Write-Host "Administrator password: $adminPassword"
Write-Host "Viewer username: viewer"
Write-Host "Viewer password: $viewerPassword"
