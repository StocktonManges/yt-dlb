import sys
import shlex
import subprocess
import tempfile
import threading
from pathlib import Path


# YouTube serves SABR-only streams to its default web clients, so yt-dlp falls
# back to `android_vr`, whose media URLs now answer 403 Forbidden. These
# clients still hand out plain https format URLs, provided a GVS PO token is
# available from the bgutil provider (see README for the one-time setup).
YOUTUBE_CLIENTS = ["--extractor-args", "youtube:player_client=tv_simply,mweb,web_embedded,default"]


def usage():
    """Return adl's own help text (not yt-dlp's)."""
    return f"""adl - download YouTube (or any yt-dlp-supported) audio as mp3.

Usage:
  adl <url> [-s START] [-e END] [-n NAME] [-m DIR]
  adl <playlist-url> -p [-m DIR]
  adl --gui
  adl -h | --help

Options:
  -s START   Trim start. Bare number = seconds. "30", "1:30", "1:30:45".
  -e END     Trim end, same formats. Omit to run to the end of the video.
  -n NAME    Output filename without extension. Default: the video title.
  -m DIR     Move the finished file here instead of the default directory.
  -p         Download the whole playlist the URL points to. Files go into a
             subfolder named after the playlist, numbered by playlist order.
             Cannot be combined with -s/-e/-n. Without -p, a watch URL that
             has a &list=... parameter downloads only that one video.
  --gui      Launch the graphical version.
  -h, --help Show this message.

Notes:
  Downloads land in {default_download_path()} by default.
  When -s/-e are given, the full audio is fetched at native speed and then
  trimmed locally with ffmpeg, which is far faster than yt-dlp's
  --download-sections for short clips of long videos. The trimmed file gets a
  _START-END suffix.

Examples:
  adl 'https://youtu.be/VIDEO'
  adl 'https://youtu.be/VIDEO' -s 1:05 -e 2:30 -n 'tavern ambience'
  adl 'https://youtu.be/VIDEO' -m ~/Desktop
  adl 'https://www.youtube.com/playlist?list=PLAYLIST' -p
"""


def default_download_path():
    """Return the default download directory.

    Prefers the personal DND audio folder when it exists, otherwise falls
    back to the user's Downloads folder.
    """
    preferred = Path("/Users/stockton.manges/PERSONAL/DND/audio")
    if preferred.is_dir():
        return str(preferred)
    return str(Path.home() / "Downloads")


def normalize_time(t):
    """Normalize a user-provided time string for yt-dlp.

    - Bare number (no colon) is treated as seconds: "30" -> "0:30".
    - One colon is treated as minutes:seconds (returned as-is): "1:30".
    - Two colons is treated as hours:minutes:seconds (returned as-is): "1:30:45".
    - Empty values and the literal "inf" are returned unchanged.
    """
    if not t or t == "inf":
        return t
    if ":" not in t:
        return f"0:{int(t):02d}"
    return t


def _time_suffix(norm_start, norm_end):
    """Build the `_HHMMSS-HHMMSS` filename suffix used for trimmed clips."""
    clean_start = (norm_start if norm_start else "0").replace(":", "")
    clean_end = (norm_end if norm_end else "inf").replace(":", "")
    return f"_{clean_start}-{clean_end}"


