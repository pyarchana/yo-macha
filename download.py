#!/usr/bin/env python3
"""
yo-macha - download entire YouTube playlists locally, keeping every name intact.

Folder  : downloads/<Playlist Title> [<playlist id>]/
File    : 001 - <Video Title> [<video id>].mp4     <- ONE file, already merged
Manifest: _playlist.json / _index.md  (holds the ORIGINAL, unsanitized titles)

Usage:
    python download.py <playlist-url> [more urls ...]
    python download.py <url> --quality 1080
    python download.py <url> --audio-only
    python download.py --from-file urls.txt
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
except ImportError:
    sys.exit("yt-dlp is not installed. Run:  pip install -r requirements.txt")


# Folder keeps the human playlist title; the id keeps it unique and re-findable.
# A video downloaded on its own has no playlist, so it lands in "Loose Videos"
# with no "[id]" suffix - the "%(field&yes|no)s" form supplies that condition.
DIR_TMPL = ("%(playlist_title,playlist|Loose Videos)s"
            "%(playlist_id& [|)s%(playlist_id|)s%(playlist_id&]|)s")
# Zero-padded index preserves playlist ORDER, title preserves the name, and the
# video id makes the file traceable back to its source forever. The index and
# its separator vanish entirely for a non-playlist video.
FILE_TMPL = "%(playlist_index&{:03d} - |)s%(title)s [%(id)s].%(ext)s"
# Sidecar files (thumbnails, metadata dumps) go in a _meta subfolder so the
# playlist folder itself lists nothing but the videos.
META_DIR = "_meta"
PL_META_TMPL = "%(title)s [%(id)s].%(ext)s"


def force_utf8_console() -> None:
    """Windows consoles default to cp1252 and crash on unicode video titles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def find_js_runtime() -> str | None:
    """
    yt-dlp now needs a JavaScript runtime to read YouTube's player, and warns
    that going without one is deprecated and may hide some formats. winget
    installs deno without putting it on PATH, so look in its package folder too.
    """
    exe = shutil.which("deno")
    if exe:
        return exe

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        *(local / "Microsoft" / "WinGet" / "Packages").glob("DenoLand.Deno_*/deno.exe"),
        Path.home() / ".deno" / "bin" / "deno.exe",
        Path.home() / ".deno" / "bin" / "deno",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def find_ffmpeg() -> str:
    """
    YouTube serves high-quality video and audio as SEPARATE streams. Without
    ffmpeg, yt-dlp downloads both and leaves you with two files. With it, they
    are muxed into one. So: refuse to run rather than produce split files.
    """
    exe = shutil.which("ffmpeg")
    if exe:
        return str(Path(exe).parent)
    sys.exit(
        "ffmpeg was not found on PATH.\n"
        "Without it, video and audio cannot be merged into a single file.\n"
        "Install it with:  winget install Gyan.FFmpeg\n"
        "then open a NEW terminal so PATH refreshes."
    )


def build_opts(args, outdir: Path) -> dict:
    if args.audio_only:
        fmt = "bestaudio[ext=m4a]/bestaudio/best"
    elif args.quality == "best":
        # Prefer mp4+m4a so the merge is a fast remux, not a re-encode.
        fmt = ("bestvideo[ext=mp4]+bestaudio[ext=m4a]"
               "/bestvideo+bestaudio/best")
    else:
        h = args.quality
        fmt = (f"bestvideo[height<=?{h}][ext=mp4]+bestaudio[ext=m4a]"
               f"/bestvideo[height<=?{h}]+bestaudio"
               f"/best[height<=?{h}]/best")

    opts = {
        "format": fmt,
        "outtmpl": {
            "default": str(outdir / DIR_TMPL / FILE_TMPL),
            # sidecars land beside the videos in _meta, not among them
            "infojson": str(outdir / DIR_TMPL / META_DIR / FILE_TMPL),
            "thumbnail": str(outdir / DIR_TMPL / META_DIR / FILE_TMPL),
            "description": str(outdir / DIR_TMPL / META_DIR / FILE_TMPL),
            "pl_infojson": str(outdir / DIR_TMPL / META_DIR / PL_META_TMPL),
            "pl_thumbnail": str(outdir / DIR_TMPL / META_DIR / PL_META_TMPL),
        },
        "paths": {"temp": str(outdir / ".tmp")},

        # --- one file out, never a split pair ----------------------------
        "ffmpeg_location": find_ffmpeg(),
        "keepvideo": False,          # delete the separate streams after muxing
        "merge_output_format": None if args.audio_only else "mp4",

        # --- name preservation -------------------------------------------
        "windowsfilenames": True,    # strip chars Windows rejects, keep the rest
        "trim_file_name": 180,       # stay under the 260-char path limit
        "restrictfilenames": False,  # keep spaces, unicode, real titles

        # --- metadata: the name also lives INSIDE the file ---------------
        "writeinfojson": True,
        "writedescription": args.extras,
        "writethumbnail": True,
        "postprocessors": [],

        # --- playlist behaviour ------------------------------------------
        "noplaylist": False,
        "ignoreerrors": "only_download",   # skip private/deleted, keep going
        "download_archive": str(outdir / "archive.txt") if args.archive else None,
        "concurrent_fragment_downloads": args.jobs,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        "overwrites": False,
        "consoletitle": True,
    }

    deno = find_js_runtime()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    else:
        print("  note: no JavaScript runtime found, some formats may be missing.\n"
              "        install one with:  winget install DenoLand.Deno",
              file=sys.stderr)

    if args.playlist_items:
        opts["playlist_items"] = args.playlist_items

    if args.audio_only:
        opts["postprocessors"].append(
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
             "preferredquality": "0"})

    # Write title/artist/track-number into the file's own tags, and burn the
    # thumbnail in - so the name survives even if the file is later renamed.
    opts["postprocessors"] += [
        {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
        {"key": "EmbedThumbnail", "already_have_thumbnail": True},
    ]

    if args.subs:
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*", "-live_chat"],
            "subtitlesformat": "srt/best",
        })
        opts["postprocessors"].append(
            {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True})

    if args.cookies_from_browser:
        opts["cookiesfrombrowser"] = (args.cookies_from_browser,)

    return {k: v for k, v in opts.items() if v is not None}


