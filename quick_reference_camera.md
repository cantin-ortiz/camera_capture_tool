


## Electrophysiology Recording — Quick Reference
**Before starting a recording, check controller is connected to:**

- **Power supply** · **PC** (USB) · **Ground** · **Head-stages** via SPI cable → acquisition port

| # | Action |
|---|--------|
| 1 | Double-click GUI (OpenEphys / Intan) |
| 2 | Set **sampling rate = 20 kS/s**, hardware band-pass **0.1 – 7500 Hz** |
| 3 | If head-stage connected to implanted electrodes: check & **save impedances** (@1 kHz, <90°) |
| 4 | Select filename, path, file format (**Binary** = OpenEphys · **Traditional** = Intan) |
| 5 | Record |
| 6 | When done: turn off, return head-stage to its drawer/box |

**Target impedances (@1 kHz):**

| Type | Range |
|---|---|
| ECoG / EMG | 4–10 kΩ |
| Tetrode LFP | 200–300 kΩ |
| Stim. electrode | 120–200 kΩ |

> **Nyquist:** never set band-pass high-cut above sampling rate / 2 (10 kHz here) — stay well below to avoid aliasing. 10 kS/s minimum needed to resolve 1 ms action potentials. Re-adjust band-pass if sampling rate changes.

---

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

*See SOPs for detailed instructions.*