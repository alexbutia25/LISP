// ===========================================================================
//  TopoKitAnexe.dcl - dialogurile generatorului de anexe (Ordinul ANCPI 600/2023)
//  Fisierul este optional: daca lipseste, TopoKitAnexe.lsp genereaza automat
//  o copie identica intr-un fisier temporar.
// ===========================================================================

tka_ed : edit_box { edit_width = 26; edit_limit = 250; }
tka_btn : button { width = 30; fixed_width = true; }

// ---------------------------------------------------------------------------
//  Meniul generatorului de anexe (comanda ANEXE)
// ---------------------------------------------------------------------------
tka_main : dialog {
  label = "TopoKit - Generator anexe (Ordinul ANCPI nr. 600/2023)";
  : row {
    : boxed_column {
      label = "Anexe (selectie multipla: Ctrl / Shift + clic)";
      : list_box { key = "lb_anexe"; multiple_select = true; width = 78; height = 26; tabs = "7 12"; }
      : row {
        : button { key = "bt_toate"; label = "Toate anexele Word"; }
        : button { key = "bt_nimic"; label = "Deselecteaza"; }
      }
    }
    : column {
      : boxed_column {
        label = "Pachete (documentatie completa)";
        : tka_btn { key = "pk_prima";  label = "Prima inregistrare"; }
        : tka_btn { key = "pk_constr"; label = "Inscriere constructie"; }
        : tka_btn { key = "pk_dez";    label = "Dezlipire teren"; }
        : tka_btn { key = "pk_alip";   label = "Alipire teren"; }
        : tka_btn { key = "pk_ui";     label = "Prima inregistrare UI / apartamentare"; }
      }
      : boxed_column {
        label = "Datele lucrarii";
        : tka_btn { key = "bt_imobil";  label = "Imobil si proprietari..."; }
        : tka_btn { key = "bt_lucrare"; label = "Lucrare si memoriu tehnic..."; }
        : tka_btn { key = "bt_exec";    label = "Executant (persoana autorizata)..."; }
        : tka_btn { key = "bt_opt";     label = "Optiuni planuri (format, scara)..."; }
        : tka_btn { key = "bt_verif";   label = "Verificare date si geometrie..."; }
      }
      : boxed_column {
        label = "Rezultat";
        : toggle { key = "tg_pdfplan"; label = "Ploteaza planurile in PDF"; }
        : toggle { key = "tg_pdf";  label = "Converteste anexele Word in PDF"; }
        : toggle { key = "tg_open"; label = "Deschide folderul cu anexele"; }
      }
    }
  }
  : boxed_column {
    label = "Stare";
    : text { key = "tx_info";  label = ""; width = 120; }
    : text { key = "tx_stare"; label = ""; width = 120; }
  }
  : row {
    fixed_width = true;
    alignment = centered;
    : button { key = "accept"; label = "Genereaza"; is_default = true; width = 18; }
    : button { key = "cancel"; label = "Inchide"; is_cancel = true; width = 18; }
  }
  errtile;
}

