# Compileaza fisiere AutoLISP (.lsp -> .fas, mod standard) in ambele formate .fas, cu accoreconsole.
#
#   powershell -ExecutionPolicy Bypass -File tools\compile_lisp.ps1 -Files a.lsp,b.lsp [-OutDir d] [-Format both|fas5|fas4] [-KeepTemp]
#
# AutoCAD 2021+ are doua motoare AutoLISP, alese de variabila LISPSYS (citita la pornire):
#   LISPSYS=0 -> motorul vechi (ANSI, VLIDE); incarca doar .fas "FAS4-FILE"
#   LISPSYS=1 -> motorul nou (Unicode); incarca FAS5 si FAS4, compileaza FAS5
#   LISPSYS=2 -> motorul nou, dar compileaza FAS4 (formatul vechi)
# (verificat cu accoreconsole AutoCAD 2026). Deci: FAS5 compilat sub LISPSYS=1, FAS4 sub LISPSYS=2.
# Sursele UTF-8 se citesc corect in ambele: sub LISPSYS=0 caracterele din afara ANSI (a cu caciula, s/t cu virgula)
# ajung in FAS4 ca \U+XXXX.
# Pentru fiecare format scriptul seteaza LISPSYS in profilul separat "TopoKitCompilare" (creat
# din <<C3D_Metric>> daca lipseste) si porneste O SINGURA consola accoreconsole (fara fereastra)
# care compileaza toate fisierele. accoreconsole /p schimba profilul implicit al AutoCAD
# (Profiles "(default)"): valoarea se salveaza inainte si se pune inapoi dupa (finally).
# Instantele acad.exe deschise nu sunt atinse; la depasirea timpului se opreste doar consola
# pornita aici.
# Iesire: <dir sursa>\fas5\<nume>.fas si <dir sursa>\fas4\<nume>.fas (cu -OutDir: <OutDir>\fas5\...).
# Fiecare .fas trebuie sa existe, sa nu fie gol si sa aiba antetul formatului (FAS5-FILE / FAS4-FILE).
# Afiseaza cate o linie "OK fisier.fas" / "EROARE fisier"; cod 0 doar daca toate au reusit.
param(
    [Parameter(Mandatory = $true)][string[]]$Files,
    [string]$OutDir = '',
    [ValidateSet('both', 'fas5', 'fas4')][string]$Format = 'both',
    [string]$CompileProfile = 'TopoKitCompilare',
    [string]$BaseProfile = '<<C3D_Metric>>',
    [int]$TimeoutSec = 900,
    [switch]$KeepTemp                       # pastreaza folderul temporar (script, jurnal accoreconsole)
)
$ErrorActionPreference = 'Stop'
if ($Files.Count -eq 1 -and $Files[0].Contains(',')) { $Files = $Files[0].Split(',') }
$Files = @($Files | ForEach-Object { $_.Trim() } | Where-Object { $_ })

# formatul -> valoarea LISPSYS sub care se compileaza si antetul asteptat
$FORMATS = [ordered]@{ fas5 = @{ Lispsys = '1'; Header = 'FAS5-FILE' }; fas4 = @{ Lispsys = '2'; Header = 'FAS4-FILE' } }
$want = if ($Format -eq 'both') { @('fas5', 'fas4') } else { @($Format) }

