#!/usr/bin/env python3
"""
gui_packager.py -- point-and-click disk builder for the Amiga Moon Cresta port.

Pick your MAME Moon Cresta romset, tick the outputs you want (ADF / hard-drive
drawer / LHA), choose where to save, and press Build. It assembles mooncrst.rom
(matching the ROMs by CRC32, so split-vs-merged and filenames don't matter) and
writes the ROM-included disk(s).

When frozen with PyInstaller the ROM-free program is bundled inside, so the user
needs nothing else installed (the .lha output still needs a system lha/jlha).

Run from source:  python3 tools/gui_packager.py
"""
import os, sys, shutil, threading, queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mc_pack
from mc_pack import PackError


class App:
    def __init__(self, root):
        self.root = root
        root.title("Moon Cresta — Amiga Disk Builder")
        root.minsize(640, 480)

        self.romset = tk.StringVar()
        self.outdir = tk.StringVar()
        self.want_adf = tk.BooleanVar(value=True)
        self.want_hd = tk.BooleanVar(value=True)
        self.has_lha = bool(shutil.which("lha") or shutil.which("jlha"))
        self.want_lha = tk.BooleanVar(value=self.has_lha)
        self.q = queue.Queue()

        pad = dict(padx=8, pady=4)
        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="1.  Your MAME Moon Cresta romset (the 'mooncrst' set — split or merged):"
                  ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(frm, textvariable=self.romset).grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(frm, text="File…", command=self.pick_file).grid(row=1, column=1, **pad)
        ttk.Button(frm, text="Folder…", command=self.pick_folder).grid(row=1, column=2, **pad)

        ttk.Label(frm, text="2.  Save the disk(s) to:").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Entry(frm, textvariable=self.outdir).grid(row=3, column=0, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…", command=self.pick_out).grid(row=3, column=1, **pad)

        opts = ttk.LabelFrame(frm, text="3.  Outputs", padding=8)
        opts.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        ttk.Checkbutton(opts, text="Bootable floppy (MoonCresta.adf)", variable=self.want_adf).pack(anchor="w")
        ttk.Checkbutton(opts, text="Hard-drive drawer (run mooncrst)", variable=self.want_hd).pack(anchor="w")
        lha_cb = ttk.Checkbutton(opts, text="LHA archive" + ("" if self.has_lha else "  (needs lha/jlha installed)"),
                                 variable=self.want_lha)
        lha_cb.pack(anchor="w")
        if not self.has_lha:
            lha_cb.state(["disabled"])

        self.build_btn = ttk.Button(frm, text="Build", command=self.start_build)
        self.build_btn.grid(row=5, column=0, columnspan=3, pady=8)

        self.log = scrolledtext.ScrolledText(frm, height=14, state="disabled", wrap="word")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(6, weight=1)

        self._note("Pick your romset and an output folder, then press Build.")
        self.root.after(100, self._drain)

    # ---- pickers ----
    def pick_file(self):
        p = filedialog.askopenfilename(title="Select your Moon Cresta romset",
                                       filetypes=[("ROM archives", "*.zip *.7z"), ("All files", "*.*")])
        if p:
            self.romset.set(p)
            if not self.outdir.get():
                self.outdir.set(os.path.join(os.path.dirname(p), "MoonCresta-disks"))

    def pick_folder(self):
        p = filedialog.askdirectory(title="Select the folder holding your romset")
        if p:
            self.romset.set(p)
            if not self.outdir.get():
                self.outdir.set(os.path.join(p, "MoonCresta-disks"))

    def pick_out(self):
        p = filedialog.askdirectory(title="Where to save the disk(s)")
        if p:
            self.outdir.set(p)

    # ---- logging (thread-safe via queue + after) ----
    def _note(self, msg):
        self.q.put(msg)

    def _drain(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    # ---- build (worker thread) ----
    def start_build(self):
        romset = self.romset.get().strip()
        outdir = self.outdir.get().strip()
        if not romset or not os.path.exists(romset):
            messagebox.showerror("Pick a romset", "Choose your Moon Cresta romset first.")
            return
        if not outdir:
            messagebox.showerror("Pick an output folder", "Choose where to save the disk(s).")
            return
        if not (self.want_adf.get() or self.want_hd.get() or self.want_lha.get()):
            messagebox.showerror("Pick an output", "Tick at least one output.")
            return
        self.build_btn.state(["disabled"])
        self._note("\n--- Building ---")
        threading.Thread(target=self._worker, args=(romset, outdir), daemon=True).start()

    def _worker(self, romset, outdir):
        try:
            res = mc_pack.build(
                romset, outdir,
                want_adf=self.want_adf.get(),
                want_hd=self.want_hd.get(),
                want_lha=self.want_lha.get(),
                build_ok=False,            # never run make from the app
                log=self._note,
            )
            self._note("\nSUCCESS. Boot MoonCresta.adf on an AGA Amiga (the ROM is inside).")
            self.root.after(0, lambda: messagebox.showinfo(
                "Done", "Built:\n" + "\n".join(sorted(res.values()))))
        except PackError as e:
            self._note("\nERROR: %s" % e)
            self.root.after(0, lambda: messagebox.showerror("Couldn't build", str(e)))
        except Exception as e:                                   # noqa
            self._note("\nUNEXPECTED ERROR: %s" % e)
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.root.after(0, lambda: self.build_btn.state(["!disabled"]))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
