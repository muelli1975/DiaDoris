# DiaDoris repository guidance

Preserve the agreed simple vertical four-track design, using the shared
Stereo-Tools Nachtgold palette. Track groups have ordinary subcolumns; detailed
editing belongs in Properties or the title editor. Do not add zoom animation.

Only Track 1 determines show duration. Photo transitions are centered around
nominal boundaries without shortening the sum of slide durations. Video inserts
currently use cuts at their boundaries, with fades inside the selected range.

Keep preview and export on the same composition model. Preserve image alpha
until final composition and preserve paired-eye geometry. The inherited TransCora
core is a pinned dependency; do not casually edit its established processing math.

Public default documentation is English, with German in README_DE.md. UI strings
must be available in German and English. Distinguish planned from tested features.

Tests and Windows packaging run through Actions. Never publish a GitHub release
unless the user explicitly requests it. Build artifacts are appropriate for tests.
