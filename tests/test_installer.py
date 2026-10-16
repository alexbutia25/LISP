#!/usr/bin/env python3
"""Test complet al instalatorului TopoKitSetup.exe sub Wine (Linux).

    python3 tests/test_installer.py [--no-build] [--debug] [--render DIR]

(--render DIR: salveaza imaginile ferestrei TopoKit, ca in docs/lansator_*.png)

(--debug: mesajele de eroare Wine se scriu in jurnal si se afiseaza la esec)

Necesita: wine (64 + 32 bit), Xvfb, makensis, mingw-w64
    apt install nsis mingw-w64 xvfb wine64 wine32:i386

Pasi:
  1. construieste dist/TopoKitSetup.exe (tools/build_installer.py), daca nu e --no-build;
  2. instaleaza silentios (/S) intr-un prefix Wine nou si verifica fisierele,
     pachetul AutoCAD, registrul (ContentsDir, Run, Uninstall) si scurtaturile;
  3. compileaza tests/fake_acad.c ("AutoCAD" COM simulat) si verifica lansatorul:
     - porneste in fundal fara AutoCAD;
     - /cmd ANEXE porneste AutoCAD (serverul COM inregistrat), asteapta sa fie
       inactiv, deschide un desen si trimite incarcarea TopoKit + ANEXE;
     - a doua pornire transmite cererea instantei care ruleaza deja;
     - pornirea fara parametri deschide fereastra TopoKit;
     - /snapshot deseneaza fereastra (GDI+) in PNG, la scara 1 si 1,5;
     - /quit inchide lansatorul;
  4. dezinstaleaza silentios si verifica stergerea completa.
"""
import os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SETUP = os.path.join(ROOT, "dist", "TopoKitSetup.exe")


def need(*tools):
    miss = [t for t in tools if not shutil.which(t)]
    if miss:
        print("Lipsesc:", ", ".join(miss), "- testul instalatorului este omis.")
        sys.exit(0)


need("wine", "wineserver", "Xvfb", "x86_64-w64-mingw32-gcc")
if "--no-build" not in sys.argv:
    need("makensis")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_installer.py")], check=True,
                   stdout=subprocess.DEVNULL)

