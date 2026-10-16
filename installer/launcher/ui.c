/*
 * ui.c - fereastra principala TopoKit ("centrul de comanda").
 *
 * Desenata integral cu GDI+ (antialiasing, colturi rotunjite, umbre), cu
 * dublu tampon si scalare dupa DPI (Per-Monitor V2):
 *
 *   antet      sigla, numele, descrierea, versiunea; curbe de nivel decorative
 *   stare      conexiunea cu AutoCAD (punct colorat, versiune, desen activ) si
 *              butonul principal: Porneste AutoCAD / Reincarca TopoKit
 *   module     8 carduri (iconita, titlu, descriere, comanda AutoCAD); clic =
 *              comanda in desenul activ (AutoCAD porneste daca e nevoie)
 *   subsol     comutatorul "Porneste odata cu Windows", Folder, Ghid
 *
 * Inchiderea ferestrei o ascunde: lansatorul ramane in bara de sistem.
 */
#ifndef UNICODE
#define UNICODE
#endif
#define COBJMACROS
#include <windows.h>
#include <windowsx.h>
#include <shlwapi.h>
#include <gdiplus.h>
#include <math.h>
#include <stdio.h>
#include "resource.h"
#include "ui.h"

#ifndef TK_VERSION
#define TK_VERSION "1.0.0"
#endif
#define UI_CLASS L"TopoKitMainWnd"
#define W_DIP 840
#define H_DIP 600

/* Cardurile modulelor - aceeasi ordine ca tabelul CMDS din topokit.c */
static const struct { const wchar_t *title, *desc, *cmd; ARGB accent; } TILES[] = {
    { L"Meniu TopoKit", L"Toate modulele și setările într-un singur dialog", L"TOPOKIT", 0xFF1B6A8F },
    { L"Anexe ANCPI", L"Planuri și documente, Ordinul 600/2023", L"ANEXE", 0xFF6A4FB6 },
    { L"Teren și volume", L"Puncte, model TIN, curbe de nivel, calcul de volume", L"TOPOTEREN", 0xFF2E8B57 },
    { L"Verificare", L"Controlul documentației înainte de predare", L"VERIFICARE", 0xFFD08A12 },
    { L"Planșe PDF", L"Plotarea tuturor planșelor într-un singur pas", L"PLANEPDF", 0xFFC8443A },
    { L"Export KMZ", L"Parcela în Google Earth (Stereo 70 → WGS84)", L"EXPKMZ", 0xFF1F8FBF },
    { L"Cadru planșă", L"Format A4–A0, cadru, caroiaj și indicator", L"INSCADRU", 0xFF3B5B92 },
    { L"Vertexuri", L"Corecție topologică la intersecții (ADDVTX)", L"ADDVTX", 0xFFA3478F },
};
#define NTILES 8

/* Paleta */
#define C_BG        0xFFF4F7FA
#define C_CARD      0xFFFFFFFF
#define C_BORDER    0xFFDDE5EC
#define C_TEXT      0xFF1A2733
#define C_TEXT2     0xFF5B6B7A
#define C_TEXT3     0xFF7A8896
#define C_NAVY      0xFF0F3D5E
#define C_TEAL      0xFF1B6A8F
#define C_LINK      0xFF1B6A8F
#define C_OK        0xFF2EAD5B
#define C_OFF       0xFF9AA5B1
#define C_WAIT      0xFFE0A030

/* Zonele active */
enum { HT_NONE = -1, HT_TILE0 = 0, HT_PRIMARY = 20, HT_TOGGLE, HT_FOLDER, HT_HELP };

static HINSTANCE g_inst;
static HWND g_wnd;
static ULONG_PTR g_gdipToken;
static GpBitmap *g_logo, *g_icons[NTILES];
static float g_s = 1.0f;                   /* scara DPI */
static int g_hover = HT_NONE, g_pressed = HT_NONE;
static BOOL g_tracking, g_hiddenOnce;

typedef struct { float x, y, w, h; } R;
static R g_r[32];                          /* zonele, in DIP */

