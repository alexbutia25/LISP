// ===========================================================================
//  TopoKitInclinare.dcl - dialogul planului de inclinare TopoKit (comanda INCLINARE)
//  Fisierul este optional: daca lipseste, TopoKitInclinare.lsp genereaza automat
//  o copie identica intr-un fisier temporar.
// ===========================================================================

tki_cod : edit_box { edit_width = 14; width = 16; fixed_width = true; }
tki_lst : popup_list { width = 14; fixed_width = true; }
tki_tit : edit_box { edit_width = 22; width = 24; fixed_width = true; }
tki_dir : popup_list { width = 10; fixed_width = true; }
tki_pl : popup_list { edit_width = 12; }
tki_eb : edit_box { edit_width = 26; }

tki_main : dialog {
  label = "TopoKit - Plan de inclinare (verticalitate)";
  : text { key = "tx_pct"; label = ""; width = 96; }
  : boxed_column {
    label = "Randuri, de la stanga la dreapta (codul punctelor; mai multe coduri separate prin virgula)";
    : row {
      fixed_width = true;
      : text { label = "Cod"; width = 16; fixed_width = true; }
      : text { label = "Alege din coduri"; width = 16; fixed_width = true; }
      : text { label = "Titlu in plan"; width = 24; fixed_width = true; }
      : text { label = "Aplecare"; width = 10; fixed_width = true; }
    }
    : row { fixed_width = true; : tki_cod { key = "eb_cod1"; } : tki_lst { key = "pl_cod1"; } : tki_tit { key = "eb_tit1"; } : tki_dir { key = "pl_dir1"; } }
    : row { fixed_width = true; : tki_cod { key = "eb_cod2"; } : tki_lst { key = "pl_cod2"; } : tki_tit { key = "eb_tit2"; } : tki_dir { key = "pl_dir2"; } }
    : row { fixed_width = true; : tki_cod { key = "eb_cod3"; } : tki_lst { key = "pl_cod3"; } : tki_tit { key = "eb_tit3"; } : tki_dir { key = "pl_dir3"; } }
    : row { fixed_width = true; : tki_cod { key = "eb_cod4"; } : tki_lst { key = "pl_cod4"; } : tki_tit { key = "eb_tit4"; } : tki_dir { key = "pl_dir4"; } }
  }
  : row {
    : boxed_column {
      label = "Calcul";
      : tki_pl { key = "pl_potr"; label = "Potrivire cod:"; }
      : tki_pl { key = "pl_abat"; label = "Abatere:"; }
      : tki_pl { key = "pl_unit"; label = "Unitate:"; }
      : edit_box { key = "eb_zec"; label = "Zecimale:"; edit_width = 4; }
      : toggle { key = "tg_h"; label = "Inaltimea H la puncte"; }
      : toggle { key = "tg_z"; label = "Cota Z la puncte"; }
      : toggle { key = "tg_evita"; label = "Ascunde etichetele suprapuse"; }
      : toggle { key = "tg_leg"; label = "Legenda"; }
    }
    : boxed_column {
      label = "Plansa";
      : tki_pl { key = "pl_fmt"; label = "Format:"; }
      : tki_pl { key = "pl_ori"; label = "Orientare:"; }
      : tki_pl { key = "pl_scara"; label = "Scara:"; }
      : tki_pl { key = "pl_prio"; label = "Automat prefera:"; }
      : edit_box { key = "eb_text"; label = "Inaltime text (mm):"; edit_width = 5; }
      : edit_box { key = "eb_strat"; label = "Strat:"; edit_width = 16; }
      : toggle { key = "tg_cartus"; label = "Chenar cu cartus"; }
    }
    : boxed_column {
      label = "Cartus";
      : tki_eb { key = "eb_titlu"; label = "Titlu:"; }
      : tki_eb { key = "eb_ben"; label = "Beneficiar:"; }
      : tki_eb { key = "eb_obi"; label = "Obiectiv:"; }
      : tki_eb { key = "eb_int"; label = "Intocmit:"; }
      : edit_box { key = "eb_nr"; label = "Plansa nr.:"; edit_width = 6; }
    }
  }
  : boxed_column {
    label = "Rezultat";
    : text { key = "tx_rez"; label = ""; width = 96; }
    : text { key = "tx_plansa"; label = ""; width = 96; }
  }
  : text { label = "Verticala fiecarui rand trece prin punctul lui cel mai de jos. Desenul este 1:1 (metri); scara mareste chenarul si textele."; }
  ok_cancel;
  errtile;
}
