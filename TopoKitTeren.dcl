// ===========================================================================
//  TopoKitTeren.dcl - meniul modulului de teren TopoKit (comanda TOPOTEREN)
//  Fisierul este optional: daca lipseste, TopoKitTeren.lsp genereaza automat
//  o copie identica intr-un fisier temporar.
// ===========================================================================

tkt_btn : button { width = 30; fixed_width = true; }
tkt_num : edit_box { edit_width = 8; }

tkt_main : dialog {
  label = "TopoKit - Teren: puncte, model 3D, curbe de nivel, volume, raster";
  : row {
    : column {
      : boxed_column {
        label = "Puncte masurate si plan";
        : popup_list { key = "pl_cols"; label = "Coloanele fisierului:"; edit_width = 30; }
        : toggle { key = "tg_3d"; label = "Puncte 3D (la cota Z)"; }
        : toggle { key = "tg_coduri"; label = "Uneste punctele consecutive cu acelasi cod"; }
        : popup_list { key = "pl_scara"; label = "Scara planului (texte):"; edit_width = 10; }
        : tkt_btn { key = "bt_imp"; label = "Import puncte (TXT/CSV)..."; }
        : tkt_btn { key = "bt_tab"; label = "Tabel de coordonate"; }
        : tkt_btn { key = "bt_leg"; label = "Legenda semnelor conventionale"; }
      }
      : boxed_column {
        label = "Raster, Google Earth si harti online";
        : tkt_btn { key = "bt_geo"; label = "Raster georeferentiat..."; }
        : tkt_btn { key = "bt_kml"; label = "Import KML / KMZ..."; }
        : tkt_btn { key = "bt_harta"; label = "Punct pe harta online"; }
      }
    }
    : column {
      : boxed_column {
        label = "Model 3D (TIN) si curbe de nivel";
        : tkt_num { key = "eb_lmax"; label = "Latura maxima a triunghiurilor (m, 0 = fara):"; }
        : tkt_btn { key = "bt_tin"; label = "Model TIN din puncte si linii"; }
        : tkt_num { key = "eb_echid"; label = "Echidistanta curbelor (m):"; }
        : tkt_num { key = "eb_princ"; label = "Curba principala la fiecare (curbe):"; }
        : tkt_btn { key = "bt_curbe"; label = "Curbe de nivel din TIN"; }
      }
      : boxed_column {
        label = "Volume de sapatura si umplutura";
        : tkt_num { key = "eb_cota"; label = "Cota planului de referinta (m):"; }
        : tkt_btn { key = "bt_vol"; label = "Volume TIN - plan"; }
        : tkt_num { key = "eb_cel"; label = "Pasul grilei pentru doua TIN (m):"; }
        : tkt_btn { key = "bt_vol2"; label = "Volume intre doua TIN"; }
      }
    }
  }
  : text { label = "Comenzi directe: IMPPCT, TABPCT, LEGENDA, TIN, CURBE, VOLUM, VOLUM2, GEOREF, IMPKML, HARTA"; }
  : row {
    fixed_width = true;
    alignment = centered;
    : button { key = "cancel"; label = "Inchide"; is_cancel = true; width = 16; }
  }
  errtile;
}
