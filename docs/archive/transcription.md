State: Legacy (archived).
# 5.0 Transkribering (YouTube/ljud)

## Pipeline
1) `yt-dlp` -> extrahera ljud
2) `ffmpeg` -> WAV mono 16kHz
3) `faster-whisper` (device:auto) -> text + `segments[{start,end,text}]`
4) Emit till index-outbox med `kind=transcript`

## CLI
```bash
python -m app.cli transcribe <YOUTUBE|AUDIOFILE>
```

Artefakter
- JSON (text+segments+language)
- SRT/VTT (tidslänkning)
