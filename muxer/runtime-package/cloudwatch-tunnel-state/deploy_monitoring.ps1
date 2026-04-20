param(
  [string]$FunctionName = "vpn-tunnel-state-publisher",
  [string]$Namespace = "VPN/TunnelState",
  [string]$Region = "us-east-1",
  [string]$DashboardPrefix = "VPN-Tunnel",
  [string]$TopologyPath = "",
  [string]$OutputDir = "",
  [switch]$SkipInvoke
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $TopologyPath) {
  $TopologyPath = Join-Path $root "monitoring_topology.json"
}
if (-not $OutputDir) {
  $OutputDir = Join-Path $root "build"
}

$TopologyPath = [System.IO.Path]::GetFullPath($TopologyPath)
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

if (-not (Test-Path $TopologyPath)) {
  throw "Topology file not found: $TopologyPath"
}

if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$lambdaSource = Join-Path $root "lambda_function.py"
$packagedTopologyPath = Join-Path $OutputDir "monitoring_topology.json"
$zipPath = Join-Path $OutputDir "vpn-tunnel-state-publisher.zip"
$generateDashboards = Join-Path $root "generate_dashboards.py"

Write-Host "[1/5] Generating dashboard JSON artifacts from topology..."
python $generateDashboards --namespace $Namespace --region $Region --topology $TopologyPath --output-dir $OutputDir --dashboard-prefix $DashboardPrefix

Write-Host "[2/5] Packaging Lambda code and topology..."
Copy-Item -Path $TopologyPath -Destination $packagedTopologyPath -Force
if (Test-Path $zipPath) {
  Remove-Item $zipPath -Force
}
Compress-Archive -Path @($lambdaSource, $packagedTopologyPath) -DestinationPath $zipPath -Force

Write-Host "[3/5] Updating Lambda function code and config..."
aws lambda update-function-code `
  --region $Region `
  --function-name $FunctionName `
  --zip-file ("fileb://{0}" -f $zipPath) `
  --output json | Out-Null

aws lambda update-function-configuration `
  --region $Region `
  --function-name $FunctionName `
  --environment "Variables={NAMESPACE=$Namespace,TOPOLOGY_PATH=/var/task/monitoring_topology.json}" `
  --output json | Out-Null

if (-not $SkipInvoke) {
  Write-Host "[4/5] Invoking Lambda to publish fresh metrics..."
  aws lambda invoke `
    --region $Region `
    --function-name $FunctionName `
    --payload '{}' `
    (Join-Path $OutputDir "lambda-invoke-output.json") `
    --output json | Out-Null
}
else {
  Write-Host "[4/5] Skipping Lambda invoke..."
}

Write-Host "[5/5] Publishing dashboards..."
$topology = Get-Content -Path $TopologyPath | ConvertFrom-Json

$dashboardMap = @{}
$dashboardMap["$DashboardPrefix-Constant-State"] = Join-Path $OutputDir "dashboard-vpn-tunnel-overview.json"
$dashboardMap["$DashboardPrefix-Muxer-$($topology.muxer.name)"] = Join-Path $OutputDir ("dashboard-vpn-muxer-{0}.json" -f $topology.muxer.name)
foreach ($hub in $topology.hubs) {
  $dashboardMap["$DashboardPrefix-Hub-$($hub.name)"] = Join-Path $OutputDir ("dashboard-vpn-hub-{0}.json" -f $hub.name)
}

foreach ($dashboardName in $dashboardMap.Keys) {
  $dashboardBody = $dashboardMap[$dashboardName]
  if (-not (Test-Path $dashboardBody)) {
    throw "Expected dashboard artifact not found: $dashboardBody"
  }
  aws cloudwatch put-dashboard `
    --region $Region `
    --dashboard-name $dashboardName `
    --dashboard-body ("file://{0}" -f $dashboardBody) `
    --output json | Out-Null
  Write-Host "  published $dashboardName"
}

Write-Host "Monitoring deployment complete."