/* ------------------------------------------------------------------ resurse */
static GpBitmap *LoadPng(int id)
{
    HRSRC rs = FindResourceW(g_inst, MAKEINTRESOURCEW(id), (LPCWSTR)RT_RCDATA);
    HGLOBAL h;
    IStream *st;
    GpBitmap *bmp = NULL;
    if (!rs || !(h = LoadResource(g_inst, rs))) return NULL;
    st = SHCreateMemStream((const BYTE *)LockResource(h), SizeofResource(g_inst, rs));
    if (!st) return NULL;
    GdipCreateBitmapFromStream(st, &bmp);  /* fluxul ramane deschis cat traieste imaginea */
    return bmp;
}

BOOL Ui_Init(HINSTANCE inst)
{
    GdiplusStartupInput si = { 1, NULL, FALSE, FALSE };
    int i;
    g_inst = inst;
    if (GdiplusStartup(&g_gdipToken, &si, NULL) != Ok) return FALSE;
    g_logo = LoadPng(IDR_LOGO);
    for (i = 0; i < NTILES; i++) g_icons[i] = LoadPng(IDR_ICON1 + i);
    return TRUE;
}

/* ------------------------------------------------------------------ desen: utilitare */
static GpPath *RoundPath(float x, float y, float w, float h, float r)
{
    GpPath *p;
    float d = 2 * r;
    GdipCreatePath(FillModeAlternate, &p);
    GdipAddPathArc(p, x, y, d, d, 180, 90);
    GdipAddPathArc(p, x + w - d, y, d, d, 270, 90);
    GdipAddPathArc(p, x + w - d, y + h - d, d, d, 0, 90);
    GdipAddPathArc(p, x, y + h - d, d, d, 90, 90);
    GdipClosePathFigure(p);
    return p;
}

static void FillRound(GpGraphics *g, float x, float y, float w, float h, float r, ARGB c)
{
    GpPath *p = RoundPath(x, y, w, h, r);
    GpSolidFill *b;
    GdipCreateSolidFill(c, &b);
    GdipFillPath(g, (GpBrush *)b, p);
    GdipDeleteBrush((GpBrush *)b);
    GdipDeletePath(p);
}

static void StrokeRound(GpGraphics *g, float x, float y, float w, float h, float r, ARGB c, float width)
{
    GpPath *p = RoundPath(x, y, w, h, r);
    GpPen *pen;
    GdipCreatePen1(c, width, UnitPixel, &pen);
    GdipDrawPath(g, pen, p);
    GdipDeletePen(pen);
    GdipDeletePath(p);
}

/* umbra difuza sub un card */
static void Shadow(GpGraphics *g, float x, float y, float w, float h, float r, float s, BOOL strong)
{
    int i;
    for (i = 4; i >= 1; i--) {
        float e = i * s;
        BYTE a = (BYTE)((strong ? 12 : 7) - i);
        FillRound(g, x - e * 0.5f, y - e * 0.25f + (strong ? 3 : 1.5f) * s, w + e, h + e, r + e * 0.5f,
                  ((ARGB)a << 24) | 0x0F2A40);
    }
}

static void Dot(GpGraphics *g, float cx, float cy, float r, ARGB c)
{
    GpSolidFill *b;
    GdipCreateSolidFill(c, &b);
    GdipFillEllipse(g, (GpBrush *)b, cx - r, cy - r, 2 * r, 2 * r);
    GdipDeleteBrush((GpBrush *)b);
}

typedef struct { GpFontFamily *ui, *semi, *mono; BOOL semiIsBold; } Families;
static Families g_fam;

static void InitFamilies(void)
{
    if (g_fam.ui) return;
    if (GdipCreateFontFamilyFromName(L"Segoe UI", NULL, &g_fam.ui) != Ok)
        GdipGetGenericFontFamilySansSerif(&g_fam.ui);
    if (GdipCreateFontFamilyFromName(L"Segoe UI Semibold", NULL, &g_fam.semi) != Ok) {
        g_fam.semi = g_fam.ui;
        g_fam.semiIsBold = TRUE;
    }
    if (GdipCreateFontFamilyFromName(L"Consolas", NULL, &g_fam.mono) != Ok)
        GdipGetGenericFontFamilyMonospace(&g_fam.mono);
}