// ---------------------------------------------------------------------------
//  Datele imobilului si ale proprietarilor (salvate in desen)
// ---------------------------------------------------------------------------
tka_imobil : dialog {
  label = "TopoKit - Date imobil si proprietari";
  : row {
    : boxed_column {
      label = "Imobil";
      : tka_ed { key = "NRCAD";      label = "Numar cadastral:"; }
      : tka_ed { key = "NRCF";       label = "Nr. carte funciara:"; }
      : tka_ed { key = "UAT";        label = "UAT:"; }
      : tka_ed { key = "LOCALITATE"; label = "Localitate:"; }
      : tka_ed { key = "JUDET";      label = "Judet:"; }
      : tka_ed { key = "STRADA";     label = "Strada:"; }
      : row {
        : edit_box { key = "NR";    label = "Nr.:";  edit_width = 5; }
        : edit_box { key = "BLOC";  label = "Bl.:";  edit_width = 4; }
        : edit_box { key = "SCARA"; label = "Sc.:";  edit_width = 3; }
      }
      : row {
        : edit_box { key = "ETAJ";  label = "Et.:";  edit_width = 3; }
        : edit_box { key = "AP";    label = "Ap.:";  edit_width = 4; }
      }
      : tka_ed { key = "TARLA";    label = "Tarla:"; }
      : tka_ed { key = "PARCELA";  label = "Parcela:"; }
      : tka_ed { key = "NRTOP";    label = "Nr. topografic:"; }
      : tka_ed { key = "DENUMIRE_LOC"; label = "Denumirea locului:"; }
      : popup_list { key = "CATEG"; label = "Categoria de folosinta:"; edit_width = 24; }
      : tka_ed { key = "SACT";     label = "Suprafata din act (mp):"; }
      : tka_ed { key = "ACT_PROP"; label = "Act de proprietate:"; }
      : tka_ed { key = "MENT_TEREN"; label = "Mentiuni teren (PAD):"; }
      : tka_ed { key = "OCPI";     label = "OCPI (judet):"; }
      : tka_ed { key = "BCPI";     label = "BCPI:"; }
    }
    : boxed_column {
      label = "Proprietar 1 (solicitant)";
      : tka_ed { key = "P1_NUME";     label = "Nume:"; }
      : tka_ed { key = "P1_PRENUME";  label = "Prenume:"; }
      : tka_ed { key = "P1_CNP";      label = "CNP/CUI:"; }
      : row {
        : edit_box { key = "P1_CI_SERIA"; label = "CI seria:"; edit_width = 4; }
        : edit_box { key = "P1_CI_NR";    label = "nr.:"; edit_width = 9; }
      }
      : tka_ed { key = "P1_CI_EMITENT"; label = "CI eliberata de:"; }
      : tka_ed { key = "P1_LOC";      label = "Domiciliu - localitate:"; }
      : tka_ed { key = "P1_STR";      label = "Strada:"; }
      : row {
        : edit_box { key = "P1_NR"; label = "Nr.:"; edit_width = 4; }
        : edit_box { key = "P1_BL"; label = "Bl.:"; edit_width = 4; }
        : edit_box { key = "P1_SC"; label = "Sc.:"; edit_width = 3; }
      }
      : row {
        : edit_box { key = "P1_ET"; label = "Et.:"; edit_width = 3; }
        : edit_box { key = "P1_AP"; label = "Ap.:"; edit_width = 4; }
      }
      : tka_ed { key = "P1_JUD";      label = "Judet/sector:"; }
      : tka_ed { key = "P1_CODP";     label = "Cod postal:"; }
      : tka_ed { key = "P1_TEL";      label = "Telefon:"; }
      : tka_ed { key = "P1_EMAIL";    label = "E-mail:"; }
      : tka_ed { key = "P1_CALITATE"; label = "Calitatea:"; }
    }
    : boxed_column {
      label = "Proprietar 2 (optional)";
      : tka_ed { key = "P2_NUME";     label = "Nume:"; }
      : tka_ed { key = "P2_PRENUME";  label = "Prenume:"; }
      : tka_ed { key = "P2_CNP";      label = "CNP:"; }
      : row {
        : edit_box { key = "P2_CI_SERIA"; label = "CI seria:"; edit_width = 4; }
        : edit_box { key = "P2_CI_NR";    label = "nr.:"; edit_width = 9; }
      }
      : tka_ed { key = "P2_LOC";      label = "Domiciliu - localitate:"; }
      : tka_ed { key = "P2_CALITATE"; label = "Calitatea:"; }
      spacer_1;
      : text { label = "Datele se salveaza in desen si"; }
      : text { label = "completeaza automat cererile,"; }
      : text { label = "declaratiile, PV de vecinatate,"; }
      : text { label = "memoriul tehnic si planurile."; }
    }
  }
  ok_cancel;
  errtile;
}

