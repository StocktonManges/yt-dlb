import tkinter as tk
from tkinter import messagebox, scrolledtext
import subprocess
import threading
import os
from pathlib import Path
from datetime import datetime

root = tk.Tk()
root.title("Simple yt-dlp GUI")

tk.Label(root, text="URL:").pack(anchor="w")
url_entry = tk.Entry(root, width=80)
url_entry.pack()

tk.Label(root, text="Start time (e.g. 10:15):").pack(anchor="w")
start_entry = tk.Entry(root, width=80)
start_entry.pack()

tk.Label(root, text="End time (e.g. 20:30):").pack(anchor="w")
end_entry = tk.Entry(root, width=80)
end_entry.pack()

tk.Label(root, text="Output filename (without extension):").pack(anchor="w")
filename_entry = tk.Entry(root, width=80)
filename_entry.pack()

# Common options - defaults set
opts = [
    ("-x", "Extract audio only", tk.BooleanVar(value=True)),      # default ON
    ("--audio-format mp3", "Convert audio to MP3", tk.BooleanVar(value=True)),  # default ON
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
    return str(Path.home() / "Downloads")

def submit():
    cmd = ["yt-dlp", "--js-runtimes", "deno", "--remote-components", "ejs:github"]
    
    for opt, _, var in opts:
        if var.get():
            cmd.extend(opt.split())
    
    start = start_entry.get().strip()
    end = end_entry.get().strip()
    if start:
        section = f"*{start}-{end if end else 'inf'}"
        cmd.extend(["--download-sections", section])
    
    fname = filename_entry.get().strip()
    if not fname:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        fname = f"audio_{ts}"
    
    cmd.extend(["-o", f"{fname}.%(ext)s"])
    
    extra = extra_entry.get().strip()
    if extra:
        cmd.extend(extra.split())
    
    url = url_entry.get().strip()
    if not url:
        messagebox.showerror("Error", "Enter URL")
        return
    cmd.append(url)
    
    downloads = get_downloads_path()
    cmd.extend(["-P", downloads])
    
    def run():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            output.insert(tk.END, " ".join(cmd) + "\n" + result.stdout + result.stderr + "\n\n")
            output.see(tk.END)
        except Exception as e:
            output.insert(tk.END, f"Error: {e}\n")
    
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

root.mainloop()