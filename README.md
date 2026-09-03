# Requirements

`yt-dlp` requires JavaScript to pass YouTube challenges. EJS packages can be installed via pip like so:

```
pip install -U "yt-dlp[default]"
```

Install the deno JS runtime and place it in the PATH variable:

```
winget install deno
```

Install ffmpeg and place it in the PATH variable:

```
winget install ffmpeg
```

> This is to support downloading a specific time range of a video and converting audio files to .mp3.

## macOS: `adl` command

On macOS, `adl` is a small shell script that calls:

```
python3 "/Users/stockton.manges/Documents/Git/yt-dlb/main.py" "$@"
```

`"$@"` forwards every argument you pass to `adl` directly to `main.py`.

To use `adl` like a normal command:

```
chmod +x adl
```

Then either:

- run it from the repo with `./adl ...`, or
- move/symlink it into a directory on your `PATH` (for example `/usr/local/bin/adl`) so you can run `adl ...` from anywhere.

## CLI flags and options

### `adl` wrapper flags

The Python wrapper in `main.py` recognizes these flags:

- `-s <time>`: Start timestamp (for partial download), e.g. `1:30`
- `-e <time>`: End timestamp, e.g. `3:00`
- `-n <name>`: Custom output filename (without extension)
- `-m <path>`: Absolute directory to move the final `.mp3` into after download. The file is first written to `~/Downloads` (so yt-dlp can clean up the intermediate `.webm`), then moved to `<path>` via yt-dlp's `--exec after_move`. The directory is created if it doesn't exist.

Usage pattern:

```
adl <url> [-s start] [-e end] [-n output_name] [-m /absolute/move/path]
```

Examples:

```
adl "https://www.youtube.com/watch?v=VIDEO_ID"
adl "https://www.youtube.com/watch?v=VIDEO_ID" -s 1:30 -e 3:00
adl "https://www.youtube.com/watch?v=VIDEO_ID" -n "my_clip"
adl "https://www.youtube.com/watch?v=VIDEO_ID" -s 0:45 -e 2:10 -n "intro_section"
adl "https://www.youtube.com/watch?v=VIDEO_ID" -n "battle_theme" -m "/Users/stockton.manges/PERSONAL/DND/music"
```

### Default `yt-dlp` options used by `adl`

`adl` always builds a `yt-dlp` command with:

- `--js-runtimes deno`
- `--remote-components ejs:github`
- `-x --audio-format mp3` (audio-only MP3 output)
- `--ignore-errors -i`
- `-o <name>.%(ext)s`
- `-P ~/Downloads`

If `-s` (and optional `-e`) is provided, `adl` also adds `--download-sections "*start-end"`.

### See all `yt-dlp` flags

Because `adl` passes arguments into the Python wrapper and then into `yt-dlp`, you can print `yt-dlp` help with:

```
adl -h
```

## One-time setup: PO token provider

YouTube now serves SABR-only streams to yt-dlp's default web clients, so yt-dlp
falls back to the `android_vr` client — whose media URLs answer
`HTTP Error 403: Forbidden`. The clients that still hand out plain https URLs
(`tv_simply`, `mweb`, `web_embedded`, pinned via `YOUTUBE_CLIENTS` in
`main.py`) require a GVS PO token, which yt-dlp can only get from an external
provider.

Install the provider once:

```bash
# yt-dlp plugin (Homebrew's yt-dlp uses its own Python, so drop the plugin
# into yt-dlp's plugin dir rather than pip-installing into the system Python)
python3 -m pip install -U bgutil-ytdlp-pot-provider
SP=$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
mkdir -p ~/.config/yt-dlp/plugins/bgutil-ytdlp-pot-provider
cp -R "$SP/yt_dlp_plugins" ~/.config/yt-dlp/plugins/bgutil-ytdlp-pot-provider/

# token server (restarts automatically with Docker)
docker run --name bgutil-provider -d --restart unless-stopped \
  -p 4416:4416 brainicism/bgutil-ytdlp-pot-provider
```

Verify with `curl http://127.0.0.1:4416/ping`. If downloads start 403'ing
again, first check that Docker is running and that container is up; then check
`yt-dlp -v <url>` for a `[pot] PO Token Providers:` line that lists
`bgutil:http` rather than `none`.