/* font: 0 normal, 1 semibold, 2 mono, 3 normal subliniat */
static GpFont *Font(int kind, float px)
{
    GpFont *f = NULL;
    GpFontFamily *fam = kind == 1 ? g_fam.semi : kind == 2 ? g_fam.mono : g_fam.ui;
    INT style = kind == 1 && g_fam.semiIsBold ? FontStyleBold : kind == 3 ? FontStyleUnderline : FontStyleRegular;
    GdipCreateFont(fam, px * g_s, style, UnitPixel, &f);
    return f;
}

/* text in dreptunghi; align/valign: 0 stanga/sus, 1 centru, 2 dreapta/jos */
static void Text(GpGraphics *g, const wchar_t *t, GpFont *f, ARGB c, R r, int align, int valign, BOOL wrap)
{
    GpStringFormat *sf;
    GpSolidFill *b;
    RectF rf = { r.x * g_s, r.y * g_s, r.w * g_s, r.h * g_s };
    GdipCreateStringFormat(wrap ? StringFormatFlagsLineLimit : StringFormatFlagsNoWrap, LANG_NEUTRAL, &sf);
    GdipSetStringFormatAlign(sf, (StringAlignment)align);
    GdipSetStringFormatLineAlign(sf, (StringAlignment)valign);
    GdipSetStringFormatTrimming(sf, wrap ? StringTrimmingEllipsisWord : StringTrimmingEllipsisCharacter);
    GdipCreateSolidFill(c, &b);
    GdipDrawString(g, t, -1, f, &rf, sf, (GpBrush *)b);
    GdipDeleteBrush((GpBrush *)b);
    GdipDeleteStringFormat(sf);
}

static float TextWidth(GpGraphics *g, const wchar_t *t, GpFont *f)
{
    RectF lay = { 0, 0, 10000, 1000 }, box = { 0 };
    GdipMeasureString(g, t, -1, f, &lay, NULL, &box, NULL, NULL);
    return box.Width / g_s;
}

static void DrawImg(GpGraphics *g, GpBitmap *b, float x, float y, float w, float h)
{
    if (b) GdipDrawImageRect(g, (GpImage *)b, x * g_s, y * g_s, w * g_s, h * g_s);
}

/* curba de nivel decorativa (aceeasi forma ca in sigla) */
static void Contour(GpGraphics *g, float cx, float cy, float r, float k, ARGB c, float width)
{
    PointF pts[97];
    GpPen *pen;
    int i;
    for (i = 0; i < 97; i++) {
        float a = 2 * 3.14159265f * i / 96;
        float rr = r * (1 + 0.12f * sinf(3 * a + k));
        pts[i].X = (cx + rr * cosf(a)) * g_s;
        pts[i].Y = (cy + 0.78f * rr * sinf(a)) * g_s;
    }
    GdipCreatePen1(c, width * g_s, UnitPixel, &pen);
    GdipDrawCurve(g, pen, pts, 97);
    GdipDeletePen(pen);
}

/* ------------------------------------------------------------------ asezare */
static void Layout(void)
{
    int i;
    float tw = (W_DIP - 48 - 3 * 16) / 4.0f, th = 132;
    g_r[HT_PRIMARY] = (R){ W_DIP - 24 - 16 - 178, 120 + 18, 178, 36 };
    for (i = 0; i < NTILES; i++)
        g_r[HT_TILE0 + i] = (R){ 24 + (i % 4) * (tw + 16), 240 + (i / 4) * (th + 16), tw, th };
    g_r[HT_TOGGLE] = (R){ 24, 556, 290, 28 };
    g_r[HT_HELP] = (R){ W_DIP - 24 - 128, 556, 128, 28 };
    g_r[HT_FOLDER] = (R){ W_DIP - 24 - 128 - 12 - 116, 556, 116, 28 };
}

