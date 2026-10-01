// ===========================================================================
//  TopoKit.dcl  -  Interfata grafica (DCL) pentru suita TopoKit (AutoLISP)
//  Instrumente pentru topografie si cadastru:
//    1. Corectie topologica (vertex-uri la intersectii de polilinii)
//    2. Export parcela inchisa in KMZ/KML (Stereo 70 -> ETRS89/WGS84)
//    3. Inserare format, cadru si indicator la scara (A4 - A0)
//    4. Generatorul de anexe pentru Ordinul ANCPI nr. 600/2023
//       (TopoKitAnexe.lsp: PAD, dezlipire/alipire, releveu, documente Word)
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
//  Dialogul principal (comenzile TOPOKIT / MYTOPO)
// ---------------------------------------------------------------------------
topokit_main : dialog {
  label = "TopoKit - Topografie & Cadastru";

  // ---------------- antet: sigla + titlu ----------------
  : row {
    : image { key = "img_logo"; width = 9; height = 3.6; fixed_width = true; fixed_height = true; color = -15; }
    : column {
      fixed_height = true;
      : text { label = "TopoKit  -  Instrumente pentru topografie si cadastru"; }
      : text { label = "Stereo 70  >  ETRS89 / WGS84   |   Formate A4 - A0   |   Corectie topologica"; }
    }
  }
  : image { key = "img_sep"; height = 0.35; fixed_height = true; color = -15; }

  : row {
    // ---------------- 1. Corectie topologica ----------------
    : tk_modul {
      label = " 1   Corectie Topologica ";
      : tk_icon { key = "img_topo"; }
      : paragraph {
        : text_part { label = "Adauga vertex-uri la intersectiile si"; }
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
        : text_part { label = "Conturul parcelei (polilinie inchisa)"; }
        : text_part { label = "in KMZ: Stereo 70 > ETRS89 / WGS84."; }
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
        : toggle { key = "tg_grid";   label = "Grila NTv2 ANCPI (precizie cm)"; mnemonic = "G"; }
        : toggle { key = "tg_puncte"; label = "Exporta si punctele de contur"; }
        : toggle { key = "tg_swap";   label = "Axe inversate (X desen = Nord)"; }
        : toggle { key = "tg_ge";     label = "Deschide in Google Earth Pro"; }
      }
      : spacer { height = 0.3; }
      : tk_action { key = "bt_kmz"; label = "Export KMZ"; mnemonic = "E"; }
      : text { label = "Comanda directa: EXPKMZ"; alignment = centered; }
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

  // ---------------- 4. Anexe Ordinul ANCPI 600/2023 ----------------
  : spacer { height = 0.3; }
  : boxed_row {
    label = " 4   Anexe - Ordinul ANCPI nr. 600/2023 ";
    : paragraph {
      : text_part { label = "Planuri in layout-uri: PAD (anexa 16), dezlipire / alipire (anexa 17), releveu (anexa 18)."; }
      : text_part { label = "Documente Word completate: cereri, declaratie, memoriu tehnic, PV de vecinatate, foaia colectiva."; }
      : text_part { key = "tx_anexe"; label = ""; width = 90; }
    }
    : column {
      : tk_action { key = "bt_anexe"; label = "Generator anexe..."; mnemonic = "A"; }
      : text { label = "Comanda directa: ANEXE"; alignment = centered; }
    }
  }

  : spacer { height = 0.3; }
  : boxed_row {
    label = "Stare";
    : text { key = "tx_status"; label = ""; width = 100; }
  }
  : row {
    : text { label = "Setarile sunt memorate pe durata sesiunii AutoCAD."; }
    : button { key = "bt_despre"; label = "Despre..."; mnemonic = "D"; width = 13; fixed_width = true; }
    : button { key = "cancel"; label = "Inchide"; width = 13; fixed_width = true; is_cancel = true; }
  }
  errtile;
}

// ---------------------------------------------------------------------------
//  Sub-dialog dedicat comenzii INSCADRU (format, scara, indicator)
// ---------------------------------------------------------------------------
topokit_cadru : dialog {
  label = "TopoKit - Inserare Format, Cadru & Indicator";
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
