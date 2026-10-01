<#
  TopoKitDocx.ps1 - completeaza sabloanele Word (.docx) TopoKit cu datele din desen.

  Utilizare (apelat automat din AutoCAD, comanda ANEXE):
      powershell -NoProfile -ExecutionPolicy Bypass -File TopoKitDocx.ps1 -Job lucrare.json

  lucrare.json (UTF-8 sau ASCII cu secvente \uXXXX):
  {
    "fields":    { "NRCAD": "12345", "P1_NUMEC": "Popescu Ion", ... },
    "tables":    { "PCT": [ {"NR":"1","X":"...","Y":"..."}, ... ], "LAT": [ ... ] },
    "pdf":       false,
    "documents": [ { "template": "C:\\...\\anexe\\Anexa_13.docx",
                     "output":   "C:\\...\\Anexa_13_Cerere.docx" } ]
  }

  Campuri in sablon:
    {{CHEIE|implicit}}   valoarea campului sau textul implicit (de regula punctele
                         originale ale formularului) daca valoarea lipseste
    {{CHEIE#n|...}}      al n-lea caracter al valorii (ex. cifrele CNP-ului)
    {{SET.CHEIE|...}}    camp dintr-un rand repetabil: randul de tabel care contine
                         campul se multiplica pentru fiecare inregistrare a setului SET
  Valorile pot contine "\n" (rand nou in acelasi paragraf).

  Compatibil Windows PowerShell 5.1 si PowerShell 7+. Arhiva rezultata are
  intrarile cu "/" (cerinta Office), independent de versiunea .NET.
  Rezultatul fiecarui document se scrie in <lucrare.json>.log.
#>
param(
    [Parameter(Mandatory = $true)][string]$Job
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
$XMLNS = 'http://www.w3.org/XML/1998/namespace'
$PH = New-Object System.Text.RegularExpressions.Regex('\{\{([^{}]*)\}\}')
$LogLines = New-Object System.Collections.Generic.List[string]

function Write-Log([string]$line) {
    $LogLines.Add($line)
}

# Transforma un obiect JSON (PSCustomObject) intr-un dictionar cheie -> text
function ConvertTo-Map($obj) {
    $h = @{}
    if ($null -ne $obj) {
        foreach ($p in $obj.PSObject.Properties) {
            if ($null -eq $p.Value) { $h[$p.Name] = '' } else { $h[$p.Name] = [string]$p.Value }
        }
    }
    return $h
}

# Valoarea unui camp: "CHEIE|implicit", "SET.CHEIE#n|implicit"
function Resolve-Field([string]$inner, $scope) {
    $def = ''
    $key = $inner
    $i = $inner.IndexOf('|')
    if ($i -ge 0) {
        $def = $inner.Substring($i + 1)
        $key = $inner.Substring(0, $i)
    }
    $idx = 0
    $j = $key.IndexOf('#')
    if ($j -ge 0) {
        $idx = [int]$key.Substring($j + 1)
        $key = $key.Substring(0, $j)
    }
    $val = $null
    $dot = $key.IndexOf('.')
    if ($dot -ge 0) {
        $k2 = $key.Substring($dot + 1)
        if ($null -ne $scope -and $scope.ContainsKey($k2)) { $val = $scope[$k2] }
    }
    elseif ($script:Fields.ContainsKey($key)) {
        $val = $script:Fields[$key]
    }
    if ($null -eq $val -or $val -eq '') { return $def }
    if ($idx -gt 0) {
        if ($idx -le $val.Length) { return $val.Substring($idx - 1, 1) }
        return ''
    }
    return $val
}

# Scrie textul intr-un nod w:t; "\n" devine <w:br/> in acelasi run
function Set-NodeText($t, [string]$text) {
    $text = $text.Replace("`r`n", "`n").Replace("`r", "`n")
    $parts = $text.Split([char]10)
    $t.InnerText = $parts[0]
    [void]$t.SetAttribute('space', $XMLNS, 'preserve')
    if ($parts.Length -gt 1) {
        $run = $t.ParentNode
        $after = $t
        for ($k = 1; $k -lt $parts.Length; $k++) {
            $br = $t.OwnerDocument.CreateElement('w', 'br', $W)
            $nt = $t.OwnerDocument.CreateElement('w', 't', $W)
            [void]$nt.SetAttribute('space', $XMLNS, 'preserve')
            $nt.InnerText = $parts[$k]
            [void]$run.InsertAfter($br, $after)
            [void]$run.InsertAfter($nt, $br)
            $after = $nt
        }
    }
}

# Inlocuieste campurile dintr-un paragraf, chiar daca Word le-a impartit in mai multe run-uri
function Update-Paragraph($p, $nsm, $scope) {
    $ts = @($p.SelectNodes('.//w:t', $nsm))
    if ($ts.Count -eq 0) { return }
    $sb = New-Object System.Text.StringBuilder
    $starts = New-Object 'int[]' ($ts.Count)
    for ($i = 0; $i -lt $ts.Count; $i++) {
        $starts[$i] = $sb.Length
        [void]$sb.Append($ts[$i].InnerText)
    }
    $full = $sb.ToString()
    if ($full.IndexOf('{{') -lt 0) { return }
    $ms = $PH.Matches($full)
    for ($m = $ms.Count - 1; $m -ge 0; $m--) {
        $mt = $ms[$m]
        $s = $mt.Index
        $e = $mt.Index + $mt.Length
        $val = Resolve-Field $mt.Groups[1].Value $scope
        $a = 0
        while (($a + 1) -lt $ts.Count -and $starts[$a + 1] -le $s) { $a++ }
        $b = $a
        while (($b + 1) -lt $ts.Count -and $starts[$b + 1] -lt $e) { $b++ }
        $ta = $ts[$a].InnerText
        $tb = $ts[$b].InnerText
        $pre = $ta.Substring(0, [Math]::Min($ta.Length, $s - $starts[$a]))
        $postStart = $e - $starts[$b]
        $post = ''
        if ($postStart -lt $tb.Length) { $post = $tb.Substring($postStart) }
        if ($a -eq $b) {
            Set-NodeText $ts[$a] ($pre + $val + $post)
        }
        else {
            Set-NodeText $ts[$a] ($pre + $val)
            for ($k = $a + 1; $k -lt $b; $k++) { Set-NodeText $ts[$k] '' }
            Set-NodeText $ts[$b] $post
        }
    }
}

# Completeaza un document XML (document, antet sau subsol)
function Update-Xml($xml) {
    $nsm = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
    $nsm.AddNamespace('w', $W)
    # 1. randurile repetabile din tabele
    foreach ($tr in @($xml.SelectNodes('//w:tr', $nsm))) {
        $txt = (@($tr.SelectNodes('.//w:t', $nsm)) | ForEach-Object { $_.InnerText }) -join ''
        $m = [regex]::Match($txt, '\{\{([A-Za-z0-9_]+)\.')
        if (-not $m.Success) { continue }
        $ds = $m.Groups[1].Value
        $rows = @()
        if ($script:Tables.ContainsKey($ds)) { $rows = @($script:Tables[$ds]) }
        $parent = $tr.ParentNode
        if ($rows.Count -gt 0) {
            foreach ($row in $rows) {
                $clone = $tr.CloneNode($true)
                [void]$parent.InsertBefore($clone, $tr)
                foreach ($p in @($clone.SelectNodes('.//w:p', $nsm))) { Update-Paragraph $p $nsm $row }
            }
            [void]$parent.RemoveChild($tr)
        }
        else {
            foreach ($p in @($tr.SelectNodes('.//w:p', $nsm))) { Update-Paragraph $p $nsm @{} }
        }
    }
    # 2. toate celelalte campuri
    foreach ($p in @($xml.SelectNodes('//w:p', $nsm))) { Update-Paragraph $p $nsm $null }
}

# Creeaza documentul completat pornind de la sablon
function New-FilledDocx([string]$template, [string]$output) {
    $in = [System.IO.Compression.ZipFile]::OpenRead($template)
    try {
        if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }
        $fs = [System.IO.File]::Open($output, [System.IO.FileMode]::CreateNew)
        $zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($e in $in.Entries) {
                $name = $e.FullName.Replace('\', '/')
                $ne = $zip.CreateEntry($name, [System.IO.Compression.CompressionLevel]::Optimal)
                $src = $e.Open()
                $dst = $ne.Open()
                try {
                    if ($name -match '^word/(document|header\d*|footer\d*)\.xml$') {
                        $xml = New-Object System.Xml.XmlDocument
                        $xml.PreserveWhitespace = $true
                        $xml.Load($src)
                        Update-Xml $xml
                        $ws = New-Object System.Xml.XmlWriterSettings
                        $ws.Encoding = New-Object System.Text.UTF8Encoding($false)
                        $xw = [System.Xml.XmlWriter]::Create($dst, $ws)
                        $xml.Save($xw)
                        $xw.Close()
                    }
                    else {
                        $src.CopyTo($dst)
                    }
                }
                finally {
                    $src.Dispose()
                    $dst.Dispose()
                }
            }
        }
        finally {
            $zip.Dispose()
            $fs.Dispose()
        }
    }
    finally {
        $in.Dispose()
    }
}

# Numele fisierului rezultat: daca documentul anterior este deschis (blocat, de
# exemplu in Word), se foloseste NUME_2.docx, NUME_3.docx...
function Get-FreeOutput([string]$path) {
    $dir = [System.IO.Path]::GetDirectoryName($path)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($path)
    $ext = [System.IO.Path]::GetExtension($path)
    $cand = $path
    for ($k = 2; $k -lt 100; $k++) {
        if (-not (Test-Path -LiteralPath $cand)) { return $cand }
        try {
            $fs = [System.IO.File]::Open($cand, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite,
                                        [System.IO.FileShare]::None)
            $fs.Close()
            return $cand
        }
        catch { $cand = [System.IO.Path]::Combine($dir, $base + '_' + $k + $ext) }
    }
    return $cand
}

# Conversie optionala in PDF: Microsoft Word (COM) sau LibreOffice
function Convert-ToPdf([string[]]$docs) {
    $done = @()
    $word = $null
    try { $word = New-Object -ComObject Word.Application } catch { $word = $null }
    if ($null -ne $word) {
        try {
            $word.Visible = $false
            foreach ($d in $docs) {
                $pdf = [System.IO.Path]::ChangeExtension($d, '.pdf')
                $doc = $word.Documents.Open($d, $false, $true)
                $doc.SaveAs2($pdf, 17)
                $doc.Close($false)
                $done += $pdf
            }
        }
        finally { $word.Quit() }
        return $done
    }
    $soffice = $null
    foreach ($c in @("$env:ProgramFiles\LibreOffice\program\soffice.exe",
                     "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe", 'soffice')) {
        if ($c -and (Get-Command $c -ErrorAction SilentlyContinue)) { $soffice = $c; break }
    }
    if ($null -ne $soffice) {
        foreach ($d in $docs) {
            $dir = [System.IO.Path]::GetDirectoryName($d)
            & $soffice --headless --norestore --convert-to pdf --outdir $dir $d | Out-Null
            $pdf = [System.IO.Path]::ChangeExtension($d, '.pdf')
            if (Test-Path -LiteralPath $pdf) { $done += $pdf }
        }
    }
    return $done
}

# ------------------------------------------------------------------ program
$errors = 0
try {
    $jobText = [System.IO.File]::ReadAllText($Job, [System.Text.Encoding]::UTF8)
    $data = $jobText | ConvertFrom-Json
    $script:Fields = ConvertTo-Map $data.fields
    $script:Tables = @{}
    if ($null -ne $data.tables) {
        foreach ($p in $data.tables.PSObject.Properties) {
            $list = New-Object System.Collections.Generic.List[object]
            foreach ($r in @($p.Value)) { $list.Add((ConvertTo-Map $r)) }
            $script:Tables[$p.Name] = $list.ToArray()
        }
    }
    $made = @()
    foreach ($d in @($data.documents)) {
        $out = [string]$d.output
        try {
            $out = Get-FreeOutput $out
            if ($out -ne [string]$d.output) {
                Write-Log ("INFO`tDocumentul " + $d.output + " este deschis; s-a salvat ca " + $out)
            }
            New-FilledDocx ([string]$d.template) $out
            $made += $out
            Write-Log ("OK`t" + $out)
        }
        catch {
            $errors++
            Write-Log ("EROARE`t" + $out + "`t" + $_.Exception.Message)
        }
    }
    if ($data.pdf -and $made.Count -gt 0) {
        try {
            foreach ($pdf in (Convert-ToPdf $made)) { Write-Log ("PDF`t" + $pdf) }
        }
        catch { Write-Log ("EROARE-PDF`t" + $_.Exception.Message) }
    }
}
catch {
    $errors++
    Write-Log ("EROARE`t" + $_.Exception.Message)
}
[System.IO.File]::WriteAllLines($Job + '.log', $LogLines, (New-Object System.Text.UTF8Encoding($false)))
exit $errors