tmp = tempfile.mkdtemp(prefix="topokit_wine_")
display = ":%d" % (90 + os.getpid() % 9)
xvfb = subprocess.Popen(["Xvfb", display], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
DEBUG = "--debug" in sys.argv
E = dict(os.environ, WINEPREFIX=os.path.join(tmp, "prefix"), WINEARCH="win64",
         WINEDEBUG="err+all,fixme-all" if DEBUG else "-all", DISPLAY=display,
         WINEDLLOVERRIDES="mscoree,mshtml=")               # fara instalarea Mono / Gecko
wine_log = os.path.join(tmp, "wine.log")
ERR = open(wine_log, "a") if DEBUG else subprocess.DEVNULL
USER = os.path.join(E["WINEPREFIX"], "drive_c", "users", os.environ.get("USER", "root"))


def wine(*args, wait=True, timeout=240):
    cmd = ["wine"] + [str(a) for a in args]
    if wait:
        return subprocess.run(cmd, env=E, timeout=timeout, stdout=subprocess.DEVNULL, stderr=ERR)
    return subprocess.Popen(cmd, env=E, stdout=subprocess.DEVNULL, stderr=ERR)


def reg(key):
    r = subprocess.run(["wine", "reg", "query", key], env=E, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def wait_for(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.5)
    raise AssertionError("timp depasit: " + what)


def read(p):
    try:
        return open(p, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return ""


try:
    subprocess.run(["wineboot", "-i"], env=E, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["wineserver", "-w"], env=E, timeout=300)          # prefixul nou este gata
    # serviciul RPC (tabela de obiecte active COM) ruleaza mereu in Windows; in Wine il pornim explicit
    wine("net", "start", "RpcSs")
    if not os.path.isdir(os.path.join(USER, "AppData")):            # utilizatorul Wine
        USER = os.path.join(E["WINEPREFIX"], "drive_c", "users",
                            next(d for d in os.listdir(os.path.join(E["WINEPREFIX"], "drive_c", "users"))
                                 if d != "Public"))

    # ------------------------------------------------------------ instalare
    assert wine(SETUP, "/S").returncode == 0
    bundle = os.path.join(USER, "AppData", "Roaming", "Autodesk", "ApplicationPlugins", "TopoKit.bundle")
    app = os.path.join(USER, "AppData", "Local", "Programs", "TopoKit")
    contents = os.path.join(bundle, "Contents")
    for f in ("TopoKitLoad.lsp", "TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp", "TopoKit.dcl",
              "TopoKitAnexe.dcl", "TopoKitTeren.dcl", "stereo70_etrs89A.gsb", "anexe/TopoKitDocx.ps1",
              "anexe/catalog.json", "anexe/Anexa_01.docx"):
        src = os.path.join(ROOT, f)
        dst = os.path.join(contents, f)
        assert os.path.isfile(dst), f
        assert open(src, "rb").read() == open(dst, "rb").read(), "copie diferita: " + f
    xml = read(os.path.join(bundle, "PackageContents.xml"))
    ver = open(os.path.join(ROOT, "installer", "VERSION")).read().strip()
    assert 'AppVersion="%s"' % ver in xml and "@VERSION@" not in xml
    for f in ("TopoKit.exe", "Uninstall.exe", "README.html", "docs/teren_tin_curbe.png"):
        assert os.path.isfile(os.path.join(app, f)), f
    r = reg(r"HKCU\Software\TopoKit")
    assert r and "ContentsDir" in r and "TopoKit.bundle\\Contents" in r and ver in r, r
    r = reg(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run")
    assert r and "TopoKit.exe\" /background" in r, r
    r = reg(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\TopoKit")
    assert r and "Uninstall.exe" in r and "QuietUninstallString" in r, r
    start = os.path.join(USER, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "TopoKit")
    assert os.path.isfile(os.path.join(start, "TopoKit.lnk"))
    print("Instalare: pachet AutoCAD, lansator, registru si scurtaturi corecte")

    # ------------------------------------------------------------ lansator + AutoCAD simulat
    os.makedirs(os.path.join(tmp, "acad"))
    fake = os.path.join(tmp, "acad", "acad.exe")                 # recunoscut dupa numele procesului
    subprocess.run(["x86_64-w64-mingw32-gcc", "-municode", "-mwindows", "-O2", "-o", fake,
                    os.path.join(ROOT, "tests", "fake_acad.c"), "-lole32", "-loleaut32", "-luuid", "-lshell32",
                    "-static", "-s"], check=True)
    acad_log = os.path.join(tmp, "acad.log")
    wine(fake, "/regserver", "Z:" + acad_log.replace("/", "\\"))
    exe = os.path.join(app, "TopoKit.exe")
    log = os.path.join(USER, "AppData", "Local", "TopoKit", "TopoKit.log")

    wine(exe, "/background", wait=False)
    wait_for(lambda: "AutoCAD inchis" in read(log), 30, "lansatorul in fundal")
    assert "Versiuni AutoCAD inregistrate COM: 1" in read(log), read(log)
    assert not os.path.exists(acad_log)                              # nu porneste AutoCAD singur

    wine(exe, "/cmd", "ANEXE", wait=False)                           # a doua instanta -> prima
    wait_for(lambda: "SEND" in read(acad_log), 60, "comanda ANEXE in AutoCAD")
    a = [l for l in read(acad_log).splitlines() if l != "ACTIVATE"]
    assert a[0] == "STARTED" and a[1] == "DOCUMENTS.ADD" and "ACTIVATE" in read(acad_log), a
    lsp = contents.split("drive_c")[1].replace(os.sep, "/")
    assert a[2] == ('SEND <03><03>(progn (if (not TKL:Load) (load "C:%s/TopoKitLoad.lsp")) '
                    '(if (not c:TOPOKIT) (TKL:Load nil)) (princ))<LF>ANEXE<LF>' % lsp), a[2]
    L = read(log)
    assert "Pornesc" in L and "Conectat la Civil 3D 2025 (COM)" in L and "SendCommand ANEXE: 0x00000000" in L, L

    wine(exe, wait=False)                                            # pornire normala: fereastra
    wait_for(lambda: "Fereastra TopoKit afisata" in read(log), 30, "fereastra TopoKit")
    assert read(acad_log).count("SEND") == 1                         # fereastra nu trimite nimic singura
    wine(exe, "/cmd", "TOPOKIT", wait=False)
    wait_for(lambda: read(acad_log).count("SEND") >= 2, 30, "comanda TOPOKIT")
    assert [l for l in read(acad_log).splitlines() if l.startswith("SEND")][1].endswith("<LF>TOPOKIT<LF>")
    wine(exe, "/cmd", "TOPOTEREN;ERASE", wait=False)                 # doar nume de comenzi
    wait_for(lambda: read(acad_log).count("SEND") >= 3, 30, "comanda TOPOTEREN")
    assert [l for l in read(acad_log).splitlines() if l.startswith("SEND")][2].endswith(")<LF>TOPOTEREN<LF>")
    print("Lansator: conectare COM, pornirea AutoCAD, desen nou, comenzi transmise intre instante")

    # AutoCAD fara legatura COM (nu apare in ROT): detectat dupa fereastra, comenzi prin WM_COPYDATA
    wine(exe, "/cmd", "QUIT", wait=False)
    wait_for(lambda: "EXIT" in read(acad_log), 30, "inchiderea AutoCAD simulat")
    wait_for(lambda: read(log).rstrip().endswith("AutoCAD inchis / nepornit"), 30, "deconectare")
    subprocess.run(["wine", "reg", "add", r"HKCU\Software\TopoKitTest", "/v", "NoRot", "/d", "1", "/f"], env=E,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wine(fake, wait=False)
    wait_for(lambda: "Conectat la Civil 3D 2025 (fereastra, fara COM)" in read(log), 40, "detectare fereastra")
    wine(exe, "/cmd", "ANEXE", wait=False)
    wait_for(lambda: "COPYDATA" in read(acad_log), 30, "comanda prin fereastra")
    cp = [l for l in read(acad_log).splitlines() if l.startswith("COPYDATA")]
    assert cp[0] == ('COPYDATA <03><03>(progn (if (not TKL:Load) (load "C:%s/TopoKitLoad.lsp")) '
                     '(if (not c:TOPOKIT) (TKL:Load nil)) (princ))<LF>ANEXE<LF>' % lsp), cp
    assert "Mesaj: ANEXE trimisă în Civil 3D 2025 (Plan_cadastral.dwg)" in read(log), read(log)
    wine(exe, "/diag", wait=False)
    diag = os.path.join(os.path.dirname(log), "diagnostic.txt")
    wait_for(lambda: "Jurnal" in read(diag), 30, "raportul de diagnostic")
    D = read(diag)
    assert 'Fereastra AutoCAD: "Autodesk Civil 3D 2025 - [Plan_cadastral.dwg]"' in D and "TopoKitLoad.lsp: da" in D, D
    print("Lansator: AutoCAD fara COM gasit dupa fereastra, comanda prin WM_COPYDATA, raport de diagnostic")

    # imaginea ferestrei (aceeasi functie de desen ca fereastra reala)
    from PIL import Image
    render = sys.argv[sys.argv.index("--render") + 1] if "--render" in sys.argv else tmp
    for name, args in (("lansator_conectat", ("on", "1", "1")), ("lansator_oprit", ("off", "-1", "1")),
                       ("lansator_150", ("starting", "20", "1.5"))):
        png = os.path.join(os.path.abspath(render), name + ".png")
        assert wine(exe, "/snapshot", "Z:" + png.replace("/", "\\"), *args).returncode == 0, name
        im = Image.open(png).convert("RGB")
        k = 1.5 if name.endswith("150") else 1
        assert im.size == (int(840 * k), int(600 * k)), im.size
        r, g, b = im.getpixel((int(8 * k), int(8 * k)))                       # antetul albastru
        assert b > 80 and r < 40, (r, g, b)
        assert im.getpixel((int(420 * k), int(590 * k))) == (244, 247, 250)    # fundalul ferestrei
    print("Fereastra TopoKit: pornire fara parametri, imagini la scara 1 si 1,5")

    wine(exe, "/quit", wait=False)
    wait_for(lambda: "Lansator oprit" in read(log), 20, "/quit")
    print("Lansator: /quit")

    # ------------------------------------------------------------ dezinstalare
    assert wine(os.path.join(app, "Uninstall.exe"), "/S").returncode == 0
    wait_for(lambda: not os.path.exists(os.path.join(app, "TopoKit.exe")), 30, "dezinstalare")
    assert not os.path.exists(bundle) and not os.path.exists(start)
    assert reg(r"HKCU\Software\TopoKit") is None
    assert reg(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\TopoKit") is None
    assert "TopoKit" not in (reg(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run") or "")
    print("Dezinstalare: fisiere, pachet AutoCAD si registru sterse")
    print("\nToate testele instalatorului au trecut.")
except Exception:
    for name in ("log", "acad_log") + (("wine_log",) if DEBUG else ()):
        if name in globals():
            print(f"--- {name}:\n" + read(globals()[name]))
    raise
finally:
    subprocess.run(["wineserver", "-k"], env=E, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    xvfb.terminate()
    shutil.rmtree(tmp, ignore_errors=True)
