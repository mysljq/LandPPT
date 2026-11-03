$ErrorActionPreference = 'Stop'
$auditRoot = if ($env:AUDIT_OUT) {Join-Path (Get-Location) $env:AUDIT_OUT} else {Join-Path (Get-Location) 'tmp/numeric-audit'}
$files = Get-ChildItem -LiteralPath $auditRoot -Filter 'page-*.pptx' | Sort-Object { [int]($_.BaseName -replace 'page-','') }
foreach ($file in $files) {
  foreach ($kind in @('office','wps')) {
    $target = Join-Path $auditRoot ($kind+'-'+$file.BaseName+'.png')
    if (Test-Path -LiteralPath $target) {continue}
    for ($attempt=0; $attempt -lt 3; $attempt++) {
      $deck=$null
      try {
        $app=if($kind -eq 'wps'){New-Object -ComObject KWPP.Application}else{New-Object -ComObject PowerPoint.Application}
        $deck=$app.Presentations.Open($file.FullName,-1,0,0)
        $deck.Slides.Item(1).Export($target,'PNG',1280,720)
        break
      } catch {
        if ($attempt -eq 2) {throw}
      } finally { if ($deck) {try {$deck.Close()} catch {}} }
    }
  }
  Write-Output $file.BaseName
}
