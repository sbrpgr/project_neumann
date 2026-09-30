# PowerPoint COM: re-save pptx with fonts embedded, save PDF, export slide PNGs.
# usage: finalize.py <stage1.pptx> <final.pptx> <final.pdf> <png_dir> [width]
import os, sys, time
import pythoncom, win32com.client
src, dst, pdf, pngdir = [os.path.abspath(a) for a in sys.argv[1:5]]
w = int(sys.argv[5]) if len(sys.argv) > 5 else 1920
pythoncom.CoInitialize()
app = win32com.client.DispatchEx("PowerPoint.Application")
try:
    app.DisplayAlerts = 1  # ppAlertsNone
except Exception as e:
    print("DisplayAlerts", e)
t = time.time()
pres = app.Presentations.Open(src, False, False, False)
try:
    pres.SaveAs(dst, 24, -1)   # ppSaveAsOpenXMLPresentation, EmbedTrueTypeFonts=msoTrue
    pres.SaveAs(pdf, 32)       # ppSaveAsPDF
    if os.path.basename(pngdir) != "-":  # E6-pres5: "-" = PDF only, no PNG export
        os.makedirs(pngdir, exist_ok=True)
        h = int(w * pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth)
        for i in range(1, pres.Slides.Count + 1):
            pres.Slides(i).Export(os.path.join(pngdir, "slide_%02d.png" % i), "PNG", w, h)
    print("slides", pres.Slides.Count)
finally:
    pres.Close()
    app.Quit()
for f in (dst, pdf):
    print(os.path.basename(f), os.path.getsize(f))
print("elapsed %.1fs" % (time.time() - t))