function Lisp([string]$s) { return $s.Replace('\', '/') }
function Fail([string]$m) { Write-Output "EROARE: $m"; exit 2 }

# ---------------------------------------------------------------- AutoCAD instalat (registru)
$acadKey = 'HKCU:\Software\Autodesk\AutoCAD'
try {
    $rel = (Get-ItemProperty $acadKey).CurVer
    $prod = (Get-ItemProperty "$acadKey\$rel").CurVer
} catch { Fail "nu gasesc AutoCAD in registru ($acadKey)" }
$prodKey = "$acadKey\$rel\$prod"
$profKey = "$prodKey\Profiles"
$loc = $null
foreach ($k in @("HKLM:\SOFTWARE\Autodesk\AutoCAD\$rel\$prod", $prodKey)) {
    try { $loc = (Get-ItemProperty $k -ErrorAction Stop).AcadLocation } catch {}
    if ($loc) { break }
}
if (-not $loc) { Fail "nu gasesc AcadLocation pentru $rel\$prod" }
$accore = Join-Path $loc 'accoreconsole.exe'
if (-not (Test-Path $accore)) { Fail "lipseste $accore" }
if (-not (Test-Path -LiteralPath "$profKey\$BaseProfile")) { Fail "lipseste profilul $BaseProfile" }

# desenul gol deschis de consola (/i e obligatoriu): sablonul acadiso.dwt copiat ca .dwg
$tpl = $null
$tplRoot = Join-Path $env:LOCALAPPDATA 'Autodesk'
if (Test-Path $tplRoot) {
    $tpl = Get-ChildItem $tplRoot -Recurse -Filter 'acadiso.dwt' -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $tpl) { $tpl = Get-ChildItem $tplRoot -Recurse -Filter 'acad.dwt' -ErrorAction SilentlyContinue | Select-Object -First 1 }
}
if (-not $tpl) { Fail "nu gasesc sablonul acadiso.dwt / acad.dwt in $tplRoot" }

# ---------------------------------------------------------------- fisierele
$jobs = @()
foreach ($f in $Files) {
    if (-not (Test-Path $f)) { Fail "lipseste $f" }
    $src = (Resolve-Path $f).Path
    $base = [IO.Path]::GetFileNameWithoutExtension($src)
    $dir = if ($OutDir) { $OutDir } else { Split-Path $src -Parent }
    $jobs += [pscustomobject]@{ Src = $src; Base = $base; Dir = $dir }
}
if ($OutDir) {
    $dup = $jobs | Group-Object Base | Where-Object { $_.Count -gt 1 }
    if ($dup) { Fail "cu -OutDir numele trebuie sa fie unice: $(($dup | ForEach-Object Name) -join ', ')" }
}

$tmp = Join-Path $env:TEMP ('tk_compile_' + [Guid]::NewGuid().ToString('N'))
if ($tmp -match '[^\x20-\x7E]') { Fail "calea temporara are caractere non-ASCII: $tmp" }
New-Item -ItemType Directory $tmp | Out-Null
$dwg = Join-Path $tmp 'gol.dwg'
Copy-Item $tpl.FullName $dwg

# copiile surselor: cai ASCII fara spatii, pentru scriptul .scr
$i = 0
foreach ($j in $jobs) {
    $i++
    $d = Join-Path $tmp "s$i"
    New-Item -ItemType Directory $d | Out-Null
    $j | Add-Member TmpSrc (Join-Path $d "$($j.Base).lsp")
    Copy-Item $j.Src $j.TmpSrc
}

# ---------------------------------------------------------------- profilul de compilare
function Get-Default { (Get-ItemProperty -LiteralPath $profKey).'(default)' }
$origDefault = Get-Default
$origLispsys = $null
$ok = $true

function Run-Format([string]$fmt) {
    $spec = $FORMATS[$fmt]
    $outTmp = Join-Path $tmp "o_$fmt"
    New-Item -ItemType Directory $outTmp | Out-Null
    $res = Join-Path $tmp "rez_$fmt.txt"
    $resL = Lisp $res
    Set-ItemProperty "$profKey\$CompileProfile\Variables" -Name LISPSYS -Value $spec.Lispsys -Type String

    # scriptul: verifica motorul, apoi compileaza fiecare fisier si scrie "<nr> <rezultat>"
    $lines = @("(progn (setq tk:fh (open `"$resL`" `"w`")) (write-line (strcat `"LISPSYS `" (itoa (getvar `"LISPSYS`"))) tk:fh) (close tk:fh) (princ))")
    $n = 0
    foreach ($j in $jobs) {
        $n++
        $j | Add-Member -Force "Out_$fmt" (Join-Path $outTmp "$n.fas")
        $s = Lisp $j.TmpSrc; $o = Lisp (Join-Path $outTmp "$n.fas")
        $lines += "(progn (setq tk:r (vl-catch-all-apply 'vlisp-compile (list 'st `"$s`" `"$o`"))) (setq tk:fh (open `"$resL`" `"a`")) (write-line (strcat `"$n `" (if (vl-catch-all-error-p tk:r) (strcat `"ERR `" (vl-catch-all-error-message tk:r)) (vl-princ-to-string tk:r))) tk:fh) (close tk:fh) (princ))"
    }
    $lines += '_QUIT _Y'
    $scr = Join-Path $tmp "c_$fmt.scr"
    [IO.File]::WriteAllText($scr, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)

    $p = Start-Process -FilePath $accore -ArgumentList @('/p', $CompileProfile, '/i', "`"$dwg`"", '/s', "`"$scr`"") `
        -WorkingDirectory $tmp -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $tmp "log_$fmt.txt") -RedirectStandardError (Join-Path $tmp "err_$fmt.txt")
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue      # doar consola pornita aici
        Write-Output "EROARE: accoreconsole ($fmt) nu a terminat in $TimeoutSec s"
        $script:ok = $false
        return
    }

    $rez = @{}
    $engine = $null
    if (Test-Path $res) {
        foreach ($l in Get-Content $res) {
            if ($l -match '^LISPSYS (\d+)') { $engine = $Matches[1] }
            elseif ($l -match '^(\d+) (.*)$') { $rez[[int]$Matches[1]] = $Matches[2] }
        }
    }
    if ($engine -ne $spec.Lispsys) {
        Write-Output "EROARE: consola ($fmt) a rulat cu LISPSYS=$engine in loc de $($spec.Lispsys)"
        $script:ok = $false
        return
    }
    $n = 0
    foreach ($j in $jobs) {
        $n++
        $tf = $j."Out_$fmt"
        $dstDir = Join-Path $j.Dir $fmt
        $dst = Join-Path $dstDir "$($j.Base).fas"
        $r = $rez[$n]
        $head = ''
        if (Test-Path $tf) {
            $b = [IO.File]::ReadAllBytes($tf)
            $head = [Text.Encoding]::ASCII.GetString($b, 0, [Math]::Min(64, $b.Length))
        }
        # vlisp-compile: T = fara observatii; un numar = cate avertismente (ex. apel cu peste 255 de
        # argumente, cum e (list ...) cu liniile DCL - codul compilat merge, verificat); nil = eroare
        if (($r -eq 'T' -or $r -match '^\d+$') -and (Test-Path $tf) -and (Get-Item $tf).Length -gt 0 -and $head.Contains($spec.Header)) {
            New-Item -ItemType Directory $dstDir -Force | Out-Null
            Copy-Item $tf $dst -Force
            Write-Output ("OK $dst" + $(if ($r -ne 'T') { " ($r avertismente)" } else { '' }))
        } else {
            Remove-Item $dst -ErrorAction SilentlyContinue                # fara .fas vechi ramas in urma
            Write-Output "EROARE $($j.Src) (${fmt}: $(if ($r) { $r } else { 'fara rezultat' }))"
            $script:ok = $false
        }
    }
}

try {
    if (-not (Test-Path "$profKey\$CompileProfile")) {
        Copy-Item -LiteralPath "$profKey\$BaseProfile" -Destination "$profKey\$CompileProfile" -Recurse
    }
    if (-not (Test-Path "$profKey\$CompileProfile\Variables")) { New-Item "$profKey\$CompileProfile\Variables" | Out-Null }
    $origLispsys = (Get-ItemProperty "$profKey\$CompileProfile\Variables").LISPSYS
    foreach ($fmt in $want) {
        try { Run-Format $fmt }
        catch { Write-Output "EROARE ($fmt): $($_.Exception.Message)"; $ok = $false }
        finally { Set-ItemProperty $profKey -Name '(default)' -Value $origDefault }
    }
}
catch { Write-Output "EROARE: $($_.Exception.Message)"; $ok = $false }
finally {
    # profilul implicit al utilizatorului si LISPSYS-ul profilului de compilare, ca inainte
    Set-ItemProperty $profKey -Name '(default)' -Value $origDefault
    if ($null -ne $origLispsys) {
        Set-ItemProperty "$profKey\$CompileProfile\Variables" -Name LISPSYS -Value $origLispsys -Type String -ErrorAction SilentlyContinue
    }
    if ((Get-Default) -ne $origDefault) { Write-Output "EROARE: profilul implicit nu a putut fi refacut ($origDefault)"; $ok = $false }
    if ($KeepTemp) { Write-Output "Temporar: $tmp" }
    else { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
if ($ok) { exit 0 } else { exit 1 }
