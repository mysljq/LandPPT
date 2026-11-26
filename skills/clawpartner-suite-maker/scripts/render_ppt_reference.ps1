param(
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputDir
)
# Optional Windows/PowerPoint reference renderer. Opens read-only and never saves source.
$ErrorActionPreference = 'Stop'
$referenceInput = (Resolve-Path -LiteralPath $InputFile).Path
$referenceOutput = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $referenceOutput | Out-Null
$referenceApp = $null
$referenceDeck = $null
$referenceExistingDecks = 0
try {
    $referenceApp = New-Object -ComObject PowerPoint.Application
    $referenceExistingDecks = $referenceApp.Presentations.Count
    $referenceDeck = $referenceApp.Presentations.Open($referenceInput, -1, 0, 0)
    $referenceScale = 1280.0 / $referenceDeck.PageSetup.SlideWidth
    $referencePages = @()
    for ($referenceIndex = 1; $referenceIndex -le $referenceDeck.Slides.Count; $referenceIndex++) {
        $referenceSlide = $referenceDeck.Slides.Item($referenceIndex)
        $referenceSlide.Export((Join-Path $referenceOutput ('{0:D3}.png' -f $referenceIndex)), 'PNG', 1280, 720)
        $referenceShapes = @()
        foreach ($referenceShape in $referenceSlide.Shapes) {
            $referenceItem = @{id=$referenceShape.Id; name=$referenceShape.Name; x=$referenceShape.Left*$referenceScale; y=$referenceShape.Top*$referenceScale; width=$referenceShape.Width*$referenceScale; height=$referenceShape.Height*$referenceScale}
            if ($referenceShape.HasTextFrame -and $referenceShape.TextFrame.HasText) {
                $referenceText = $referenceShape.TextFrame.TextRange
                $referenceItem.text = $referenceText.Text
                $referenceItem.font_size_px = $referenceText.Font.Size*$referenceScale
                $referenceItem.font_name = $referenceText.Font.Name
                $referenceItem.line_count = $referenceText.Lines().Count
                $referenceItem.bound = @(($referenceText.BoundLeft*$referenceScale),($referenceText.BoundTop*$referenceScale),($referenceText.BoundWidth*$referenceScale),($referenceText.BoundHeight*$referenceScale))
            }
            $referenceShapes += $referenceItem
        }
        $referencePages += @{slide=$referenceIndex;shapes=$referenceShapes}
    }
    ConvertTo-Json -InputObject $referencePages -Depth 10 | Set-Content -LiteralPath (Join-Path $referenceOutput 'native-metrics.json') -Encoding utf8
} finally {
    if ($referenceDeck) {$referenceDeck.Close()}
    if ($referenceApp -and $referenceExistingDecks -eq 0 -and $referenceApp.Presentations.Count -eq 0) {$referenceApp.Quit()}
}