static int HitTest(int px, int py)
{
    float x = px / g_s, y = py / g_s;
    int ids[] = { HT_PRIMARY, HT_TOGGLE, HT_FOLDER, HT_HELP, 0, 1, 2, 3, 4, 5, 6, 7 };
    unsigned i;
    UiState st;
    for (i = 0; i < sizeof ids / sizeof ids[0]; i++) {
        R r = g_r[ids[i]];
        if (x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h) {
            if (ids[i] == HT_PRIMARY) {
                App_State(&st);
                if (st.state == UI_STARTING) return HT_NONE;      /* buton inactiv */
            }
            return ids[i];
        }
    }
    return HT_NONE;
}

/* ------------------------------------------------------------------ desenul ferestrei */
static void Paint(GpGraphics *g, int hover, int pressed)
{
    UiState st;
    GpFont *fTitle, *fSub, *fH, *fBody, *fSmall, *fMono, *fBtn, *fLabel, *fLink, *fLinkU;
    GpLineGradient *grad;
    PointF p1 = { 0, 0 }, p2;
    wchar_t line1[160], line2[MAX_PATH + 64];
    ARGB dot;
    int i;
    float s = g_s;

    App_State(&st);
    InitFamilies();
    fTitle = Font(1, 27); fSub = Font(0, 13.5f); fH = Font(1, 15.5f); fBody = Font(0, 12.5f);
    fSmall = Font(0, 11.5f); fMono = Font(2, 10.5f); fBtn = Font(1, 13); fLabel = Font(1, 11);
    fLink = Font(0, 13); fLinkU = Font(3, 13);

    GdipSetSmoothingMode(g, SmoothingModeAntiAlias);
    GdipSetPixelOffsetMode(g, PixelOffsetModeHalf);
    GdipSetInterpolationMode(g, InterpolationModeHighQualityBicubic);
    GdipSetTextRenderingHint(g, TextRenderingHintClearTypeGridFit);
    GdipGraphicsClear(g, C_BG);

    /* --- antet */
    p2.X = W_DIP * s; p2.Y = 104 * s;
    GdipCreateLineBrush(&p1, &p2, C_NAVY, 0xFF1E6F93, WrapModeTile, &grad);
    GdipFillRectangle(g, (GpBrush *)grad, 0, 0, W_DIP * s, 104 * s);
    GdipDeleteBrush((GpBrush *)grad);
    GdipSetClipRect(g, 0, 0, W_DIP * s, 104 * s, CombineModeReplace);
    for (i = 0; i < 5; i++) Contour(g, 700, 70, 40.0f + 34 * i, (float)i, 0x22FFFFFF, 1.6f);
    for (i = 0; i < 3; i++) Contour(g, 340, -30, 60.0f + 40 * i, 2.0f + i, 0x14FFFFFF, 1.4f);
    GdipResetClip(g);
    DrawImg(g, g_logo, 24, 22, 60, 60);
    StrokeRound(g, 25.5f * s, 23.5f * s, 57 * s, 57 * s, 13 * s, 0x40FFFFFF, 1.2f * s);
    Text(g, L"TopoKit", fTitle, 0xFFFFFFFF, (R){ 100, 20, 400, 38 }, 0, 1, FALSE);
    Text(g, L"Topografie și cadastru pentru AutoCAD", fSub, 0xD8FFFFFF, (R){ 101, 58, 460, 24 }, 0, 1, FALSE);
    FillRound(g, (W_DIP - 24 - 70) * s, 22 * s, 70 * s, 24 * s, 12 * s, 0x2EFFFFFF);
    Text(g, L"v" TK_VERSION, fSmall, 0xFFFFFFFF, (R){ W_DIP - 24 - 70, 22, 70, 24 }, 1, 1, FALSE);

    /* --- starea conexiunii */
    {
        R c = { 24, 120, W_DIP - 48, 72 };
        R b = g_r[HT_PRIMARY];
        const wchar_t *btn;
        BOOL primary = st.state == UI_OFF, hot = hover == HT_PRIMARY, down = pressed == HT_PRIMARY;
        Shadow(g, c.x * s, c.y * s, c.w * s, c.h * s, 12 * s, s, FALSE);
        FillRound(g, c.x * s, c.y * s, c.w * s, c.h * s, 12 * s, C_CARD);
        StrokeRound(g, c.x * s, c.y * s, c.w * s, c.h * s, 12 * s, C_BORDER, 1 * s);
        if (st.state == UI_ON) {
            dot = C_OK;
            swprintf(line1, 160, L"Conectat la %ls", st.acad);
            if (st.doc && st.doc[0]) swprintf(line2, MAX_PATH + 64, L"Desen activ: %ls", st.doc);
            else swprintf(line2, MAX_PATH + 64, L"Niciun desen deschis – TopoKit creează unul la prima comandă");
            btn = L"Reîncarcă TopoKit";
        } else if (st.state == UI_STARTING) {
            dot = C_WAIT;
            swprintf(line1, 160, L"Se pornește AutoCAD…");
            swprintf(line2, MAX_PATH + 64, L"Comanda aleasă se deschide imediat ce AutoCAD este gata");
            btn = L"Se pornește…";
        } else {
            dot = C_OFF;
            swprintf(line1, 160, L"AutoCAD nu rulează");
            swprintf(line2, MAX_PATH + 64, L"Alegeți un modul sau porniți AutoCAD – TopoKit se conectează automat");
            btn = L"Pornește AutoCAD";
        }
        Dot(g, (c.x + 30) * s, (c.y + 36) * s, 13 * s, (dot & 0x00FFFFFF) | 0x33000000);
        Dot(g, (c.x + 30) * s, (c.y + 36) * s, 6.5f * s, dot);
        Text(g, line1, fH, C_TEXT, (R){ c.x + 56, c.y + 13, b.x - c.x - 72, 24 }, 0, 1, FALSE);
        Text(g, line2, fBody, C_TEXT2, (R){ c.x + 56, c.y + 38, b.x - c.x - 72, 20 }, 0, 1, FALSE);
        if (st.state == UI_STARTING) {
            FillRound(g, b.x * s, b.y * s, b.w * s, b.h * s, 8 * s, 0xFFE9EEF2);
            Text(g, btn, fBtn, C_TEXT3, b, 1, 1, FALSE);
        } else if (primary) {
            FillRound(g, b.x * s, (b.y + (down ? 1 : 0)) * s, b.w * s, b.h * s, 8 * s,
                      down ? 0xFF0B2F49 : hot ? C_TEAL : C_NAVY);
            Text(g, btn, fBtn, 0xFFFFFFFF, (R){ b.x, b.y + (down ? 1 : 0), b.w, b.h }, 1, 1, FALSE);
        } else {
            FillRound(g, b.x * s, b.y * s, b.w * s, b.h * s, 8 * s, down ? 0xFFE3ECF4 : hot ? 0xFFEEF4F9 : C_CARD);
            StrokeRound(g, b.x * s, b.y * s, b.w * s, b.h * s, 8 * s, hot ? C_TEAL : 0xFFC9D6E2, 1 * s);
            Text(g, btn, fBtn, C_NAVY, b, 1, 1, FALSE);
        }
    }

    /* --- modulele */
    Text(g, L"MODULE", fLabel, C_TEXT3, (R){ 26, 212, 200, 20 }, 0, 1, FALSE);
    Text(g, L"Clic pe un modul pentru a-l deschide în AutoCAD", fSmall, C_TEXT3,
         (R){ W_DIP - 24 - 420, 212, 420, 20 }, 2, 1, FALSE);
    for (i = 0; i < NTILES; i++) {
        R t = g_r[HT_TILE0 + i];
        BOOL hot = hover == i, down = pressed == i;
        float dy = hot && !down ? -1.5f : 0;
        float cw;
        t.y += dy;
        Shadow(g, t.x * s, t.y * s, t.w * s, t.h * s, 12 * s, s, hot);
        FillRound(g, t.x * s, t.y * s, t.w * s, t.h * s, 12 * s, down ? 0xFFF1F6FA : hot ? 0xFFFCFEFF : C_CARD);
        StrokeRound(g, t.x * s, t.y * s, t.w * s, t.h * s, 12 * s, hot ? TILES[i].accent : 0xFFE1E8EE,
                    (hot ? 1.6f : 1.0f) * s);
        DrawImg(g, g_icons[i], t.x + 18, t.y + 18, 44, 44);
        cw = TextWidth(g, TILES[i].cmd, fMono) + 14;
        FillRound(g, (t.x + t.w - 14 - cw) * s, (t.y + 18) * s, cw * s, 20 * s, 6 * s, 0xFFEEF2F6);
        Text(g, TILES[i].cmd, fMono, C_TEXT2, (R){ t.x + t.w - 14 - cw, t.y + 18, cw, 20 }, 1, 1, FALSE);
        Text(g, TILES[i].title, fH, C_TEXT, (R){ t.x + 18, t.y + 72, t.w - 30, 22 }, 0, 1, FALSE);
        Text(g, TILES[i].desc, fBody, C_TEXT2, (R){ t.x + 18, t.y + 95, t.w - 30, 34 }, 0, 0, TRUE);
    }

    /* --- subsol */
    {
        GpPen *pen;
        R tg = g_r[HT_TOGGLE];
        float kx;
        GdipCreatePen1(0xFFE1E8EE, 1 * s, UnitPixel, &pen);
        GdipDrawLine(g, pen, 0, 540 * s, W_DIP * s, 540 * s);
        GdipDeletePen(pen);
        FillRound(g, tg.x * s, (tg.y + 4) * s, 40 * s, 20 * s, 10 * s,
                  st.autorun ? (hover == HT_TOGGLE ? C_TEAL : C_NAVY) : (hover == HT_TOGGLE ? 0xFFB3BFCA : 0xFFC5CFD8));
        kx = st.autorun ? tg.x + 30 : tg.x + 10;
        Dot(g, kx * s, (tg.y + 14) * s, 7.5f * s, 0xFFFFFFFF);
        Text(g, L"Pornește TopoKit odată cu Windows (în fundal)", fLink, C_TEXT,
             (R){ tg.x + 52, tg.y, tg.w + 40, tg.h }, 0, 1, FALSE);
        Text(g, L"Folder TopoKit", hover == HT_FOLDER ? fLinkU : fLink, C_LINK, g_r[HT_FOLDER], 2, 1, FALSE);
        Text(g, L"Ghid de utilizare", hover == HT_HELP ? fLinkU : fLink, C_LINK, g_r[HT_HELP], 2, 1, FALSE);
    }

    GdipDeleteFont(fTitle); GdipDeleteFont(fSub); GdipDeleteFont(fH); GdipDeleteFont(fBody);
    GdipDeleteFont(fSmall); GdipDeleteFont(fMono); GdipDeleteFont(fBtn); GdipDeleteFont(fLabel);
    GdipDeleteFont(fLink); GdipDeleteFont(fLinkU);
}

