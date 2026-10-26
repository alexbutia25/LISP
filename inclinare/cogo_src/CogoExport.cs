// Modul mic pentru AutoCAD/Civil 3D: scrie punctele COGO (si punctele AutoCAD) intr-un fisier text.
// Comanda: PLANINCL_EXPORTPUNCTE <cale_fisier>
using System;
using System.Globalization;
using System.IO;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(PlanInclinare.Cmds))]

namespace PlanInclinare
{
    public class Cmds
    {
        static string F(double v) { return v.ToString("R", CultureInfo.InvariantCulture); }
        static string Clean(string s) { return (s ?? "").Replace(";", ",").Replace("\r", " ").Replace("\n", " "); }

        [CommandMethod("PLANINCL_EXPORTPUNCTE")]
        public static void Export()
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            var ed = doc.Editor;
            var pso = new PromptStringOptions("\nFisier iesire: ");
            pso.AllowSpaces = true;
            var pr = ed.GetString(pso);
            if (pr.Status != PromptStatus.OK) return;
            var db = doc.Database;
            var sb = new StringBuilder();
            int nCogo = 0, nPt = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    string dxf = id.ObjectClass.DxfName;
                    if (dxf == "AECC_COGO_POINT")
                    {
                        try
                        {
                            var p = (Autodesk.Civil.DatabaseServices.CogoPoint)tr.GetObject(id, OpenMode.ForRead);
                            sb.AppendLine(p.PointNumber + ";" + F(p.Easting) + ";" + F(p.Northing) + ";" + F(p.Elevation) + ";" + Clean(p.RawDescription));
                            nCogo++;
                        }
                        catch { }
                    }
                    else if (dxf == "POINT")
                    {
                        var p = (DBPoint)tr.GetObject(id, OpenMode.ForRead);
                        nPt++;
                        sb.AppendLine("P" + nPt + ";" + F(p.Position.X) + ";" + F(p.Position.Y) + ";" + F(p.Position.Z) + ";" + Clean(p.Layer));
                    }
                }
                tr.Commit();
            }
            File.WriteAllText(pr.StringResult, sb.ToString(), new UTF8Encoding(false));
            ed.WriteMessage("\nPLANINCL: " + nCogo + " puncte COGO, " + nPt + " puncte AutoCAD exportate.\n");
        }
    }
}
