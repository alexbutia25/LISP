/* ui.h - fereastra principala TopoKit (desenata cu GDI+), vezi ui.c */
#ifndef TOPOKIT_UI_H
#define TOPOKIT_UI_H
#include <windows.h>

/* Starea afisata in fereastra (completata de lansator, topokit.c) */
enum { UI_OFF, UI_ON, UI_STARTING };
typedef struct {
    int state;                  /* UI_OFF / UI_ON / UI_STARTING */
    const wchar_t *acad;        /* "AutoCAD 2024" */
    const wchar_t *doc;         /* desenul activ ("" daca nu exista) */
    BOOL autorun;               /* porneste odata cu Windows */
    const wchar_t *note;        /* mesajul ultimei actiuni (NULL = niciunul) */
    int noteKind;               /* UI_NOTE_OK / UI_NOTE_ERR / UI_NOTE_INFO */
} UiState;
enum { UI_NOTE_OK, UI_NOTE_ERR, UI_NOTE_INFO };

/* Actiunile ferestrei, executate de lansator */
enum { ACT_CMD, ACT_START, ACT_RELOAD, ACT_AUTORUN, ACT_FOLDER, ACT_HELP, ACT_HIDDEN, ACT_DIAG };

void App_State(UiState *st);            /* implementate in topokit.c */
void App_Action(int act, int arg);

BOOL Ui_Init(HINSTANCE inst);           /* GDI+ si imaginile din resurse */
void Ui_Show(void);                     /* creeaza / aduce in fata fereastra */
void Ui_Refresh(void);                  /* starea s-a schimbat: redeseneaza */
void Ui_Destroy(void);
HWND Ui_Hwnd(void);                     /* fereastra, daca este vizibila */
BOOL Ui_Snapshot(const wchar_t *png, float scale, int hover);   /* imagine PNG (documentatie, teste) */

#endif