static void OnPaint(HWND h)
{
    PAINTSTRUCT ps;
    RECT rc;
    HDC dc = BeginPaint(h, &ps), mem;
    HBITMAP bmp, old;
    GpGraphics *g;
    GetClientRect(h, &rc);
    mem = CreateCompatibleDC(dc);
    bmp = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
    old = (HBITMAP)SelectObject(mem, bmp);
    if (GdipCreateFromHDC(mem, &g) == Ok) {
        Paint(g, g_hover, g_pressed);
        GdipDeleteGraphics(g);
    }
    BitBlt(dc, 0, 0, rc.right, rc.bottom, mem, 0, 0, SRCCOPY);
    SelectObject(mem, old);
    DeleteObject(bmp);
    DeleteDC(mem);
    EndPaint(h, &ps);
}

/* ------------------------------------------------------------------ DPI */
static UINT WindowDpi(HWND h)
{
    typedef UINT(WINAPI * GetDpiForWindowFn)(HWND);
    static GetDpiForWindowFn fn;
    static BOOL looked;
    HDC dc;
    UINT dpi;
    if (!looked) {
        fn = (GetDpiForWindowFn)(void *)GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow");
        looked = TRUE;
    }
    if (fn && h) return fn(h);
    dc = GetDC(NULL);
    dpi = (UINT)GetDeviceCaps(dc, LOGPIXELSX);
    ReleaseDC(NULL, dc);
    return dpi ? dpi : 96;
}