def write_manifest(info: dict, outdir: Path) -> Path | None:
    """Save the untouched titles + order, independent of any filesystem rules."""
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        return None

    title = info.get("title") or info.get("playlist_title") or "Unsorted"
    pid = info.get("id") or "single"
    with YoutubeDL({"windowsfilenames": True, "quiet": True}) as ydl:
        probe = ydl.prepare_filename(
            {**info, "playlist_title": title, "playlist_id": pid, "ext": "x"},
            outtmpl=str(outdir / DIR_TMPL / "x.x"))
    folder = Path(probe).parent
    folder.mkdir(parents=True, exist_ok=True)

    data = {
        "playlist_title": title,
        "playlist_id": pid,
        "playlist_url": info.get("webpage_url"),
        "uploader": info.get("uploader"),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "video_count": len(entries),
        "videos": [
            {
                "index": e.get("playlist_index") or i,
                "title": e.get("title"),          # original, unsanitized
                "id": e.get("id"),
                "url": f"https://www.youtube.com/watch?v={e.get('id')}",
                "uploader": e.get("uploader") or e.get("channel"),
                "duration": e.get("duration"),
            }
            for i, e in enumerate(entries, 1)
        ],
    }

    (folder / "_playlist.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [f"# {title}", "",
             f"{len(entries)} videos - {data['playlist_url'] or ''}", ""]
    lines += [f"{v['index']:03d}. [{v['title']}]({v['url']})"
              for v in data["videos"]]
    (folder / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return folder


def report_split_files(outdir: Path) -> None:
    """Leftover .fNNN files mean a merge failed - say so instead of hiding it."""
    strays = [p for p in outdir.rglob("*.f[0-9][0-9][0-9]*")
              if p.is_file() and p.suffix != ".part"]
    if strays:
        print("\n  WARNING: unmerged stream files were left behind:",
              file=sys.stderr)
        for p in strays[:10]:
            print(f"    {p.name}", file=sys.stderr)
        print("  Rerun with --no-archive to redo those items.", file=sys.stderr)


def main() -> int:
    force_utf8_console()
    p = argparse.ArgumentParser(
        description="Download whole YouTube playlists, keeping playlist and video names.")
    p.add_argument("urls", nargs="*", help="playlist (or video) URLs")
    p.add_argument("--from-file", metavar="FILE", help="text file with one URL per line")
    p.add_argument("-o", "--output", default="downloads", help="output folder (default: downloads)")
    p.add_argument("-q", "--quality", default="1080",
                   help="max height: 480 / 720 / 1080 / 1440 / 2160 / best (default: 1080)")
    p.add_argument("--audio-only", action="store_true", help="extract mp3 audio instead of video")
    p.add_argument("--subs", action="store_true", help="download and embed English subtitles")
    p.add_argument("--extras", action="store_true", help="also save description files")
    p.add_argument("--playlist-items", help="range to grab, e.g. 1-10 or 3,7,12-20")
    p.add_argument("-j", "--jobs", type=int, default=4, help="parallel fragment downloads (default: 4)")
    p.add_argument("--no-archive", dest="archive", action="store_false",
                   help="do not keep archive.txt (which lets you resume and skip duplicates)")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="use your login for private/age-gated lists: chrome, firefox, edge ...")
    args = p.parse_args()

    urls = list(args.urls)
    if args.from_file:
        urls += [ln.strip()
                 for ln in Path(args.from_file).read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    if not urls:
        p.print_help()
        return 1

    outdir = Path(args.output).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    opts = build_opts(args, outdir)

    failed = []
    for url in urls:
        print(f"\n{'=' * 70}\n  {url}\n{'=' * 70}")
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if info:
                folder = write_manifest(info, outdir)
                if folder:
                    print(f"\n  Saved to: {folder}")
                    print(f"  Manifest: {folder / '_playlist.json'}")
        except DownloadError as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            failed.append(url)
        except KeyboardInterrupt:
            print("\n  Interrupted - rerun the same command to resume.", file=sys.stderr)
            return 130

    report_split_files(outdir)
    print(f"\nDone. {len(urls) - len(failed)}/{len(urls)} url(s) succeeded.")
    for u in failed:
        print(f"  failed: {u}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
