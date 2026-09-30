param([Parameter(Mandatory=$true)][string]$InputGeometry,[Parameter(Mandatory=$true)][string]$OutputModel,[Parameter(Mandatory=$true)][string]$Report,[switch]$WriteParasolid)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$rhinoSystem='C:\Program Files\Rhino 8\System'
$env:PATH=$rhinoSystem+';'+$env:PATH
Add-Type -Path (Join-Path $rhinoSystem 'RhinoCommon.dll')
Add-Type -Path @((Join-Path $PSScriptRoot 'Packet.cs'),(Join-Path $PSScriptRoot 'RhinoExact.cs')) -ReferencedAssemblies @((Join-Path $rhinoSystem 'RhinoCommon.dll'),'System.Core','System.Drawing','System.Web.Extensions')
if($WriteParasolid){[RhinoExact]::ExportParasolid($InputGeometry,$OutputModel,$Report)}else{[RhinoExact]::Run($InputGeometry,$OutputModel,$Report)}