static void FitWindow(HWND h, const RECT *suggested)
{
    RECT r = { 0, 0, (LONG)(W_DIP * g_s + 0.5f), (LONG)(H_DIP * g_s + 0.5f) };
    DWORD style = (DWORD)GetWindowLongPtrW(h, GWL_STYLE), ex = (DWORD)GetWindowLongPtrW(h, GWL_EXSTYLE);
    AdjustWindowRectEx(&r, style, FALSE, ex);
    if (suggested)
        SetWindowPos(h, NULL, suggested->left, suggested->top, r.right - r.left, r.bottom - r.top,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    else
        SetWindowPos(h, NULL, 0, 0, r.right - r.left, r.bottom - r.top, SWP_NOZORDER | SWP_NOMOVE | SWP_NOACTIVATE);
}

/* bara de titlu in culoarea antetului (Windows 11; ignorat in rest) */
static void TitleBarColor(HWND h)
{
    typedef HRESULT(WINAPI * DwmSetFn)(HWND, DWORD, LPCVOID, DWORD);
    HMODULE m = LoadLibraryW(L"dwmapi.dll");
    if (m) {
        DwmSetFn set = (DwmSetFn)(void *)GetProcAddress(m, "DwmSetWindowAttribute");
        COLORREF cap = RGB(0x0F, 0x3D, 0x5E), txt = RGB(0xFF, 0xFF, 0xFF);
        if (set) {
            set(h, 35 /* DWMWA_CAPTION_COLOR */, &cap, sizeof cap);
            set(h, 36 /* DWMWA_TEXT_COLOR */, &txt, sizeof txt);
        }
    }
}

/* ------------------------------------------------------------------ fereastra */
static void Activate(int ht)
{
    if (ht >= HT_TILE0 && ht < HT_TILE0 + NTILES) App_Action(ACT_CMD, ht - HT_TILE0);
    else if (ht == HT_PRIMARY) {
        UiState st;
        App_State(&st);
        App_Action(st.state == UI_ON ? ACT_RELOAD : ACT_START, 0);
    } else if (ht == HT_TOGGLE) App_Action(ACT_AUTORUN, 0);
    else if (ht == HT_FOLDER) App_Action(ACT_FOLDER, 0);
    else if (ht == HT_HELP) App_Action(ACT_HELP, 0);
    InvalidateRect(g_wnd, NULL, FALSE);
}

static LRESULT CALLBACK UiProc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_PAINT:
        OnPaint(h);
        return 0;
    case WM_ERASEBKGND:
        return 1;
    case WM_MOUSEMOVE: {
        int ht = HitTest(GET_X_LPARAM(lp), GET_Y_LPARAM(lp));
        if (!g_tracking) {
            TRACKMOUSEEVENT tme = { sizeof tme, TME_LEAVE, h, 0 };
            TrackMouseEvent(&tme);
            g_tracking = TRUE;
        }
        if (ht != g_hover) { g_hover = ht; InvalidateRect(h, NULL, FALSE); }
        return 0;
    }
    case WM_MOUSELEAVE:
        g_tracking = FALSE;
        if (g_hover != HT_NONE) { g_hover = HT_NONE; InvalidateRect(h, NULL, FALSE); }
        return 0;
    case WM_SETCURSOR:
        if (LOWORD(lp) == HTCLIENT) {
            POINT pt;
            GetCursorPos(&pt);
            ScreenToClient(h, &pt);
            SetCursor(LoadCursorW(NULL, HitTest(pt.x, pt.y) != HT_NONE ? IDC_HAND : IDC_ARROW));
            return TRUE;
        }
        break;
    case WM_LBUTTONDOWN:
        g_pressed = HitTest(GET_X_LPARAM(lp), GET_Y_LPARAM(lp));
        if (g_pressed != HT_NONE) { SetCapture(h); InvalidateRect(h, NULL, FALSE); }
        return 0;
    case WM_LBUTTONUP: {
        int ht = HitTest(GET_X_LPARAM(lp), GET_Y_LPARAM(lp)), was = g_pressed;
        g_pressed = HT_NONE;
        if (GetCapture() == h) ReleaseCapture();
        InvalidateRect(h, NULL, FALSE);
        if (was != HT_NONE && ht == was) Activate(ht);
        return 0;
    }
    case WM_KEYDOWN:
        if (wp == VK_ESCAPE) { SendMessageW(h, WM_CLOSE, 0, 0); return 0; }
        if (wp == VK_RETURN) { App_Action(ACT_CMD, 0); return 0; }
        if (wp >= '1' && wp <= '8') { App_Action(ACT_CMD, (int)(wp - '1')); return 0; }
        break;
    case WM_DPICHANGED:
        g_s = HIWORD(wp) / 96.0f;
        FitWindow(h, (RECT *)lp);
        InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_CLOSE:
        ShowWindow(h, SW_HIDE);
        if (!g_hiddenOnce) { g_hiddenOnce = TRUE; App_Action(ACT_HIDDEN, 0); }
        return 0;
    case WM_DESTROY:
        g_wnd = NULL;
        return 0;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

void Ui_Show(void)
{
    if (!g_wnd) {
        WNDCLASSEXW wc;
        RECT wa;
        int w, hgt;
        memset(&wc, 0, sizeof wc);
        wc.cbSize = sizeof wc;
        wc.style = CS_HREDRAW | CS_VREDRAW;
        wc.lpfnWndProc = UiProc;
        wc.hInstance = g_inst;
        wc.hIcon = LoadIconW(g_inst, MAKEINTRESOURCEW(IDI_APP));
        wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
        wc.lpszClassName = UI_CLASS;
        RegisterClassExW(&wc);
        Layout();
        g_wnd = CreateWindowExW(0, UI_CLASS, L"TopoKit", WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                                CW_USEDEFAULT, CW_USEDEFAULT, 100, 100, NULL, NULL, g_inst, NULL);
        if (!g_wnd) return;
        g_s = WindowDpi(g_wnd) / 96.0f;
        FitWindow(g_wnd, NULL);
        TitleBarColor(g_wnd);
        {   /* centrat pe zona de lucru */
            RECT r;
            GetWindowRect(g_wnd, &r);
            SystemParametersInfoW(SPI_GETWORKAREA, 0, &wa, 0);
            w = r.right - r.left;
            hgt = r.bottom - r.top;
            SetWindowPos(g_wnd, NULL, wa.left + (wa.right - wa.left - w) / 2, wa.top + (wa.bottom - wa.top - hgt) / 2,
                         0, 0, SWP_NOSIZE | SWP_NOZORDER);
        }
    }
    if (IsIconic(g_wnd)) ShowWindow(g_wnd, SW_RESTORE);
    ShowWindow(g_wnd, SW_SHOW);
    SetForegroundWindow(g_wnd);
    InvalidateRect(g_wnd, NULL, FALSE);
}

void Ui_Refresh(void)
{
    if (g_wnd && IsWindowVisible(g_wnd)) InvalidateRect(g_wnd, NULL, FALSE);
}

void Ui_Destroy(void)
{
    if (g_wnd) DestroyWindow(g_wnd);
}

/* Imaginea ferestrei (fara bara de titlu) intr-un fisier PNG */
BOOL Ui_Snapshot(const wchar_t *png, float scale, int hover)
{
    static const CLSID pngEnc = { 0x557cf406, 0x1a04, 0x11d3, { 0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e } };
    GpBitmap *bmp;
    GpGraphics *g;
    GpStatus stt;
    g_s = scale;
    Layout();
    if (GdipCreateBitmapFromScan0((INT)(W_DIP * scale), (INT)(H_DIP * scale), 0, PixelFormat32bppARGB, NULL, &bmp) != Ok)
        return FALSE;
    GdipGetImageGraphicsContext((GpImage *)bmp, &g);
    Paint(g, hover, HT_NONE);
    GdipDeleteGraphics(g);
    stt = GdipSaveImageToFile((GpImage *)bmp, png, &pngEnc, NULL);
    GdipDisposeImage((GpImage *)bmp);
    return stt == Ok;
}
