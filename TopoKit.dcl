// ===========================================================================
//  TopoKit.dcl  -  Interfata grafica (DCL) pentru suita TopoKit (AutoLISP)
//  Instrumente pentru topografie si cadastru:
//    1. Corectie topologica (vertexi la intersectii de polilinii)
//    2. Export KMZ (parcela sau tot desenul, TransDatRO) - EXPKMZ, DWGKMZ
//    3. Inserare format, cadru si indicator la scara (A4 - A0)
//    4. Generatorul de anexe pentru Ordinul ANCPI nr. 600/2023
//       (TopoKitAnexe.lsp: PAD, dezlipire/alipire, releveu, documente Word)
//    5. Modulul de teren (TopoKitTeren.lsp: puncte, TIN, curbe, volume, raster, KML)
//    6. Calcul inclinatie (TopoKitInclinare.lsp, comanda INCLINARE)
//
//  Imaginile (sigla, pictogramele si previzualizarea plansei) sunt desenate
//  din TopoKit.lsp cu vector_image / fill_image.
//
//  Fisierul este optional: daca nu este gasit in caile de suport AutoCAD,
//  TopoKit.lsp genereaza automat o copie identica intr-un fisier temporar.
// ===========================================================================

// ---- elemente reutilizabile -------------------------------------------------
tk_icon : image {
  width = 34;
  height = 6.5;
  fixed_width = true;
  fixed_height = true;
  alignment = centered;
  color = -15;
}

tk_action : button {
  height = 2.2;
  fixed_height = true;
  width = 30;
  fixed_width = true;
  alignment = centered;
}

tk_modul : boxed_column {
  width = 42;
  fixed_width = true;
}

// ---------------------------------------------------------------------------
//  Dialogul principal (comenzile TOPOKIT / MYTOPO): modulele ca in fereastra
//  TopoKit - carduri cu pictograma colorata, titlu, comanda si descriere.
//  Clic pe pictograma = modulul. Pictogramele si antetul sunt desenate din
//  TopoKit.lsp (TK:DrawCardIcon, TK:DrawHeader).
// ---------------------------------------------------------------------------
tk_card : boxed_column {
  label = "";
  width = 31;
  fixed_width = true;
}

tk_ico : image_button {
  width = 7.5;
  height = 3.4;
  fixed_width = true;
  fixed_height = true;
  color = -15;
}

