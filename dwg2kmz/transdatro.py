"""
Portare Python a algoritmului oficial ANCPI TransDatRO (TransDatRO_code_source 1.06)
pentru Stereografic 1970 <-> ETRS89, cu grila ETRS89_KRASOVSCHI42_2DJ.GRD.

Pasi Stereo70 -> ETRS89 (identic cu clasa Java Stereo70or30ETRS89):
  1. corectie din grila (interpolare bicubica B-spline): E -= dE, N -= dN
  2. Helmert 2D  Stereo70 -> Oblique Stereographic GRS80
  3. stereografic invers pe elipsoidul GRS80 -> (phi, lambda) ETRS89
"""
import math
import os
import struct
import sys
from array import array

A_ETRS89 = 6378137.0
INV_F_ETRS89 = 298.257222101

# Helmert 2D (din clasa dV, TransDatRO): tE, tN, dm [ppm], Rz ["]
H_OS_ST70 = (119.7358, 31.8051, 0.11559991, -0.22739706)
H_ST70_OS = (-119.7358, -31.8051, -0.11559991, 0.22739706)

GRID_NAME = "ETRS89_KRASOVSCHI42_2DJ.GRD"


class OutsideGrid(ValueError):
    pass


def _grid_path():
    bases = [getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__)),
             os.path.dirname(os.path.abspath(sys.argv[0]))]
    for b in bases:
        if b:
            p = os.path.join(b, "grids", GRID_NAME)
            if os.path.isfile(p):
                return p
    raise FileNotFoundError(f"Lipseste grila {GRID_NAME}")


class _Grid2D:
    def __init__(self, path):
        with open(path, "rb") as fh:
            raw = fh.read()
        self.minE, self.maxE, self.minN, self.maxN, self.stepE, self.stepN = struct.unpack("<6d", raw[:48])
        self.vals = array("d")
        self.vals.frombytes(raw[48:])
        if sys.byteorder != "little":
            self.vals.byteswap()
        self.ncols = round((self.maxE - self.minE) / self.stepE + 1)

    def shift(self, east, north):
        minE, minN, stepE, stepN = self.minE, self.minN, self.stepE, self.stepN
        if (east <= minE + stepE or east >= self.maxE - stepE or
                north <= minN + stepN or north >= self.maxN - stepN):
            raise OutsideGrid("punct în afara grilei TransDatRO")
        col = int((east - minE) / stepE)
        row = int((north - minN) / stepN)
        xk = (east - (minE + col * stepE)) / stepE
        yk = (north - (minN + row * stepN)) / stepN
        ff = [0.0] * 17
        i = 1
        for py in range(4):
            for px in range(4):
                ff[i] = (xk ** px) * (yk ** py)
                i += 1
        ax = [0.0] * 17
        ay = [0.0] * 17
        k = 1
        for dr in (-1, 0, 1, 2):
            for dc in (0, 1, 2, 3):
                nc = (row + dr) * self.ncols + col + dc      # pozitie 1-based, ca in Java
                vE = self.vals[2 * (nc - 1)]
                vN = self.vals[2 * (nc - 1) + 1]
                if int(vE) == 999 or int(vN) == 999:
                    raise OutsideGrid("punct în afara graniței României (grila TransDatRO)")
                ax[k] = vE
                ay[k] = vN
                k += 1
        return _bspline(ff, ax), _bspline(ff, ay)


