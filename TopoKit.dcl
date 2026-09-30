// ===========================================================================
//  TopoKit.dcl  -  Interfata grafica (DCL) pentru suita TopoKit (AutoLISP)
//  Instrumente pentru topografie si cadastru:
//    1. Corectie topologica (vertex-uri la intersectii de polilinii)
//    2. Export parcela inchisa in KMZ/KML (Stereo 70 -> WGS84)
//    3. Inserare format, cadru si indicator la scara (A4 - A0)
//
//  Fisierul este optional: daca nu este gasit in caile de suport AutoCAD,
//  TopoKit.lsp genereaza automat o copie identica intr-un fisier temporar.
// ===========================================================================

// ---------------------------------------------------------------------------
//  Dialogul principal (comenzile TOPOKIT / MYTOPO)
// ---------------------------------------------------------------------------
topokit_main : dialog {
  label = "TopoKit - Instrumente Topografie & Cadastru";
  : text { label = "Alegeti modulul dorit. Setarile sunt memorate pe durata sesiunii AutoCAD."; }
  : row {
    // ---------------- 1. Corectie topologica ----------------
    : boxed_column {
      label = "1. Corectie Topologica";
      width = 36;
      : text_part { label = "Insereaza vertex-uri in toate punctele"; }
      : text_part { label = "de intersectie dintre poliliniile"; }
      : text_part { label = "selectate (LWPOLYLINE / POLYLINE)."; }
      spacer;
      : toggle { key = "tg_contact"; label = "Include punctele de contact (T / suprapuneri)"; }
      : edit_box { key = "eb_tol"; label = "Toleranta (unitati desen):"; edit_width = 10; }
      spacer_1;
      : button { key = "bt_addvtx"; label = "Corectie Topologica"; height = 2; fixed_height = true; }
    }
    // ---------------- 2. Export KMZ ----------------
    : boxed_column {
      label = "2. Export KMZ (Stereo 70 -> WGS84)";
      width = 36;
      : edit_box { key = "eb_nume"; label = "Nume parcela:"; edit_width = 18; }
      : radio_row {
        key = "rr_kmz";
        : radio_button { key = "rb_kmz"; label = "KMZ"; }
        : radio_button { key = "rb_kml"; label = "KML"; }
      }
      : toggle { key = "tg_puncte"; label = "Exporta si punctele de contur"; }
      : toggle { key = "tg_swap"; label = "Axe inversate (X desen = Nord)"; }
      : toggle { key = "tg_ge"; label = "Deschide in Google Earth Pro"; }
      spacer_1;
      : button { key = "bt_kmz"; label = "Export KMZ"; height = 2; fixed_height = true; }
    }
    // ---------------- 3. Format & cadru ----------------
    : boxed_column {
      label = "3. Inserare Format & Cadru";
      width = 36;
      : popup_list { key = "pl_format"; label = "Format:"; edit_width = 12; }
      : radio_row {
        key = "rr_orient";
        : radio_button { key = "rb_port"; label = "Portrait"; }
        : radio_button { key = "rb_land"; label = "Landscape"; }
      }
      : popup_list { key = "pl_scara"; label = "Scara:"; edit_width = 12; }
      : toggle { key = "tg_caroiaj"; label = "Caroiaj de coordonate (10 cm)"; }
      : text { key = "tx_dim"; label = ""; width = 34; }
      spacer_1;
      : button { key = "bt_cadru"; label = "Inserare Format & Cadru"; height = 2; fixed_height = true; }
    }
  }
  spacer;
  : row {
    alignment = centered;
    fixed_width = true;
    : button { key = "bt_despre"; label = "Despre..."; width = 14; fixed_width = true; }
    : button { key = "cancel"; label = "Inchide"; width = 14; fixed_width = true; is_cancel = true; }
  }
  errtile;
}

// ---------------------------------------------------------------------------
//  Sub-dialog dedicat comenzii INSCADRU (format, scara, indicator)
// ---------------------------------------------------------------------------
topokit_cadru : dialog {
  label = "TopoKit - Inserare Format, Cadru & Indicator";
  : row {
    : boxed_column {
      label = "Format si scara";
      : popup_list { key = "pl_format"; label = "Format pagina:"; edit_width = 12; }
      : boxed_radio_row {
        key = "rr_orient";
        label = "Orientare";
        : radio_button { key = "rb_port"; label = "Portrait"; }
        : radio_button { key = "rb_land"; label = "Landscape"; }
      }
      : popup_list { key = "pl_scara"; label = "Scara desenului:"; edit_width = 12; }
      : toggle { key = "tg_caroiaj"; label = "Caroiaj de coordonate (10 cm)"; }
      : text { key = "tx_dim"; label = ""; width = 38; }
    }
    : boxed_column {
      label = "Indicator (cartus)";
      : edit_box { key = "eb_benef";   label = "Beneficiar:";   edit_width = 30; }
      : edit_box { key = "eb_lucrare"; label = "Lucrarea:";     edit_width = 30; }
      : edit_box { key = "eb_titlu";   label = "Titlu plansa:"; edit_width = 30; }
      : edit_box { key = "eb_exec";    label = "Executant:";    edit_width = 30; }
      : edit_box { key = "eb_plansa";  label = "Plansa nr.:";   edit_width = 30; }
    }
  }
  : text { label = "Dupa OK indicati coltul stanga-jos al formatului in Model Space."; }
  ok_cancel;
  errtile;
}