topokit_main : dialog {
  label = "TopoKit - Topografie si Cadastru";

  // ---------------- antet: sigla, nume, versiune ----------------
  : image { key = "img_head"; width = 128; height = 4.6; fixed_height = true; color = -15; }
  : row {
    : text { key = "tx_titlu"; label = ""; width = 60; }
    : text { key = "tx_conn"; label = ""; width = 60; alignment = right; }
  }

  // ---------------- modulele ----------------
  : text { label = "MODULE  -  clic pe pictograma unui modul pentru a-l deschide"; }
  : row {
    fixed_width = true;
    : tk_card {
      : row {
        : tk_ico { key = "bt_setari"; }
        : column {
          : text { label = "Setari module"; }
          : text { label = "TOPOKIT"; }
        }
      }
      : paragraph {
        : text_part { label = "Optiuni: vertexi, KMZ,"; }
        : text_part { label = "format si cadru"; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_anexe"; }
        : column {
          : text { label = "Anexe ANCPI"; }
          : text { label = "ANEXE"; }
        }
      }
      : paragraph {
        : text_part { label = "Planuri si documente,"; }
        : text_part { key = "tx_anexe"; label = ""; width = 30; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_teren"; }
        : column {
          : text { label = "Teren si volume"; }
          : text { label = "TOPOTEREN"; }
        }
      }
      : paragraph {
        : text_part { label = "Puncte, TIN, curbe, volume"; }
        : text_part { key = "tx_teren"; label = ""; width = 30; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_verif"; }
        : column {
          : text { label = "Verificare"; }
          : text { label = "VERIFICARE"; }
        }
      }
      : paragraph {
        : text_part { label = "Controlul documentatiei"; }
        : text_part { label = "inainte de predare"; }
      }
    }
  }
  : row {
    fixed_width = true;
    : tk_card {
      : row {
        : tk_ico { key = "bt_pdf"; }
        : column {
          : text { label = "Planse PDF"; }
          : text { label = "PLANEPDF"; }
        }
      }
      : paragraph {
        : text_part { label = "Plotarea tuturor planselor"; }
        : text_part { label = "intr-un singur pas"; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_kmz"; }
        : column {
          : text { label = "Export KMZ"; }
          : text { label = "EXPKMZ"; }
        }
      }
      : paragraph {
        : text_part { label = "Parcela in Google Earth"; }
        : text_part { label = "Stereo 70 > ETRS89"; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_dwgkmz"; }
        : column {
          : text { label = "DWG to KMZ"; }
          : text { label = "DWGKMZ"; }
        }
      }
      : paragraph {
        : text_part { label = "Convertor DXF/DWG in"; }
        : text_part { label = "Google Earth, TransDatRO"; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_cadru"; }
        : column {
          : text { label = "Cadru plansa"; }
          : text { label = "INSCADRU"; }
        }
      }
      : paragraph {
        : text_part { label = "Format A4 - A0, cadru,"; }
        : text_part { label = "caroiaj si indicator"; }
      }
    }
  }
  : row {
    fixed_width = true;
    : tk_card {
      : row {
        : tk_ico { key = "bt_addvtx"; }
        : column {
          : text { label = "Vertexi"; }
          : text { label = "ADDVTX"; }
        }
      }
      : paragraph {
        : text_part { label = "Corectie topologica"; }
        : text_part { label = "la intersectii"; }
      }
    }
    : tk_card {
      : row {
        : tk_ico { key = "bt_incl"; }
        : column {
          : text { label = "Calcul inclinatie"; }
          : text { label = "PLANINCL"; }
        }
      }
      : paragraph {
        : text_part { label = "Plan Inclinare: DWG/DXF, CSV,"; }
        : text_part { key = "tx_incl"; label = ""; width = 30; }
      }
    }
    : spacer { width = 64; }
  }

  : spacer { height = 0.3; }
  : boxed_row {
    label = "Stare";
    : text { key = "tx_status"; label = ""; width = 100; }
  }
  : row {
    : text { label = "Setarile sunt memorate pe durata sesiunii AutoCAD."; }
    : button { key = "bt_setari2"; label = "Setari module..."; mnemonic = "S"; width = 18; fixed_width = true; }
    : button { key = "bt_despre"; label = "Despre..."; mnemonic = "D"; width = 13; fixed_width = true; }
    : button { key = "cancel"; label = "Inchide"; width = 13; fixed_width = true; is_cancel = true; }
  }
  errtile;
}

// ---------------------------------------------------------------------------
//  Setarile modulelor 1-3 (butonul "Setari module..." din meniul principal)
// ---------------------------------------------------------------------------
topokit_setari : dialog {
  label = "TopoKit - Setari module";
  : row {
    // ---------------- 1. Corectie topologica ----------------
    : tk_modul {
      label = " 1   Corectie Topologica ";
      : tk_icon { key = "img_topo"; }
      : paragraph {
        : text_part { label = "Adauga vertexi la intersectiile si"; }
        : text_part { label = "contactele poliliniilor selectate."; }
        : text_part { label = "Cotele Z si arcele raman neschimbate."; }
      }
      : boxed_column {
        label = "Optiuni";
        : toggle { key = "tg_contact"; label = "Puncte de contact (T, suprapuneri)"; mnemonic = "P"; }
        : edit_box { key = "eb_tol"; label = "Toleranta [m]:"; edit_width = 10; mnemonic = "T"; }
        : spacer { height = 3.2; }
      }
      : spacer { height = 0.3; }
      : tk_action { key = "bt_addvtx"; label = "Corectie Topologica"; mnemonic = "C"; }
      : text { label = "Comanda directa: ADDVTX"; alignment = centered; }
    }

    // ---------------- 2. Export KMZ ----------------
    : tk_modul {
      label = " 2   Export Google Earth ";
      : tk_icon { key = "img_kmz"; }
      : paragraph {
        : text_part { label = "Parcela sau obiecte pe straturi"; }
        : text_part { label = "in KMZ: Stereo 70 > ETRS89 (TransDatRO)."; }
        : text_part { key = "tx_grid"; label = ""; width = 38; }
      }
      : boxed_column {
        label = "Optiuni";
        : edit_box { key = "eb_nume"; label = "Nume parcela:"; edit_width = 17; mnemonic = "N"; }
        : radio_row {
          key = "rr_kmz";
          : radio_button { key = "rb_kmz"; label = "KMZ"; }
          : radio_button { key = "rb_kml"; label = "KML"; }
        }
        : toggle { key = "tg_grid";   label = "TransDatRO ANCPI (precizie mm)"; mnemonic = "G"; }
        : toggle { key = "tg_puncte"; label = "Puncte de contur / inventar"; }
        : toggle { key = "tg_swap";   label = "Axe inversate (X desen = Nord)"; }
        : toggle { key = "tg_ge";     label = "Deschide in Google Earth Pro"; }
      }
      : spacer { height = 0.3; }
      : tk_action { key = "bt_kmz"; label = "Export KMZ parcela"; mnemonic = "E"; }
      : tk_action { key = "bt_dwgkmz"; label = "Transformator DWG > KMZ"; mnemonic = "W"; }
      : text { label = "Comenzi directe: EXPKMZ, DWGKMZ"; alignment = centered; }
    }

    // ---------------- 3. Format si cadru ----------------
    : tk_modul {
      label = " 3   Format si Cadru ";
      : tk_icon { key = "img_cadru"; }
      : paragraph {
        : text_part { key = "tx_dim"; label = ""; width = 38; }
        : text_part { label = "Cadru, spatiu util si indicator pe"; }
        : text_part { label = "stratul L_CADRU, in Model Space."; }
      }
      : boxed_column {
        label = "Optiuni";
        : popup_list { key = "pl_format"; label = "Format:"; edit_width = 13; mnemonic = "F"; }
        : radio_row {
          key = "rr_orient";
          : radio_button { key = "rb_port"; label = "Portrait"; }
          : radio_button { key = "rb_land"; label = "Landscape"; }
        }
        : popup_list { key = "pl_scara"; label = "Scara:"; edit_width = 13; mnemonic = "S"; }
        : toggle { key = "tg_caroiaj"; label = "Caroiaj de coordonate (10 cm)"; }
        : spacer { height = 1.1; }
      }
      : spacer { height = 0.3; }
      : tk_action { key = "bt_cadru"; label = "Inserare Format si Cadru"; mnemonic = "I"; }
      : text { label = "Comanda directa: INSCADRU"; alignment = centered; }
    }
  }
  : spacer { height = 0.3; }
  : row {
    : text { label = "Setarile sunt memorate pe durata sesiunii AutoCAD."; }
    : button { key = "accept"; label = "OK"; width = 13; fixed_width = true; is_default = true; }
    : button { key = "cancel"; label = "Renunta"; width = 13; fixed_width = true; is_cancel = true; }
  }
  errtile;
}

// ---------------------------------------------------------------------------
//  Sub-dialog dedicat comenzii INSCADRU (format, scara, indicator)
// ---------------------------------------------------------------------------
topokit_cadru : dialog {
  label = "TopoKit - Inserare Format, Cadru si Indicator";
  : row {
    : column {
      : boxed_column {
        label = "Previzualizare";
        : image { key = "img_cadru"; width = 34; height = 10; fixed_width = true; fixed_height = true; color = -15; alignment = centered; }
        : text { key = "tx_dim"; label = ""; width = 34; alignment = centered; }
      }
      : boxed_column {
        label = "Format si scara";
        : popup_list { key = "pl_format"; label = "Format pagina:"; edit_width = 13; mnemonic = "F"; }
        : radio_row {
          key = "rr_orient";
          : radio_button { key = "rb_port"; label = "Portrait"; }
          : radio_button { key = "rb_land"; label = "Landscape"; }
        }
        : popup_list { key = "pl_scara"; label = "Scara desenului:"; edit_width = 13; mnemonic = "S"; }
        : toggle { key = "tg_caroiaj"; label = "Caroiaj de coordonate (10 cm)"; }
      }
    }
    : column {
      : boxed_column {
        label = "Indicator (cartus)";
        : edit_box { key = "eb_benef";   label = "Beneficiar:";   edit_width = 32; mnemonic = "B"; }
        : edit_box { key = "eb_lucrare"; label = "Lucrarea:";     edit_width = 32; mnemonic = "L"; }
        : edit_box { key = "eb_titlu";   label = "Titlu plansa:"; edit_width = 32; mnemonic = "T"; }
        : edit_box { key = "eb_exec";    label = "Executant:";    edit_width = 32; mnemonic = "E"; }
        : edit_box { key = "eb_plansa";  label = "Plansa nr.:";   edit_width = 32; mnemonic = "P"; }
        : spacer { height = 0.5; }
        : paragraph {
          : text_part { label = "Scara, formatul, data si autorul se completeaza"; }
          : text_part { label = "automat. Textele se pot modifica ulterior cu EATTEDIT."; }
        }
      }
      : spacer { height = 0.5; }
      : paragraph {
        : text_part { label = "Dupa OK indicati coltul stanga-jos al formatului"; }
        : text_part { label = "in Model Space."; }
      }
    }
  }
  ok_cancel;
  errtile;
}