def run_download(cmd, norm_start, norm_end, move_to=None, log=print, runner=None):
    """Run yt-dlp, then (when a time range is given) ffmpeg-trim the result.

    yt-dlp's own ``--download-sections`` delegates the actual fetch to ffmpeg,
    which streams the source HTTP url at YouTube's per-stream throttle (often
    only ~1-2x real time). Pulling the full audio with yt-dlp's native
    downloader and trimming locally is dramatically faster for short clips of
    long videos.

    Parameters
    ----------
    cmd : list[str]
        Base yt-dlp command (no ``--download-sections``, no ``--exec`` move).
    norm_start, norm_end : str | None
        Normalized time bounds (see :func:`normalize_time`). ``norm_end`` may
        be ``"inf"`` for "until end of video".
    move_to : str | None
        Optional final destination directory.
    log : callable
        Sink for human-readable progress messages.
    runner : callable | None
        Function used to spawn subprocesses. Defaults to ``subprocess.run``.
        Useful for the GUI, which pipes child output into a text widget.

    Returns
    -------
    int
        Exit code: 0 on success, otherwise the failing step's return code.
    """
    if runner is None:
        runner = subprocess.run
    needs_trim = bool(norm_start or norm_end)

    capture_path = None
    if needs_trim:
        # Have yt-dlp write the final mp3 path to a temp file so we know
        # exactly which file to feed to ffmpeg, regardless of %(title)s.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="yt_dlb_path_"
        )
        tmp.close()
        capture_path = tmp.name
        cmd = cmd + ["--print-to-file", "after_move:filepath", capture_path]

    if move_to and not needs_trim:
        target = Path(move_to).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        quoted_target = shlex.quote(str(target))
        cmd = cmd + ["--exec", f"after_move:mv -- %(filepath)q {quoted_target}/"]

    log("Running: " + " ".join(shlex.quote(c) for c in cmd))
    try:
        result = runner(cmd)
    except FileNotFoundError as e:
        log(f"Error: {e}")
        if capture_path:
            Path(capture_path).unlink(missing_ok=True)
        return 127

    if not needs_trim:
        return result.returncode

    try:
        if result.returncode != 0:
            log("yt-dlp exited non-zero; skipping trim.")
            return result.returncode

        try:
            captured = Path(capture_path).read_text().strip().splitlines()
        except FileNotFoundError:
            captured = []
        full_path_str = captured[-1] if captured else ""

        if not full_path_str or not Path(full_path_str).exists():
            log(f"Error: could not locate downloaded file (got: {full_path_str!r}).")
            return 1

        full = Path(full_path_str)
        trimmed = full.with_name(f"{full.stem}{_time_suffix(norm_start, norm_end)}{full.suffix}")

        ffmpeg_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats"]
        if norm_start:
            ffmpeg_cmd.extend(["-ss", norm_start])
        if norm_end and norm_end != "inf":
            ffmpeg_cmd.extend(["-to", norm_end])
        ffmpeg_cmd.extend(["-i", str(full), "-c", "copy", str(trimmed)])

        log("Trimming: " + " ".join(shlex.quote(c) for c in ffmpeg_cmd))
        try:
            trim_result = runner(ffmpeg_cmd)
        except FileNotFoundError as e:
            log(f"Error: {e} (is ffmpeg installed?)")
            return 127
        if trim_result.returncode != 0:
            log(f"ffmpeg trim failed; leaving full file at {full}")
            return trim_result.returncode

        full.unlink(missing_ok=True)

        if move_to:
            target = Path(move_to).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            final = target / trimmed.name
            trimmed.replace(final)
            log(f"Saved to: {final}")
        else:
            log(f"Saved to: {trimmed}")

        return 0
    finally:
        if capture_path:
            Path(capture_path).unlink(missing_ok=True)


# ====================== COMMAND LINE MODE ======================
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
    print(usage())
    sys.exit(0)

if len(sys.argv) > 1 and sys.argv[1] != "--gui":
    url = sys.argv[1]
    start = None
    end = None
    custom_name = None
    move_to = None
    playlist = False

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "-s" and i+1 < len(sys.argv):
            start = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == "-e" and i+1 < len(sys.argv):
            end = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == "-n" and i+1 < len(sys.argv):
            custom_name = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == "-m" and i+1 < len(sys.argv):
            move_to = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == "-p":
            playlist = True
            i += 1
        else:
            i += 1

    if playlist and (start or end or custom_name):
        print("Error: -p cannot be combined with -s, -e or -n.", file=sys.stderr)
        sys.exit(2)

    cmd = ["yt-dlp", "--js-runtimes", "deno", "--remote-components", "ejs:github",
           *YOUTUBE_CLIENTS,
           "-x", "--audio-format", "mp3", "--ignore-errors", "-i"]

    # Normalize bounds so a bare number is interpreted as seconds. We don't
    # pass --download-sections any more: yt-dlp pulls the full audio at
    # native speed, then run_download() trims locally with ffmpeg -c copy.
    norm_start = normalize_time(start)
    norm_end = normalize_time(end)

    if playlist:
        cmd.extend(["--yes-playlist", "-o",
                    "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s"])
    else:
        name_part = custom_name if custom_name else "%(title)s"
        cmd.extend(["--no-playlist", "-o", f"{name_part}.%(ext)s"])

    downloads = default_download_path()
    cmd.extend(["-P", downloads])

    cmd.append(url)

    sys.exit(run_download(cmd, norm_start, norm_end, move_to=move_to))

# ====================== GUI MODE ======================
import tkinter as tk
from tkinter import messagebox, scrolledtext