def _bspline(ff, az):
    cf = [0.0] * 17
    cf[1] = az[6]
    cf[2] = az[7]
    cf[3] = az[10]
    cf[4] = az[11]
    cf[5] = (-az[8] + 4 * az[7] - 3 * az[6]) / 2
    cf[6] = (3 * az[7] - 4 * az[6] + az[5]) / 2
    cf[7] = (-az[12] + 4 * az[11] - 3 * az[10]) / 2
    cf[8] = (3 * az[11] - 4 * az[10] + az[9]) / 2
    cf[9] = (-az[14] + 4 * az[10] - 3 * az[6]) / 2
    cf[10] = (-az[15] + 4 * az[11] - 3 * az[7]) / 2
    cf[11] = (3 * az[10] - 4 * az[6] + az[2]) / 2
    cf[12] = (3 * az[11] - 4 * az[7] + az[3]) / 2
    cf[13] = ((az[1] + az[11]) - (az[3] + az[9])) / 4
    cf[14] = ((az[2] + az[12]) - (az[4] + az[10])) / 4
    cf[15] = ((az[5] + az[15]) - (az[7] + az[13])) / 4
    cf[16] = ((az[6] + az[16]) - (az[8] + az[14])) / 4
    c = [0.0] * 17
    c[1] = cf[1]
    c[2] = cf[5]
    c[3] = -3 * cf[1] + 3 * cf[2] - 2 * cf[5] - cf[6]
    c[4] = 2 * cf[1] - 2 * cf[2] + cf[5] + cf[6]
    c[5] = cf[9]
    c[6] = cf[13]
    c[7] = -3 * cf[9] + 3 * cf[10] - 2 * cf[13] - cf[14]
    c[8] = 2 * cf[9] - 2 * cf[10] + cf[13] + cf[14]
    c[9] = -3 * cf[1] + 3 * cf[3] - 2 * cf[9] - cf[11]
    c[10] = -3 * cf[5] + 3 * cf[7] - 2 * cf[13] - cf[15]
    c[11] = (9 * cf[1] - 9 * cf[2] - 9 * cf[3] + 9 * cf[4] + 6 * cf[5] + 3 * cf[6] - 6 * cf[7] - 3 * cf[8]
             + 6 * cf[9] - 6 * cf[10] + 3 * cf[11] - 3 * cf[12] + 4 * cf[13] + 2 * cf[14] + 2 * cf[15] + cf[16])
    c[12] = (-6 * cf[1] + 6 * cf[2] + 6 * cf[3] - 6 * cf[4] - 3 * cf[5] - 3 * cf[6] + 3 * cf[7] + 3 * cf[8]
             - 4 * cf[9] + 4 * cf[10] - 2 * cf[11] + 2 * cf[12] - 2 * cf[13] - 2 * cf[14] - cf[15] - cf[16])
    c[13] = 2 * cf[1] - 2 * cf[3] + cf[9] + cf[11]
    c[14] = 2 * cf[5] - 2 * cf[7] + cf[13] + cf[15]
    c[15] = (-6 * cf[1] + 6 * cf[2] + 6 * cf[3] - 6 * cf[4] - 4 * cf[5] - 2 * cf[6] + 4 * cf[7] + 2 * cf[8]
             - 3 * cf[9] + 3 * cf[10] - 3 * cf[11] + 3 * cf[12] - 2 * cf[13] - cf[14] - 2 * cf[15] - cf[16])
    c[16] = (4 * cf[1] - 4 * cf[2] - 4 * cf[3] + 4 * cf[4] + 2 * cf[5] + 2 * cf[6] - 2 * cf[7] - 2 * cf[8]
             + 2 * cf[9] - 2 * cf[10] + 2 * cf[11] - 2 * cf[12] + cf[13] + cf[14] + cf[15] + cf[16])
    return sum(c[i] * ff[i] for i in range(1, 17))


def _helmert2d(E, N, p):
    tE, tN, dm, rz = p
    m = 1 + dm * 1e-6
    rz = rz * math.pi / (180 * 3600)
    return (E * m * math.cos(rz) - N * m * math.sin(rz) + tE,
            N * m * math.cos(rz) + E * m * math.sin(rz) + tN)


