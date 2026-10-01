param([string]$Output,[string]$Evidence,[switch]$CompileOnly)
$ErrorActionPreference='Stop'
$viewRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if(-not $Output){$Output=Join-Path $viewRoot 'results/SW'}
if(-not $Evidence){$Evidence=Join-Path $viewRoot 'validation/solidworks-native'}
$Output=[IO.Path]::GetFullPath($Output);$Evidence=[IO.Path]::GetFullPath($Evidence)
& (Join-Path $PSScriptRoot 'run.ps1') -CompileOnly
$viewBuild=Join-Path $viewRoot '.tmp/solidworks-native/inspection'
New-Item -ItemType Directory -Path $viewBuild -Force | Out-Null
$viewInterop='C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/api/redist'
$viewFramework=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
$viewAssemblies=@('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swpublished.dll') | ForEach-Object {Join-Path $viewInterop $_}
$viewNativeDll=Join-Path $viewRoot '.tmp/solidworks-native/build/MacNativeFeatures.dll'
Copy-Item -LiteralPath $viewNativeDll -Destination $viewBuild -Force
foreach($viewFile in $viewAssemblies){Copy-Item -LiteralPath $viewFile -Destination $viewBuild -Force}
$viewDll=Join-Path $viewBuild 'NativeInspection.dll'
$viewSource=Join-Path $PSScriptRoot 'inspection/InspectionAddin.cs'
$viewArguments=@('/nologo','/target:library','/platform:x64',('/out:'+$viewDll),('/reference:'+$viewNativeDll),('/reference:'+(Join-Path $viewFramework 'System.Windows.Forms.dll')))+@($viewAssemblies | ForEach-Object {'/reference:'+$_})+@($viewSource)
& (Join-Path $viewFramework 'csc.exe') @viewArguments
if($LASTEXITCODE -ne 0){throw 'Native inspection component compilation failed'}
if($CompileOnly){Write-Output 'Native default-session inspection component compiled';return}
$viewJob=@{output=$Output;evidence=$Evidence;log=(Join-Path $viewBuild 'inspection.log');status=(Join-Path $viewBuild 'status.json');source_sha256=@{}}
$viewSources=@($PSCommandPath,$viewSource)+@(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | Select-Object -ExpandProperty FullName)+@('Packet.cs','SwSession.cs','SwReadback.cs','SwInspectionHost.cs' | ForEach-Object {Join-Path $viewRoot ('tools/exact_native/'+$_)})
foreach($viewFile in $viewSources){$viewJob.source_sha256[$viewFile.Substring($viewRoot.Length+1).Replace('\','/')]=(Get-FileHash -LiteralPath $viewFile -Algorithm SHA256).Hash.ToLowerInvariant()}
[IO.File]::WriteAllText((Join-Path $viewBuild 'job.json'),($viewJob | ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($viewJob.status,'{"completed":false}',(New-Object Text.UTF8Encoding($false)))
Add-Type -Path @($viewAssemblies[0],$viewAssemblies[1])
Add-Type -Path @((Join-Path $viewRoot 'tools/exact_native/SwSession.cs'),(Join-Path $viewRoot 'tools/exact_native/SwInspectionHost.cs')) -ReferencedAssemblies @($viewAssemblies[0],$viewAssemblies[1],'System.Core')
$viewRegistry=[Microsoft.Win32.Registry]::CurrentUser
$viewKey='Software\Classes\CLSID\{2D37D692-0752-49ED-875D-3439B1904EA8}'
if($viewRegistry.OpenSubKey($viewKey)){throw 'Native inspection component is already registered; inspect ownership before reuse'}
$viewAssemblyName=[Reflection.AssemblyName]::GetAssemblyName($viewDll).FullName
$viewCodeBase='file:///'+$viewDll.Replace('\','/')
try {
 $viewEntry=$viewRegistry.CreateSubKey($viewKey);$viewEntry.SetValue('','InspectionAddin');$viewEntry.Close()
 foreach($viewSuffix in @('\InprocServer32','\InprocServer32\0.0.0.0')){
  $viewEntry=$viewRegistry.CreateSubKey($viewKey+$viewSuffix)
  $viewEntry.SetValue('','mscoree.dll');$viewEntry.SetValue('ThreadingModel','Both');$viewEntry.SetValue('Class','InspectionAddin')
  $viewEntry.SetValue('Assembly',$viewAssemblyName);$viewEntry.SetValue('RuntimeVersion','v4.0.30319');$viewEntry.SetValue('CodeBase',$viewCodeBase);$viewEntry.Close()
 }
 $viewEntry=$viewRegistry.CreateSubKey($viewKey+'\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}');$viewEntry.Close()
 [SwSession]::Begin()
 $viewLoad=[SwInspectionHost]::Load($viewDll)
 if($viewLoad -ne 0){throw ('Native inspection add-in did not load: '+$viewLoad)}
 [SwInspectionHost]::Unload($viewDll) | Out-Null
 $viewStatus=Get-Content -LiteralPath $viewJob.status -Raw -Encoding UTF8 | ConvertFrom-Json
 if(-not $viewStatus.completed -or -not $viewStatus.passed){throw $viewStatus.error}
 Write-Output 'Default-session inspection completed; native CAD files are unchanged'
} finally {
 [SwSession]::End()
 $viewEntry=$viewRegistry.OpenSubKey($viewKey+'\InprocServer32')
 if($viewEntry){$viewOwned=$viewEntry.GetValue('CodeBase') -eq $viewCodeBase;$viewEntry.Close();if($viewOwned){$viewRegistry.DeleteSubKeyTree($viewKey)}}
}
