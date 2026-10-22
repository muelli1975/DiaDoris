# DiaDoris

DiaDoris is a local stereoscopic slide-show editor for photos, editable titles,
graphics, short or long video inserts, music and spoken commentary. It uses four
vertical track groups rather than a conventional horizontal timeline.

**0.1 is the first test version.** Windows packages are produced as
[GitHub Actions artifacts](https://github.com/muelli1975/DiaDoris/actions/workflows/test-build.yml).
There is no automatic release publication.

[Deutsch](README_DE.md)

## Start

Extract the complete portable folder and run `DiaDoris.exe`. FFmpeg and the
Windows Blu-ray 3D tools are included. Processing is local; the application
does not download components or require an account.

Open `examples/Example.dido` for an editable demonstration made from original
calibration graphics and a quiet calibration tone. Add your own files to Track 1;
normal images default to 2D, while explicit `_sbs`, `-lr`, `-rl`, JPS and PNS
sources default to Full-SBS. Check **Source layout** and **Swap L/R** in Properties.

Track 1 determines the show duration. Photo transitions are centered on nominal
image boundaries: three eight-second images remain 24 seconds, including
transitions. Titles and the two audio tracks have stable image anchors, offsets
and independent fades. Clips extending beyond the final main image are truncated.

Videos on Track 1 have source trims, unchanged playback speed and adjustable
original audio. Video boundaries use cuts in this test version; video/audio fades
can be placed inside the selected range. No artificial file-size or clip-length
limit is imposed. Sources must be ordinary SDR video: 2D or packed SBS/OU.
HDR conversion and MVC/MV-HEVC video input are outside this initial importer.

## Titles, audio and output

- Text and graphics remain editable, including position, scale and stereo depth.
  A title can use transparency, a solid colour, one of twelve gradients or an image
  background. PNG transparency is retained through composition.
- Safe area, grids (3/4/6/9/12), mouse alignment and exact pixel keyboard steps
  support title layout. F1 explains the applicable shortcuts.
- Clip gains are in dB. Selected Audio 2 clips can lower Audio 1. The meter shows
  stereo sample peaks on a real -60 to 0 dBFS scale; click to clear held peaks.
- Export presets cover Full/Half SBS/OU, anaglyphs and Windows Blu-ray 3D.
  Video bitrates are shown in Mbit/s. The default is Full-SBS with 1920 × 1080
  pixels per eye, H.264 MP4 at 20 Mbit/s, AAC-LC stereo at 48 kHz/320 kbit/s.
- All 17 TransCora matrix/pipeline anaglyph methods are reused. CIELAB is not an
  export option. Blu-ray ISO/M2TS uses the inherited TransCora MVC path.
- `.dido` projects reference source media. ZIP backup includes referenced media,
  uses content hashes to avoid collisions, and does not modify the working project.

Preview is reduced in resolution. Final rendering uses source media and the same
composition/timing model; video is encoded lossily only at the final output stage.
Blu-ray preparation uses a temporary lossless intermediate and needs additional
disk space. Preview preparation uses temporary uncompressed audio files.

## Test-version boundaries

This first version needs practical testing with real projects and event players.
There is no zoom animation. Fonts must be installed on the machine opening a
project; optional font embedding is not implemented. Automatic source-layout
detection is conservative. Frame rate conversion repeats/drops whole stereo
frames; it does not synthesize motion. No real-time performance guarantee is made.

## Development

Python 3.12, `pip install -r requirements.txt`, FFmpeg/ffprobe, then
`python run_diadoris.py`. On Windows, place FFmpeg under `tools/ffmpeg/bin`.
Run `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v` for the
portable model, rendering, audio, video and export tests.

The pinned download scripts are build-time tools only. The Windows workflow also
tests actual Blu-ray ISO/M2TS output before packaging. Portable packages include
their matching source under `source/`.

Copyright Christoph Müller. MIT project licence; bundled dependencies retain
their own licences. See [THIRD_PARTY.md](THIRD_PARTY.md).
