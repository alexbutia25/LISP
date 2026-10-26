"""Testeaza transformarea DWG to KMZ pe punctele oficiale din Help_TransDatRO_code_source (ANCPI)."""
import math
import sys

import transdatro as t

sys.stdout.reconfigure(encoding="utf-8")


def dms(d, m, s):
    return d + m / 60 + s / 3600


# nume, x (Nord), y (Est), latitudine, longitudine  - valori oficiale TransDatRO
TESTS = [
    ("P1", 693771.731, 310723.518, (47, 42, 56.4), (22, 28, 32.0)),
    ("P2", 721361.806, 641283.450, (47, 58, 33.2), (26, 53, 26.7)),
    ("P3", 516470.189, 165265.572, (46, 3, 57.4), (20, 40, 11.6)),
    ("P4", 402327.815, 713143.130, (45, 5, 18.2), (27, 42, 24.0)),
    ("P5", 329703.378, 333185.413, (44, 26, 51.3), (22, 54, 9.3)),
    ("P6", 249343.594, 518651.464, (43, 44, 37.2), (25, 13, 48.1)),
    ("P7", 528076.247, 411159.899, (46, 14, 47.6), (23, 50, 46.1)),
]

worst = 0.0
print("Punct   Stereo70->ETRS89    ETRS89->Stereo70 (dX, dY)")
for name, x, y, la, lo in TESTS:
    lon, lat = t.stereo70_to_etrs89(y, x)
    dn = math.radians(lat - dms(*la)) * 6378137
    de = math.radians(lon - dms(*lo)) * 6378137 * math.cos(math.radians(lat))
    d = math.hypot(dn, de)
    e2, n2 = t.etrs89_to_stereo70(dms(*lo), dms(*la))
    worst = max(worst, d, abs(n2 - x), abs(e2 - y))
    print(f"{name}     {d * 1000:7.2f} mm        {(n2 - x) * 1000:7.2f} mm  {(e2 - y) * 1000:7.2f} mm")

for name, x, y in [("OutsideGrid", 188993.152, 348668.167), ("OutsideBorder", 725005.421, 170257.544)]:
    try:
        t.stereo70_to_etrs89(y, x)
        print(f"{name}: EROARE - nu a fost respins")
    except t.OutsideGrid as ex:
        print(f"{name}: respins corect ({ex})")

print(f"\nEroare maximă: {worst * 1000:.2f} mm  (valorile oficiale sunt date la 1 mm / 0.00001\")")