// ---------------------------------------------------------------------------
//  Datele lucrarii si textele memoriului tehnic
// ---------------------------------------------------------------------------
tka_lucrare : dialog {
  label = "TopoKit - Date lucrare si memoriu tehnic";
  : row {
    : boxed_column {
      label = "Lucrare";
      : popup_list { key = "TIP"; label = "Tipul lucrarii:"; edit_width = 46; }
      : popup_list { key = "COMUNICARE"; label = "Comunicarea raspunsului:"; edit_width = 46; }
      : tka_ed { key = "INTAB_OBIECT"; label = "Intabularea (obiect):"; edit_width = 46; }
      : tka_ed { key = "E_CONTRACT"; label = "Contract/angajament nr.:"; }
      : tka_ed { key = "E_CONTRACT_DATA"; label = "din data:"; }
      : tka_ed { key = "DATA_MAS"; label = "Data masuratorilor:"; }
      : row {
        : edit_box { key = "PV_EXEMPLARE"; label = "PV vecinatate - exemplare:"; edit_width = 4; }
        : edit_box { key = "PV_PAGINI"; label = "pagini:"; edit_width = 4; }
      }
      : tka_ed { key = "NRCF_COLECTIVA"; label = "CF colectiva (UI):"; }
      : tka_ed { key = "ST_AFERENT"; label = "Teren aferent cladirii (mp):"; }
      : tka_ed { key = "PARTI_COMUNE"; label = "Parti comune (UI):"; edit_width = 46; }
    }
    : column {
      : boxed_column {
        label = "Declaratia proprietarului (anexa 14)";
        : toggle { key = "POZ_INCERTA"; label = "Pozitionare incerta a imobilului"; }
        : toggle { key = "LITIGIU"; label = "Imobilul se afla in litigiu:"; }
        : row {
          : edit_box { key = "LIT_ID"; label = "ID imobil:"; edit_width = 10; }
          : edit_box { key = "LIT_DOSAR"; label = "Nr. dosar:"; edit_width = 14; }
        }
        : row {
          : edit_box { key = "LIT_INSTANTA"; label = "Instanta:"; edit_width = 18; }
          : edit_box { key = "LIT_OBIECT"; label = "Obiect:"; edit_width = 16; }
        }
      }
      : boxed_column {
        label = "Memoriu tehnic (gol = text generat automat)";
        : edit_box { key = "METODA";      label = "Metoda:";     edit_width = 60; edit_limit = 400; }
        : edit_box { key = "APARATURA";   label = "Aparatura:";  edit_width = 60; edit_limit = 400; }
        : edit_box { key = "SPRIJIN";     label = "Puncte de sprijin:"; edit_width = 60; edit_limit = 400; }
        : edit_box { key = "SCOP";        label = "4. Scop:";    edit_width = 60; edit_limit = 2000; }
        : edit_box { key = "DOCUMENTARE"; label = "5. Documentare:"; edit_width = 60; edit_limit = 2000; }
        : edit_box { key = "OPERATIUNI";  label = "6. Operatiuni:";  edit_width = 60; edit_limit = 2000; }
        spacer_1;
        : text { label = "Textele lungi se pot ajusta si in documentul Word generat."; }
      }
    }
  }
  ok_cancel;
  errtile;
}

// ---------------------------------------------------------------------------
//  Datele persoanei autorizate (salvate pe calculator)
// ---------------------------------------------------------------------------
tka_exec : dialog {
  label = "TopoKit - Executant (persoana autorizata)";
  : row {
    : boxed_column {
      label = "Identificare";
      : tka_ed { key = "E_TITLU";   label = "Titlu (ing., dr. ing.):"; }
      : tka_ed { key = "E_NUME";    label = "Nume:"; }
      : tka_ed { key = "E_PRENUME"; label = "Prenume:"; }
      : tka_ed { key = "E_CNP";     label = "CNP/CUI:"; }
      : tka_ed { key = "E_FIRMA";   label = "Firma (PFA/PJA):"; }
      : row {
        : edit_box { key = "E_CI_SERIA"; label = "CI seria:"; edit_width = 4; }
        : edit_box { key = "E_CI_NR";    label = "nr.:"; edit_width = 9; }
      }
      : tka_ed { key = "E_TEL";     label = "Telefon:"; }
      : tka_ed { key = "E_EMAIL";   label = "E-mail:"; }
    }
    : boxed_column {
      label = "Autorizatie si adresa";
      : tka_ed { key = "E_CAT";         label = "Categoria/clasa:"; }
      : tka_ed { key = "E_AUT_SERIA";   label = "Seria (ex. RO-BV-F):"; }
      : tka_ed { key = "E_AUT_NR";      label = "Numar:"; }
      : tka_ed { key = "E_AUT_EMITENT"; label = "Emisa de:"; }
      : tka_ed { key = "E_AUT_DATA";    label = "Data emiterii:"; }
      : tka_ed { key = "E_LOC";         label = "Localitate:"; }
      : tka_ed { key = "E_STR";         label = "Strada:"; }
      : tka_ed { key = "E_NR";          label = "Nr.:"; }
      : tka_ed { key = "E_JUD";         label = "Judet:"; }
    }
  }
  ok_cancel;
  errtile;
}

