param([string]$BuildDirectory)
$ErrorActionPreference='Stop'
$nativeJob=Get-Content -LiteralPath (Join-Path $BuildDirectory 'job.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$nativeDll=Join-Path $BuildDirectory 'MacNativeFeatures.dll'
$nativeAssemblies=@('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll') | ForEach-Object {Join-Path $BuildDirectory $_}
Add-Type -Path $nativeAssemblies
Add-Type -Path @((Join-Path $nativeJob.root 'tools/exact_native/SwSession.cs'),(Join-Path $nativeJob.root 'tools/exact_native/SwInspectionHost.cs')) -ReferencedAssemblies @($nativeAssemblies[0],$nativeAssemblies[1],'System.Core')
$nativeRegistry=[Microsoft.Win32.Registry]::CurrentUser
$nativeKey='Software\Classes\CLSID\{6AB4EFC0-B919-4CCB-AD94-24B10C2D0694}'
if($nativeRegistry.OpenSubKey($nativeKey)){throw 'Native construction component is already registered; inspect ownership before reuse'}
$nativeAssemblyName=[Reflection.AssemblyName]::GetAssemblyName($nativeDll).FullName
$nativeCodeBase='file:///'+$nativeDll.Replace('\','/')
try {
 $nativeEntry=$nativeRegistry.CreateSubKey($nativeKey);$nativeEntry.SetValue('','NativeBuildAddin');$nativeEntry.Close()
 foreach($nativeSuffix in @('\InprocServer32','\InprocServer32\0.0.0.0')){
  $nativeEntry=$nativeRegistry.CreateSubKey($nativeKey+$nativeSuffix)
  $nativeEntry.SetValue('','mscoree.dll');$nativeEntry.SetValue('ThreadingModel','Both');$nativeEntry.SetValue('Class','NativeBuildAddin')
  $nativeEntry.SetValue('Assembly',$nativeAssemblyName);$nativeEntry.SetValue('RuntimeVersion','v4.0.30319');$nativeEntry.SetValue('CodeBase',$nativeCodeBase);$nativeEntry.Close()
 }
 $nativeEntry=$nativeRegistry.CreateSubKey($nativeKey+'\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}');$nativeEntry.Close()
 [SwSession]::SkipReadback=$true;[SwSession]::Begin()
 $nativeLoad=[SwInspectionHost]::Load($nativeDll)
 if($nativeLoad -ne 0){throw ('Native construction add-in did not load: '+$nativeLoad)}
 [SwInspectionHost]::Unload($nativeDll) | Out-Null
 $nativeStatus=Get-Content -LiteralPath $nativeJob.status -Raw -Encoding UTF8 | ConvertFrom-Json
 if(-not $nativeStatus.completed -or -not $nativeStatus.passed){throw $nativeStatus.error}
} finally {
 [SwSession]::End()
 $nativeEntry=$nativeRegistry.OpenSubKey($nativeKey+'\InprocServer32')
 if($nativeEntry){$nativeOwned=$nativeEntry.GetValue('CodeBase') -eq $nativeCodeBase;$nativeEntry.Close();if($nativeOwned){$nativeRegistry.DeleteSubKeyTree($nativeKey)}}
}
