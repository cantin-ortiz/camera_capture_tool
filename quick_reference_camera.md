## Camera Recording — Quick Reference
**Before starting a recording, check:**

- **USB 3.0** connected · **GPIO** cable connected
- **config.py**: correct parameters especially framerate.
- GPIO → **INTAN:** Digital Input 01 · **Open Ephys:** IO Board Port 01
- Always run a **synchronisation test** (see full SOP §4.0 & §7).

| # | Action |
|---|--------|
| 1 | Double-click **`start_recording.bat`** — wait for live preview |
| 2 | Start **ephys** recording |
| 3 | Press **ENTER** in console → video acquisition starts |
| 4 | Press **ENTER** again (or wait for `--duration`) → video stops |
| 5 | Stop **ephys** recording |
| 6 | Save **both** output files: the video and the .csv

> **Order is critical:** ephys must start *before* video, and stop *after* video.