// ---------------------------------------------------------------------------
//  Optiunile planurilor (format, scara, numerotare)
// ---------------------------------------------------------------------------
tka_opt : dialog {
  label = "TopoKit - Optiuni planuri";
  : boxed_column {
    label = "Pagina";
    : popup_list { key = "pl_format"; label = "Format:"; edit_width = 26; }
    : popup_list { key = "pl_scara";  label = "Scara:";  edit_width = 26; }
  }
  : boxed_column {
    label = "Numerotare si cote";
    : edit_box { key = "eb_start"; label = "Primul numar de punct:"; edit_width = 6; }
    : radio_column {
      key = "rc_mod";
      : radio_button { key = "rb_nv";  label = "Sens orar, din punctul cel mai de nord-vest"; }
      : radio_button { key = "rb_pol"; label = "Ordinea vertex-urilor poliliniei"; }
      : radio_button { key = "rb_des"; label = "Numerele punctelor din desen (texte / blocuri de punct)"; }
    }
    : edit_box { key = "eb_nrdist"; label = "Distanta maxima numar - varf (m):"; edit_width = 6; }
    : radio_row {
      key = "rr_sep";
      : radio_button { key = "rb_virg"; label = "Zecimale cu virgula (12,34)"; }
      : radio_button { key = "rb_punct"; label = "cu punct (12.34)"; }
    }
    : toggle { key = "tg_inv"; label = "Inventar de coordonate pe plan"; }
  }
  : boxed_column {
    label = "Etichete";
    : edit_box { key = "eb_a16"; label = "Eticheta anexei 16:"; edit_width = 20; }
    : edit_box { key = "eb_a17"; label = "Eticheta anexei 17:"; edit_width = 20; }
  }
  ok_cancel;
  errtile;
}

// ---------------------------------------------------------------------------
//  Laturile imobilului: vecini, identificatori, materializare
// ---------------------------------------------------------------------------
tka_laturi : dialog {
  label = "TopoKit - Laturi si vecinatati";
  : list_box { key = "lb_lat"; multiple_select = true; width = 110; height = 16; tabs = "8 18 48 80"; }
  : text { label = "Selectati una sau mai multe laturi, completati campurile si apasati Aplica."; }
  : boxed_column {
    label = "Date latura";
    : edit_box { key = "eb_id";    label = "Identificator vecin (pe plan):"; edit_width = 50; edit_limit = 120; }
    : edit_box { key = "eb_vecin"; label = "Vecin (nume si prenume / denumire):"; edit_width = 50; edit_limit = 120; }
    : row {
      : popup_list { key = "pl_mat"; label = "Materializare:"; edit_width = 22; }
      : edit_box { key = "eb_mat"; edit_width = 26; edit_limit = 120; }
    }
    : edit_box { key = "eb_obs";   label = "Observatii:"; edit_width = 50; edit_limit = 120; }
    : row {
      : button { key = "bt_aplica"; label = "Aplica la laturile selectate"; }
      : button { key = "bt_auto";   label = "Detecteaza din desen"; }
      : button { key = "bt_sterge"; label = "Sterge datele selectiei"; }
    }
  }
  ok_cancel;
  errtile;
}

// ---------------------------------------------------------------------------
//  Datele unei constructii
// ---------------------------------------------------------------------------
tka_constr : dialog {
  label = "TopoKit - Date constructie";
  : text { key = "tx_info"; label = ""; width = 60; }
  : boxed_column {
    label = "Constructie";
    : edit_box { key = "COD";      label = "Cod (C1, C2...):"; edit_width = 8; }
    : popup_list { key = "DEST";   label = "Destinatia:"; edit_width = 40; }
    : edit_box { key = "DENUMIRE"; label = "Denumire (ex. Casa de locuit):"; edit_width = 40; edit_limit = 120; }
    : edit_box { key = "REGIM";    label = "Regim de inaltime (ex. P+1E):"; edit_width = 12; }
    : edit_box { key = "AN";       label = "Anul construirii:"; edit_width = 8; }
    : edit_box { key = "SD";       label = "Suprafata desfasurata (mp):"; edit_width = 10; }
    : edit_box { key = "NRUI";     label = "Numar unitati individuale:"; edit_width = 6; }
    : edit_box { key = "MENT";     label = "Alte mentiuni:"; edit_width = 40; edit_limit = 250; }
  }
  ok_cancel;
  errtile;
}

// ---------------------------------------------------------------------------
//  Raportul verificarii (date lucrare, geometrie, loturi)
// ---------------------------------------------------------------------------
tka_raport : dialog {
  label = "TopoKit - Verificarea datelor si a geometriei";
  : text { key = "tx_titlu"; label = ""; width = 100; }
  : list_box { key = "lb_rap"; width = 112; height = 14; }
  : text { label = "E = eroare (planul ar fi gresit)   A = atentionare   I = informatie"; }
  : row {
    fixed_width = true;
    alignment = centered;
    : button { key = "accept"; label = "Continua"; is_default = true; width = 16; }
    : button { key = "cancel"; label = "Renunta"; is_cancel = true; width = 16; }
  }
}