def _stereo_consts(a=A_ETRS89, nf=INV_F_ETRS89):
    """Constantele proiectiei stereografice pe GRS80 (ca in Stereo_FiLa_NE / Stereo_NE_FiLa)."""
    br1 = math.radians(46)
    f = 1 / nf
    b = a * (1 - f)
    ep = math.sqrt((a * a - b * b) / (a * a))
    w = math.sqrt(1 - ep * ep * math.sin(br1) ** 2)
    raza = (a * (1 - ep * ep)) / (w * w * w)
    raza = math.sqrt(raza * a / w)
    n = math.sqrt(1 + (ep * ep * math.cos(br1) ** 4) / (1 - ep * ep))
    s1 = (1 + math.sin(br1)) / (1 - math.sin(br1))
    s2 = (1 - ep * math.sin(br1)) / (1 + ep * math.sin(br1))
    w1 = math.exp(n * math.log(s1 * math.exp(ep * math.log(s2))))
    c = ((n + math.sin(br1)) * (1 - (w1 - 1) / (w1 + 1))) / ((n - math.sin(br1)) * (1 + (w1 - 1) / (w1 + 1)))
    w2 = c * w1
    hi0 = (w2 - 1) / (w2 + 1)
    hi0 = math.atan(hi0 / math.sqrt(1 - hi0 * hi0))
    return math.radians(25), 0.99975, ep, raza, n, c, hi0


_SC = _stereo_consts()


def _stereo_inv(north, east):
    la0, k0, ep, raza, n, c, hi0 = _SC
    g = 2 * raza * k0 * math.tan(math.pi / 4 - hi0 / 2)
    h = 4 * raza * k0 * math.tan(hi0) + g
    ii = math.atan((east - 500000) / (h + (north - 500000)))
    j = math.atan((east - 500000) / (g - (north - 500000))) - ii
    lam = j + 2 * ii + la0
    La = la0 + (lam - la0) / n
    hi = hi0 + 2 * math.atan((north - 500000 - (east - 500000) * math.tan(j / 2)) / (2 * raza * k0))
    csi = (0.5 * math.log((1 + math.sin(hi)) / (c * (1 - math.sin(hi))))) / n
    Fi = 2 * math.atan(math.exp(csi)) - math.pi / 2
    for _ in range(50):
        fic = Fi
        csii = math.log(math.tan(Fi / 2 + math.pi / 4) *
                        math.exp((ep / 2) * math.log((1 - ep * math.sin(Fi)) / (1 + ep * math.sin(Fi)))))
        Fi = Fi - (csii - csi) * math.cos(Fi) * (1 - ep * ep * math.sin(Fi) ** 2) / (1 - ep * ep)
        if abs(math.degrees(Fi - fic) * 3600) <= 1e-9:
            break
    return Fi, La


def _stereo_fwd(Fi, La):
    la0, k0, ep, raza, n, c, hi0 = _SC
    sa = (1 + math.sin(Fi)) / (1 - math.sin(Fi))
    sb = (1 - ep * math.sin(Fi)) / (1 + ep * math.sin(Fi))
    w = c * math.exp(n * math.log(sa * math.exp(ep * math.log(sb))))
    hi = (w - 1) / (w + 1)
    hi = math.atan(hi / math.sqrt(1 - hi * hi))
    lam = n * (La - la0) + la0
    beta = 1 + math.sin(hi) * math.sin(hi0) + math.cos(hi) * math.cos(hi0) * math.cos(lam - la0)
    east = 2 * raza * k0 * math.cos(hi) * math.sin(lam - la0) / beta + 500000
    north = 2 * raza * k0 * (math.cos(hi0) * math.sin(hi)
                             - math.sin(hi0) * math.cos(hi) * math.cos(lam - la0)) / beta + 500000
    return north, east


_GRID = None


def _grid():
    global _GRID
    if _GRID is None:
        _GRID = _Grid2D(_grid_path())
    return _GRID


def stereo70_to_etrs89(east, north):
    """(E = y, N = x) Stereo 70 -> (lon, lat) ETRS89 in grade. Ridica OutsideGrid in afara Romaniei."""
    dE, dN = _grid().shift(east, north)
    E, N = _helmert2d(east - dE, north - dN, H_ST70_OS)
    Fi, La = _stereo_inv(N, E)
    return math.degrees(La), math.degrees(Fi)


def etrs89_to_stereo70(lon, lat):
    """(lon, lat) ETRS89 -> (E = y, N = x) Stereo 70."""
    N, E = _stereo_fwd(math.radians(lat), math.radians(lon))
    E, N = _helmert2d(E, N, H_OS_ST70)
    dE, dN = _grid().shift(E, N)
    return E + dE, N + dN
