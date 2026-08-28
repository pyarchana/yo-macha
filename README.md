# yo-macha

Download an entire YouTube playlist at once, as **single merged files**, with the
playlist name and every video name intact.

## Setup

```bash
pip install -r requirements.txt
```

You also need ffmpeg, which is what joins the video and audio streams:

```bash
winget install Gyan.FFmpeg
```

Optional but recommended, a JavaScript runtime. yt-dlp uses it to read YouTube's
player, and without one it warns that some formats are hidden. In testing it was
the difference between being offered a 1080p stream and a better one:

```bash
winget install DenoLand.Deno
```

winget installs deno without adding it to PATH, so the script looks inside the
winget package folder as well. No PATH setup needed.

## Use

```bash
python download.py "https://www.youtube.com/playlist?list=PLxxxxxxxx"
```

That is the whole thing. Common variations:

| Goal | Command |
|---|---|
| Best available quality | `python download.py <url> -q best` |
| Save space | `python download.py <url> -q 720` |
| Music / podcasts as mp3 | `python download.py <url> --audio-only` |
| With subtitles burned in | `python download.py <url> --subs` |
| Only videos 1 to 10 | `python download.py <url> --playlist-items 1-10` |
| Several playlists | `python download.py --from-file urls.txt` |
| Your private playlist | `python download.py <url> --cookies-from-browser chrome` |

## What you get

```
downloads/
└── Python： Full Course (2024) [PLxyz999]/
    ├── 001 - Day 1： Setup & ＂Hello, World＂ [dQw4w9].mp4
    ├── 002 - Day 2, Variables ⧸ Types [xK9p2a].mp4
    ├── _index.md          readable list, original titles, clickable links
    ├── _playlist.json     same data for scripts
    └── _meta/             thumbnails and raw metadata, kept out of the way
```

The playlist folder itself lists nothing but the videos and the two manifests.
Thumbnails are already embedded in each mp4, so the loose copies and the
per-video `.info.json` dumps live in `_meta/`.

Names are protected at three levels, so nothing is lost.

1. **Filename.** The real title, plus a zero-padded index that preserves
   playlist order and the video id for traceability.
2. **Inside the file.** Title, artist, track number and chapters are written
   into the video's own metadata tags, so the name survives a rename.
3. **Manifest.** `_playlist.json` stores the *original, unsanitized* titles.
   Windows cannot store `: / ? " < > |` in a filename, so yt-dlp swaps them for
   lookalike characters (`：⧸？＂＜＞｜`). The manifest keeps the true text.

## About the split video and audio problem

YouTube serves anything above 360p as **two separate streams**, video and audio.
Downloaders that lack ffmpeg save both and leave you with a silent video plus a
stray audio file. This project avoids that:

- it locates `ffmpeg` and passes the path to yt-dlp explicitly, rather than
  hoping PATH is right;
- it **refuses to start** if ffmpeg is missing, instead of producing split files;
- it prefers mp4+m4a streams so joining is a fast remux, not a slow re-encode;
- `keepvideo=False` deletes the two source streams once merged;
- after the run it scans for leftover `.f137`-style files and warns if any
  merge silently failed.

Result: one `.mp4` per video, picture and sound together.

## Notes

- **Resume anytime.** Ctrl+C and rerun the same command. `archive.txt` records
  finished videos and they are skipped. Partial files continue where they left off.
- **Private or deleted videos** in a playlist are skipped; the rest still download.
- Long titles are trimmed to 180 characters to stay under the 260-character path
  limit on Windows. Keep the project path short for very long playlists.
- Downloading is subject to YouTube's Terms of Service and to copyright in the
  material. Use it for content you own, content licensed for download, or where
  local law otherwise permits.
