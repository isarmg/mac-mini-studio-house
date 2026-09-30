param([string]$OutputModel,[string]$Report,[string]$InputGeometry,[string]$BatchFile,[ValidateSet('inspect','transfer','compose')][string]$Action='inspect',[switch]$CompileOnly)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$interop='C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist'
$workRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$buildRoot=Join-Path $workRoot '.tmp/exact-migration/inprocess'
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$sourceNames=@('Packet.cs','SwSession.cs','SwExact.cs','SwReadback.cs','SwInspectionAddin.cs')
$sources=@($sourceNames | ForEach-Object {Join-Path $PSScriptRoot $_})
$sourceHash=($sources | ForEach-Object {(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}) -join ''
$algorithm=[Security.Cryptography.SHA256]::Create()
$buildHash=([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($sourceHash)))).Replace('-','').ToLowerInvariant()
$compiled=Join-Path $buildRoot ('ExactCadInspection_'+$buildHash+'.dll')
$framework=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
$references=@((Join-Path $interop 'SolidWorks.Interop.sldworks.dll'),(Join-Path $interop 'SolidWorks.Interop.swconst.dll'),(Join-Path $interop 'SolidWorks.Interop.swpublished.dll'),(Join-Path $framework 'System.Core.dll'),(Join-Path $framework 'System.Web.Extensions.dll'))
if(-not (Test-Path -LiteralPath $compiled)){
    $compilerArgs=@('/nologo','/target:library','/platform:x64',('/out:'+$compiled))+@($references | ForEach-Object {'/reference:'+$_})+$sources
    & (Join-Path $framework 'csc.exe') @compilerArgs
    if($LASTEXITCODE -ne 0){throw 'Inspection DLL compilation failed'}
}
$dll=Join-Path $buildRoot 'ExactCadInspection.dll'
Copy-Item -LiteralPath $compiled -Destination $dll -Force
foreach($name in @('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swpublished.dll')){
    Copy-Item -LiteralPath (Join-Path $interop $name) -Destination (Join-Path $buildRoot $name) -Force
}
if($CompileOnly){Write-Output ('Reviewable in-process inspection DLL: '+$dll);return}
if(-not $BatchFile -and (-not $OutputModel -or -not $Report)){throw 'OutputModel and Report are required for inspection'}
Add-Type -Path (Join-Path $interop 'SolidWorks.Interop.sldworks.dll')
Add-Type -Path (Join-Path $interop 'SolidWorks.Interop.swconst.dll')
Add-Type -Path @((Join-Path $PSScriptRoot 'SwSession.cs'),(Join-Path $PSScriptRoot 'SwInspectionHost.cs')) -ReferencedAssemblies @((Join-Path $interop 'SolidWorks.Interop.sldworks.dll'),(Join-Path $interop 'SolidWorks.Interop.swconst.dll'),'System.Core')
$guid='{2D16C047-FE48-4C43-8C60-9F02F43B9957}'
$classKey='Software\Classes\CLSID\'+$guid
$swKey='Software\SolidWorks\AddIns\'+$guid
$registry=[Microsoft.Win32.Registry]::CurrentUser
if($registry.OpenSubKey($classKey)){throw 'Temporary COM registration already exists; inspect ownership before reuse.'}
$registration=[Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($swKey)
if($registration){
    $guardOwns=$registration.GetValue('Description') -eq $dll;$registration.Close()
    if(-not $guardOwns){throw 'The administrator registration points outside this task helper'}
}else{Write-Output 'Using temporary per-user COM registration only'}
$assemblyName=[Reflection.AssemblyName]::GetAssemblyName($dll).FullName
$codeBase='file:///'+$dll.Replace('\','/')
$jobPath=Join-Path $buildRoot 'job.json'
if($BatchFile){
    $jobs=@((Get-Content -LiteralPath $BatchFile -Raw -Encoding UTF8 | ConvertFrom-Json).jobs)
}else{
    $reportPath=[IO.Path]::GetFullPath($Report)
    $job=@{model=[IO.Path]::GetFullPath($OutputModel);report=$reportPath;log=$reportPath+'.inprocess.log';action=$Action}
    if($InputGeometry){$job.input=[IO.Path]::GetFullPath($InputGeometry)}
    if($Action -ne 'inspect' -and -not $InputGeometry){throw 'Direct construction requires the canonical InputGeometry packet'}
    $jobs=@($job)
}
[IO.File]::WriteAllText($jobPath,(@{jobs=$jobs} | ConvertTo-Json -Compress -Depth 8),(New-Object Text.UTF8Encoding($false)))
foreach($job in $jobs){
    if($job.action -eq 'inspect' -and -not (Test-Path -LiteralPath $job.model -PathType Leaf)){throw ('Missing native model before application startup: '+$job.model)}
    if($job.action -ne 'inspect' -and -not (Test-Path -LiteralPath $job.input -PathType Leaf)){throw ('Missing input before application startup: '+$job.input)}
}
$env:EXACT_CAD_INSPECTION_JOB=$jobPath
try {
    $key=$registry.CreateSubKey($classKey);$key.SetValue('','ExactCadInspectionAddin');$key.Close()
    $key=$registry.CreateSubKey($classKey+'\InprocServer32')
    $key.SetValue('','mscoree.dll');$key.SetValue('ThreadingModel','Both');$key.SetValue('Class','ExactCadInspectionAddin');$key.SetValue('Assembly',$assemblyName);$key.SetValue('RuntimeVersion','v4.0.30319');$key.SetValue('CodeBase',$codeBase);$key.Close()
    $key=$registry.CreateSubKey($classKey+'\InprocServer32\0.0.0.0')
    $key.SetValue('Class','ExactCadInspectionAddin');$key.SetValue('Assembly',$assemblyName);$key.SetValue('RuntimeVersion','v4.0.30319');$key.SetValue('CodeBase',$codeBase);$key.Close()
    $key=$registry.CreateSubKey($classKey+'\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}');$key.Close()
    $probe=[Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]$guid))
    if($null -eq $probe){throw 'Temporary COM component activation failed'}
    Write-Output 'Temporary inspection COM component activated successfully'
    if([Runtime.InteropServices.Marshal]::IsComObject($probe)){[Runtime.InteropServices.Marshal]::FinalReleaseComObject($probe) | Out-Null}
    $probe=$null
    [SwSession]::SkipReadback=$true
    [SwSession]::Begin()
    $status=[SwInspectionHost]::Load($dll)
    Write-Output ('In-process add-in load status: '+$status)
    if($status -ne 0){throw ('Could not load in-process inspection add-in: '+$status)}
    [SwInspectionHost]::Unload($dll) | Out-Null
    $failures=@()
    foreach($job in $jobs){
        if(-not (Test-Path -LiteralPath $job.report)){$failures+='No native report: '+$job.report;continue}
        Get-Content -LiteralPath $job.log -Encoding UTF8 -Tail 3
        $result=Get-Content -LiteralPath ($job.report+'.status.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if($result.error){$failures+=$result.error}
        if($null -eq $result.topology_passed){$failures+='Native topology inspection did not finish: '+$job.report}
    }
    if($failures.Count){throw ($failures -join [Environment]::NewLine)}
} finally {
    [SwSession]::End()
    $key=$registry.OpenSubKey($classKey+'\InprocServer32')
    if($key){$owned=$key.GetValue('CodeBase') -eq $codeBase;$key.Close();if($owned){$registry.DeleteSubKeyTree($classKey)}}
}
