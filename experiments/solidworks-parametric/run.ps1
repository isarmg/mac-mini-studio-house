param([switch]$CompileOnly, [ValidateSet('all', 'housing', 'base')][string]$Mode = 'all')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$prototypeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$prototypeBuild = Join-Path $prototypeRoot '.tmp/sw-parametric'
$prototypeOutput = Join-Path $prototypeRoot 'results/experimental/solidworks-parametric'
$prototypeInterop = 'C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/api/redist'
$prototypeFramework = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
New-Item -ItemType Directory -Path $prototypeBuild -Force | Out-Null
New-Item -ItemType Directory -Path $prototypeOutput -Force | Out-Null
$prototypeSources = @('Packet.cs', 'SwSession.cs', 'SwReadback.cs') | ForEach-Object { Join-Path $prototypeRoot ('tools/exact_native/' + $_) }
$prototypeSources += Join-Path $PSScriptRoot 'Prototype.cs'
$prototypeReferences = @('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll') | ForEach-Object { Join-Path $prototypeInterop $_ }
$prototypeReferences += Join-Path $prototypeFramework 'System.Core.dll'
$prototypeReferences += Join-Path $prototypeFramework 'System.Web.Extensions.dll'
$prototypeExecutable = Join-Path $prototypeBuild 'SwParametricPrototype.exe'
$prototypeArguments = @('/nologo', '/target:exe', '/platform:x64', ('/out:' + $prototypeExecutable))
$prototypeArguments += $prototypeReferences | ForEach-Object { '/reference:' + $_ }
$prototypeArguments += $prototypeSources
& (Join-Path $prototypeFramework 'csc.exe') @prototypeArguments
if ($LASTEXITCODE -ne 0) { throw 'Prototype compilation failed' }
foreach ($prototypeAssembly in @('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll')) {
    Copy-Item -LiteralPath (Join-Path $prototypeInterop $prototypeAssembly) -Destination $prototypeBuild -Force
}
if ($CompileOnly) { return }
$prototypeTimer = [Diagnostics.Stopwatch]::StartNew()
try {
    & $prototypeExecutable $prototypeRoot $prototypeOutput $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Prototype experiment failed; inspect the reported CAD step' }
    if ($Mode -eq 'all') {
        & python -B (Join-Path $PSScriptRoot 'verify.py')
        if ($LASTEXITCODE -ne 0) { throw 'Independent prototype verification failed' }
    }
    Write-Output ('Prototype elapsed seconds: ' + [math]::Round($prototypeTimer.Elapsed.TotalSeconds, 1))
}
finally {
    # Only this runner's three build files may be deleted; no recursive deletion.
    $prototypeResolvedBuild = [IO.Path]::GetFullPath($prototypeBuild)
    $prototypeExpectedBuild = [IO.Path]::GetFullPath((Join-Path $prototypeRoot '.tmp/sw-parametric'))
    if ($prototypeResolvedBuild -ne $prototypeExpectedBuild -or -not $prototypeResolvedBuild.StartsWith($prototypeRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw 'Build cleanup escaped the workspace'
    }
    foreach ($prototypeDirectory in @((Join-Path $prototypeRoot '.tmp'), $prototypeResolvedBuild)) {
        if ((Get-Item -LiteralPath $prototypeDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Build cleanup refuses reparse points'
        }
    }
    foreach ($prototypeFile in @('SwParametricPrototype.exe', 'SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll')) {
        $prototypeDelete = [IO.Path]::GetFullPath((Join-Path $prototypeResolvedBuild $prototypeFile))
        if ([IO.Path]::GetDirectoryName($prototypeDelete) -ne $prototypeResolvedBuild) { throw 'Unexpected build file path' }
        Remove-Item -LiteralPath $prototypeDelete -Force -ErrorAction SilentlyContinue
    }
    if ((Get-ChildItem -LiteralPath $prototypeResolvedBuild -Force | Measure-Object).Count -eq 0) {
        Remove-Item -LiteralPath $prototypeResolvedBuild -Force
    }
}
