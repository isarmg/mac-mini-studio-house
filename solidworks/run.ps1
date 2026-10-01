param(
 [string]$Mode='all',
 [string]$Output,
 [string]$Evidence,
 [switch]$SkipPrepare,
 [switch]$CompileOnly
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$nativeRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$nativeBuild=Join-Path $nativeRoot '.tmp/solidworks-native/build'
$nativeReferences=Join-Path $nativeRoot '.tmp/solidworks-native/references'
if(-not $Output){$Output=Join-Path $nativeRoot '.tmp/solidworks-native/staging'}
if(-not $Evidence){$Evidence=Join-Path $nativeRoot '.tmp/solidworks-native/evidence'}
New-Item -ItemType Directory -Path $nativeBuild -Force | Out-Null
if(-not $SkipPrepare -and -not $CompileOnly){
 & python -B (Join-Path $PSScriptRoot 'prepare.py') $nativeReferences
 if($LASTEXITCODE -ne 0){throw 'Exact native references could not be prepared'}
}
$nativeInterop='C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/api/redist'
$nativeFramework=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
$nativeAssemblies=@('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swpublished.dll') | ForEach-Object {Join-Path $nativeInterop $_}
$nativeAssemblies+=@('System.Core.dll','System.Web.Extensions.dll','System.Windows.Forms.dll') | ForEach-Object {Join-Path $nativeFramework $_}
$nativeSources=@('Packet.cs','SwSession.cs','SwReadback.cs') | ForEach-Object {Join-Path $nativeRoot ('tools/exact_native/'+$_)}
$nativeSources+=@(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | Select-Object -ExpandProperty FullName)
$nativeDll=Join-Path $nativeBuild 'MacNativeFeatures.dll'
$nativeArguments=@('/nologo','/target:library','/platform:x64',('/out:'+$nativeDll))+@($nativeAssemblies | ForEach-Object {'/reference:'+$_})+$nativeSources
& (Join-Path $nativeFramework 'csc.exe') @nativeArguments
if($LASTEXITCODE -ne 0){throw 'Native feature component compilation failed'}
foreach($nativeFile in $nativeAssemblies | Select-Object -First 3){Copy-Item -LiteralPath $nativeFile -Destination $nativeBuild -Force}
if($CompileOnly){Write-Output ('Compiled native construction component: '+$nativeDll);return}
$nativeJob=@{
 root=$nativeRoot;input=(Join-Path $nativeReferences 'construction.json');mode=$Mode
 output=[IO.Path]::GetFullPath($Output);evidence=[IO.Path]::GetFullPath($Evidence)
 log=(Join-Path $nativeBuild 'build.log');status=(Join-Path $nativeBuild 'status.json')
 source_sha256=@{}
}
foreach($nativeFile in $nativeSources){$nativeRelative=$nativeFile.Substring($nativeRoot.Length+1).Replace('\','/');$nativeJob.source_sha256[$nativeRelative]=(Get-FileHash -LiteralPath $nativeFile -Algorithm SHA256).Hash.ToLowerInvariant()}
foreach($nativeFile in @('prepare.py','run.ps1','session.ps1')){
 $nativePath=Join-Path $PSScriptRoot $nativeFile
 $nativeJob.source_sha256['solidworks/'+$nativeFile]=(Get-FileHash -LiteralPath $nativePath -Algorithm SHA256).Hash.ToLowerInvariant()
}
[IO.File]::WriteAllText((Join-Path $nativeBuild 'job.json'),($nativeJob | ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($nativeJob.log,'',(New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($nativeJob.status,'{"completed":false}',(New-Object Text.UTF8Encoding($false)))
$nativeSpace=[RunspaceFactory]::CreateRunspace();$nativeSpace.ApartmentState='STA';$nativeSpace.ThreadOptions='ReuseThread';$nativeSpace.Open()
$nativeWorker=[PowerShell]::Create();$nativeWorker.Runspace=$nativeSpace
$null=$nativeWorker.AddScript([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'session.ps1'))).AddArgument($nativeBuild)
$nativePrinted=0
try {
 $nativePending=$nativeWorker.BeginInvoke()
 do {
  $nativeLines=@(Get-Content -LiteralPath $nativeJob.log -Encoding UTF8)
  while($nativePrinted -lt $nativeLines.Length){Write-Output $nativeLines[$nativePrinted];$nativePrinted++}
  $null=$nativePending.AsyncWaitHandle.WaitOne(250)
 } while(-not $nativePending.IsCompleted)
 $nativeWorker.EndInvoke($nativePending) | Out-Null
 $nativeLines=@(Get-Content -LiteralPath $nativeJob.log -Encoding UTF8)
 while($nativePrinted -lt $nativeLines.Length){Write-Output $nativeLines[$nativePrinted];$nativePrinted++}
 if($nativeWorker.HadErrors){throw ($nativeWorker.Streams.Error | Out-String)}
} finally {
 $nativeWorker.Dispose();$nativeSpace.Dispose()
}