root = tk.Tk()
root.title("Simple yt-dlp GUI")

tk.Label(root, text="URL:").pack(anchor="w")
url_entry = tk.Entry(root, width=80)
url_entry.pack()

tk.Label(root, text="Start time (e.g. 30, 1:30, 1:30:45):").pack(anchor="w")
start_entry = tk.Entry(root, width=80)
start_entry.pack()

tk.Label(root, text="End time (e.g. 30, 1:30, 1:30:45):").pack(anchor="w")
end_entry = tk.Entry(root, width=80)
end_entry.pack()

tk.Label(root, text="Output filename (without extension - leave empty for video title):").pack(anchor="w")
filename_entry = tk.Entry(root, width=80)
filename_entry.pack()

playlist_var = tk.BooleanVar()
tk.Checkbutton(root, text="Download whole playlist (ignores start/end/filename)",
               variable=playlist_var).pack(anchor="w")

# Common options
opts = [
    ("-x", "Extract audio only", tk.BooleanVar(value=True)),
    ("--audio-format mp3", "Convert audio to MP3", tk.BooleanVar(value=True)),
    ("--no-keep-video", "Delete video after audio extract", tk.BooleanVar()),
    ("--write-subs", "Download subtitles", tk.BooleanVar()),
    ("--embed-subs", "Embed subtitles", tk.BooleanVar()),
    ("--ignore-errors", "Continue on errors", tk.BooleanVar(value=True)),
    ("-i", "Ignore errors (short)", tk.BooleanVar(value=True)),
]

for opt, desc, var in opts:
    frame = tk.Frame(root)
    frame.pack(anchor="w")
    tk.Checkbutton(frame, text=opt, variable=var).pack(side="left")
    tk.Label(frame, text=desc).pack(side="left", padx=5)

tk.Label(root, text="Extra options:").pack(anchor="w")
extra_entry = tk.Entry(root, width=80)
extra_entry.pack()

output = scrolledtext.ScrolledText(root, height=15)
output.pack()

def get_downloads_path():
    return default_download_path()

def submit():
    cmd = ["yt-dlp", "--js-runtimes", "deno", "--remote-components", "ejs:github",
           *YOUTUBE_CLIENTS]

    for opt, _, var in opts:
        if var.get():
            cmd.extend(opt.split())

    if playlist_var.get():
        norm_start = norm_end = None
        cmd.extend(["--yes-playlist", "-o",
                    "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s"])
    else:
        norm_start = normalize_time(start_entry.get().strip())
        norm_end = normalize_time(end_entry.get().strip())
        fname = filename_entry.get().strip()
        name_part = fname if fname else "%(title)s"
        cmd.extend(["--no-playlist", "-o", f"{name_part}.%(ext)s"])

    extra = extra_entry.get().strip()
    if extra:
        cmd.extend(shlex.split(extra))

    url = url_entry.get().strip()
    if not url:
        messagebox.showerror("Error", "Enter URL")
        return

    cmd.append(url)
    downloads = get_downloads_path()
    cmd.extend(["-P", downloads])

    output.insert(tk.END, "Starting download...\n")
    output.see(tk.END)

    def gui_log(msg):
        output.insert(tk.END, msg + "\n")
        output.see(tk.END)

    def gui_runner(args):
        # Pipe yt-dlp/ffmpeg output into the text widget instead of the
        # parent terminal.
        result = subprocess.run(args, capture_output=True, text=True)
        if result.stdout:
            output.insert(tk.END, result.stdout)
        if result.stderr:
            output.insert(tk.END, result.stderr)
        output.see(tk.END)
        return result

    def run():
        try:
            run_download(cmd, norm_start, norm_end, log=gui_log, runner=gui_runner)
            output.insert(tk.END, "Download finished.\n\n")
            output.see(tk.END)
        except Exception as e:
            output.insert(tk.END, f"Error: {e}\n")
            output.see(tk.END)

    threading.Thread(target=run, daemon=True).start()

tk.Button(root, text="Submit", command=submit).pack()
tk.Button(root, text="Clear", command=lambda: [
    url_entry.delete(0, tk.END), 
    start_entry.delete(0, tk.END), 
    end_entry.delete(0, tk.END), 
    filename_entry.delete(0, tk.END), 
    extra_entry.delete(0, tk.END), 
    output.delete(1.0, tk.END)
]).pack()

if __name__ == "__main__":
    if len(sys.argv) <= 1 or sys.argv[1] == "--gui":
        root.mainloop()