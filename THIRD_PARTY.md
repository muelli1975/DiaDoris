# Dependencies and reused components

DiaDoris is MIT licensed. Third-party components retain their respective licences.

- Python, PSF licence.
- PySide6 / Qt for Python / Shiboken, LGPLv3/GPL/commercial licensing as supplied
  by upstream. The portable package keeps Qt libraries separate and includes
  upstream licence files. See https://doc.qt.io/qtforpython-6/licenses.html .
- Pillow, HPND; NumPy, BSD; pillow-heif, BSD-3-Clause, with its upstream libheif
  dependencies. Wheel licence files are copied into `licenses/` during packaging.
- FFmpeg and its linked libraries: the pinned build's own licence/readme files
  are included under `tools/ffmpeg`. GPL-enabled codecs retain their GPL licences.
- TransCora core and anaglyph catalogue, Christoph Müller, MIT, revision
  `a6fdd8683883549a80b984a937715b0e88f272d5`. The core files are retained unmodified
  under `transcora/`; the corresponding licence and third-party notices are in
  `reference/`. The build-time FFmpeg/FRIM/tsMuxeR download scripts and manifests
  come from the same revision.
- The anaglyph preview and colour-transfer functions are copied without changes
  from StereoFine. Its licence and dependency notices are under `reference/`.
- FRIM 1.31 and tsMuxeR 2.6.12 retain their upstream terms and documentation.
  The pinned manifests, original FRIM readmes and tsMuxeR notes are included
  beside the tools. See `reference/TransCora_THIRD_PARTY.md`.

No components are downloaded by the desktop application. The download scripts
are used only when creating packages.
