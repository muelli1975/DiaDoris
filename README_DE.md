# DiaDoris

DiaDoris erstellt stereoskopische Diaschauen aus Fotos, bearbeitbaren Titeln,
Grafiken, Videoclips, Musik und Kommentaren. Vier vertikale Spurgruppen ersetzen
eine klassische horizontale Timeline.

**0.1 ist die erste Testversion.** Das Windows-Paket entsteht als Artefakt unter
[GitHub Actions](https://github.com/muelli1975/DiaDoris/actions/workflows/test-build.yml).
Es wird kein Release automatisch veröffentlicht.

## Einstieg

Den vollständigen portablen Ordner entpacken und `DiaDoris.exe` starten.
FFmpeg und die Windows-Blu-ray-Werkzeuge sind enthalten. Das Programm arbeitet
lokal und lädt beim Start keine Komponenten nach.

`examples/Example.dido` enthält ein bearbeitbares Beispiel mit selbst erzeugten
Stereo-Testgrafiken und einem leisen Testton. Eigene Dateien kommen zunächst in
Spur 1. Normale Bilder beginnen als 2D; eindeutige `_sbs`-/`-lr`-/`-rl`-Namen sowie
JPS/PNS als Full-SBS. Ohne eindeutiges Kürzel gilt bei JPS/PNS wie in TransCora
rechts zuerst. Die etablierten TransCora-Kürzel für Full-/Half-SBS/OU werden
ebenfalls erkannt. **Quelllayout** und **L/R tauschen** in den Eigenschaften prüfen.

Die Hauptspur bestimmt die Schaudauer. Übergänge zwischen Fotos liegen mittig
auf dem rechnerischen Bildwechsel: 3 × 8 Sekunden bleiben insgesamt 24 Sekunden.
Titel und die beiden Audiospuren besitzen feste Ankerbilder, Startversätze und
eigene Blenden. Am Schauende werden weiterlaufende Elemente begrenzt.

Videoclips auf Spur 1 erhalten einen Ausschnitt, unveränderte Geschwindigkeit
und einstellbaren Originalton. An Videogrenzen wird in dieser Testversion direkt
geschnitten; Video-/Tonblenden können innerhalb des Ausschnitts liegen. Es gibt
keine künstliche Zeit- oder Dateigrößenbegrenzung. Eingabe: gewöhnliche SDR-Videos
in 2D oder SBS/OU. HDR-Umwandlung und MVC/MV-HEVC-Videoimport sind noch nicht enthalten.

## Gestaltung und Ausgabe

- Titel aus Text und Grafiken mit Position, Größe und stereoskopischer Tiefe.
  Hintergrund: transparent, einfarbig, zwölf Farbverläufe oder eigenes Bild.
- Safe Area, Raster mit 3/4/6/9/12 Unterteilungen, Mausausrichtung und pixelgenaue
  Tastaturbewegung. F1 erklärt die Befehle im jeweiligen Bereich.
- Lautstärke je Audioclip in dB. Gewählte Kommentare auf Audio 2 können Audio 1
  absenken. Die Pegelanzeige zeigt Sample-Spitzen von -60 bis 0 dBFS; ein Klick
  löscht gespeicherte Spitzen und Übersteuerungsmarkierungen.
- Exportvorgaben für Full-/Half-SBS/OU, Anaglyphen und Windows-Blu-ray-3D.
  Videobitrate in Mbit/s. Standard: Full-SBS mit 1920 × 1080 je Auge, MP4/H.264
  mit 20 Mbit/s und AAC-LC, Stereo, 48 kHz, 320 kbit/s.
- Die 17 Anaglyphenverfahren und die Blu-ray-ISO-/M2TS-Strecke stammen aus
  TransCora. CIELAB gehört nicht zur Videoausgabe.
- `.dido` speichert Verweise auf Originale. Die ZIP-Sicherung nimmt benötigte
  Medien mit; identische Dateien werden zusammengefasst, Namenskollisionen
  verhindert. Die normalen Projektverweise bleiben erhalten.

Die Vorschau verwendet eine reduzierte Auflösung. Der Export verwendet die
Originalressourcen und dasselbe Ablaufmodell. Blu-ray benötigt vorübergehend
eine verlustfrei komprimierte Zwischenfassung. Für die Tonvorschau entstehen
temporäre unkomprimierte Audiodateien.

## Grenzen der ersten Testversion

Praktische Prüfungen mit eigenen Projekten und Veranstaltungsplayern sind nötig.
Zoom bleibt ausgeschaltet und ist nicht implementiert. Schriften müssen auf dem
jeweiligen Rechner installiert sein; optionale Schriftensicherung folgt später.
Die Layouterkennung bleibt bewusst zurückhaltend. Eine Bildratenänderung lässt
ganze Stereobildpaare aus oder wiederholt sie, ohne Bewegungsinterpolation.
Eine Echtzeitgarantie für die Vorschau gibt es noch nicht.

## Aus Quellcode starten

Python 3.12, `pip install -r requirements.txt`, FFmpeg/ffprobe und anschließend
`python run_diadoris.py`. Unter Windows liegen die FFmpeg-Programme in
`tools/ffmpeg/bin`. Das portable Paket enthält seinen Quellstand unter `source/`.

Copyright Christoph Müller. Projekt: MIT. Fremdkomponenten behalten ihre eigenen
Lizenzen; siehe [THIRD_PARTY.md](THIRD_PARTY.md).
