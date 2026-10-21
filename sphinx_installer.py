# -*- coding: utf-8 -*-
"""Сфинксляндия Installer: находит установленные лаунчеры (официальный, TLauncher, Prism, PolyMC,
MultiMC, Modrinth App, CurseForge, ATLauncher, GDLauncher), даёт выбрать сборку, ставит туда
Simple Voice Chat и добавляет сервер."""
import json, os, re, shutil, sqlite3, struct, tempfile, threading, urllib.parse, urllib.request, webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

# ====== НАСТРОЙКИ (поменяй тут) ======
SERVER_NAME = "Сфинксляндия"
SERVER_IP = "FatSphynx.gomc.me"
MOD_SLUG = "simple-voice-chat"
LAUNCHER_URL = "https://launcher.mojang.com/download/MinecraftInstaller.exe"
# =====================================

UA = {"User-Agent": "SphinxInstaller/1.0"}
MC_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), ".minecraft")

# ---------- минимальный NBT ----------
def _rd(b, p, t):
    if t == 1: return struct.unpack_from(">b", b, p)[0], p + 1
    if t == 2: return struct.unpack_from(">h", b, p)[0], p + 2
    if t == 3: return struct.unpack_from(">i", b, p)[0], p + 4
    if t == 4: return struct.unpack_from(">q", b, p)[0], p + 8
    if t == 5: return struct.unpack_from(">f", b, p)[0], p + 4
    if t == 6: return struct.unpack_from(">d", b, p)[0], p + 8
    if t == 7:
        n = struct.unpack_from(">i", b, p)[0]; return bytes(b[p+4:p+4+n]), p + 4 + n
    if t == 8:
        n = struct.unpack_from(">H", b, p)[0]; return b[p+2:p+2+n].decode("utf-8", "replace"), p + 2 + n
    if t == 9:
        et = b[p]; n = struct.unpack_from(">i", b, p+1)[0]; p += 5; out = []
        for _ in range(n):
            v, p = _rd(b, p, et); out.append(v)
        return (et, out), p
    if t == 10:
        d = {}
        while b[p] != 0:
            nt = b[p]; ln = struct.unpack_from(">H", b, p+1)[0]
            name = b[p+3:p+3+ln].decode("utf-8", "replace"); p += 3 + ln
            v, p = _rd(b, p, nt); d[name] = (nt, v)
        return d, p + 1
    if t == 11:
        n = struct.unpack_from(">i", b, p)[0]; return list(struct.unpack_from(f">{n}i", b, p+4)), p + 4 + 4*n
    if t == 12:
        n = struct.unpack_from(">i", b, p)[0]; return list(struct.unpack_from(f">{n}q", b, p+4)), p + 4 + 8*n
    raise ValueError("bad nbt tag %d" % t)

def _wr(t, v):
    if t == 1: return struct.pack(">b", v)
    if t == 2: return struct.pack(">h", v)
    if t == 3: return struct.pack(">i", v)
    if t == 4: return struct.pack(">q", v)
    if t == 5: return struct.pack(">f", v)
    if t == 6: return struct.pack(">d", v)
    if t == 7: return struct.pack(">i", len(v)) + v
    if t == 8:
        s = v.encode("utf-8"); return struct.pack(">H", len(s)) + s
    if t == 9:
        et, items = v
        return struct.pack(">bi", et, len(items)) + b"".join(_wr(et, i) for i in items)
    if t == 10:
        out = b""
        for k, (nt, nv) in v.items():
            kb = k.encode("utf-8")
            out += struct.pack(">bH", nt, len(kb)) + kb + _wr(nt, nv)
        return out + b"\x00"
    if t == 11: return struct.pack(">i", len(v)) + struct.pack(f">{len(v)}i", *v)
    if t == 12: return struct.pack(">i", len(v)) + struct.pack(f">{len(v)}q", *v)
    raise ValueError(t)

def add_server(game_dir, name, ip):
    path = os.path.join(game_dir, "servers.dat")
    os.makedirs(game_dir, exist_ok=True)
    root = {"servers": (9, (10, []))}
    if os.path.exists(path):
        data = open(path, "rb").read()
        if data:
            shutil.copy2(path, path + ".bak")
            ln = struct.unpack_from(">H", data, 1)[0]
            root, _ = _rd(data, 3 + ln, 10)
    if "servers" not in root or root["servers"][1][0] != 10 and root["servers"][1][1]:
        root["servers"] = (9, (10, []))
    lst = root["servers"][1][1]
    for s in lst:
        if s.get("ip", (8, ""))[1].lower() == ip.lower():
            return False  # уже есть
    lst.append({"name": (8, name), "ip": (8, ip)})
    root["servers"] = (9, (10, lst))
    open(path, "wb").write(b"\x0a\x00\x00" + _wr(10, root))
    return True

# ---------- определение сборок ----------
APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
HOME = os.path.expanduser("~")
LOADERS = ("neoforge", "forge", "fabric", "quilt")

def loader_from_text(s):
    s = (s or "").lower()
    for l in LOADERS:
        if l in s:
            return l
    return None

def mc_version(vid):
    v = (vid or "").lower()
    m = re.search(r"neoforge[-_ ]?(\d+)\.(\d+)", v)
    if m:
        a, b = m.groups()
        return "1.%s" % a if b == "0" else "1.%s.%s" % (a, b)
    m = re.search(r"(?<![\d.])(1\.\d+(?:\.\d+)?)", v)
    return m.group(1) if m else None

def read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def inst(launcher, name, game_dir, mc, loader, vid=None, dotmc=False):
    return {"launcher": launcher, "name": name, "game_dir": game_dir, "mc": mc,
            "loader": loader, "vid": vid, "dotmc": dotmc}

def sub_dirs(p):
    try:
        return [d for d in sorted(os.listdir(p)) if os.path.isdir(os.path.join(p, d))]
    except Exception:
        return []

def scan_dotminecraft(label):
    """Официальный лаунчер / TLauncher / SKLauncher: общая папка .minecraft."""
    if not os.path.isdir(MC_DIR):
        return None
    out, seen = [], set()
    for fn in ("launcher_profiles.json", "tlauncher_profiles.json"):
        data = read_json(os.path.join(MC_DIR, fn))
        for pid, p in ((data or {}).get("profiles") or {}).items():
            vid = p.get("lastVersionId", "")
            l = loader_from_text(vid)
            if l:
                out.append(inst(label, "%s [%s]" % (p.get("name") or pid, vid),
                                p.get("gameDir") or MC_DIR, mc_version(vid), l, vid, True))
                seen.add(vid)
    for v in sub_dirs(os.path.join(MC_DIR, "versions")):
        l = loader_from_text(v)
        if l and v not in seen:
            out.append(inst(label, "%s (папка .minecraft)" % v, MC_DIR, mc_version(v), l, v, True))
    return out

def scan_prism(root, label):
    idir = os.path.join(root, "instances")
    if not os.path.isdir(idir):
        return None
    out = []
    uid_map = {"net.minecraftforge": "forge", "net.neoforged": "neoforge",
               "net.fabricmc.fabric-loader": "fabric", "org.quiltmc.quilt-loader": "quilt"}
    for d in sub_dirs(idir):
        if d.startswith("_"):
            continue
        base = os.path.join(idir, d)
        pack = read_json(os.path.join(base, "mmc-pack.json"))
        if pack is None:
            continue
        mc = loader = None
        for c in pack.get("components", []):
            if c.get("uid") == "net.minecraft":
                mc = c.get("version")
            if c.get("uid") in uid_map:
                loader = uid_map[c["uid"]]
        name = d
        try:
            for line in open(os.path.join(base, "instance.cfg"), encoding="utf-8", errors="ignore"):
                if line.startswith("name="):
                    name = line.split("=", 1)[1].strip() or d
        except Exception:
            pass
        gd = next((os.path.join(base, x) for x in ("minecraft", ".minecraft")
                   if os.path.isdir(os.path.join(base, x))), os.path.join(base, "minecraft"))
        out.append(inst(label, name, gd, mc, loader))
    return out

def scan_modrinth():
    root = next((r for r in (os.path.join(APPDATA, "ModrinthApp"),
                             os.path.join(APPDATA, "com.modrinth.theseus")) if os.path.isdir(r)), None)
    if not root:
        return None
    pdir = os.path.join(root, "profiles")
    meta = {}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % os.path.join(root, "app.db").replace("\\", "/"), uri=True)
        for path, name, gv, ml in con.execute("SELECT path, name, game_version, mod_loader FROM profiles"):
            meta[path] = (name, gv, ml)
        con.close()
    except Exception:
        pass
    out = []
    for d in sub_dirs(pdir):
        name, gv, ml = meta.get(d, (d, None, None))
        ml = (ml or "").lower()
        out.append(inst("Modrinth App", name, os.path.join(pdir, d), gv, ml if ml in LOADERS else None))
    return out

def scan_curseforge():
    roots = [os.path.join(HOME, "curseforge", "minecraft", "Instances"),
             os.path.join(HOME, "Documents", "curseforge", "minecraft", "Instances")]
    root = next((r for r in roots if os.path.isdir(r)), None)
    if not root:
        return None
    return scan_curse_dir(root)

def scan_curse_dir(root):
    out = []
    for d in sub_dirs(root):
        base = os.path.join(root, d)
        j = read_json(os.path.join(base, "minecraftinstance.json")) or {}
        bml = (j.get("baseModLoader") or {}).get("name", "")
        out.append(inst("CurseForge", d, base, j.get("gameVersion") or mc_version(bml), loader_from_text(bml)))
    return out

def scan_atl(root=None):
    root = root or os.path.join(APPDATA, "ATLauncher", "instances")
    if not os.path.isdir(root):
        return None
    out = []
    for d in sub_dirs(root):
        base = os.path.join(root, d)
        j = read_json(os.path.join(base, "instance.json")) or {}
        lv = (j.get("launcher") or {}).get("loaderVersion") or {}
        out.append(inst("ATLauncher", (j.get("launcher") or {}).get("name") or d, base,
                        j.get("id") if mc_version(j.get("id")) else None,
                        loader_from_text(str(lv.get("type", "")))))
    return out

def scan_gdl():
    root = os.path.join(APPDATA, "gdlauncher_carbon", "data", "instances")
    if not os.path.isdir(root):
        return None
    out = []
    for d in sub_dirs(root):
        base = os.path.join(root, d)
        gd = os.path.join(base, "instance") if os.path.isdir(os.path.join(base, "instance")) else base
        txt = ""
        try:
            txt = open(os.path.join(base, "config.json"), encoding="utf-8", errors="ignore").read()
        except Exception:
            pass
        m = re.search(r'"(?:mcVersion|minecraft|gameVersion)"\s*:\s*"(1\.[\d.]+)"', txt)
        out.append(inst("GDLauncher", d, gd, m.group(1) if m else None, loader_from_text(txt)))
    return out

def scan_folder(path):
    """Ручной выбор: папка лаунчера или отдельной сборки."""
    for fn in (lambda: scan_prism(path, "Другой лаунчер"), lambda: scan_atl(os.path.join(path, "instances")),
               lambda: scan_curse_dir(path) if os.path.isfile(os.path.join(path, (sub_dirs(path) or ["_"])[0], "minecraftinstance.json")) else None):
        r = fn()
        if r:
            return r
    pd = os.path.join(path, "profiles")
    if os.path.isdir(pd):
        return [inst("Другой лаунчер", d, os.path.join(pd, d), None, None) for d in sub_dirs(pd)]
    gd = next((os.path.join(path, x) for x in ("minecraft", ".minecraft") if os.path.isdir(os.path.join(path, x))), path)
    return [inst("Другой лаунчер", os.path.basename(path.rstrip("\\/")) or path, gd, None, None)]

def find_launchers():
    """-> {название лаунчера: [сборки]} только для найденных."""
    cands = [
        (".minecraft (официальный, TLauncher, SKLauncher)", lambda: scan_dotminecraft(".minecraft")),
        ("Prism Launcher", lambda: scan_prism(os.path.join(APPDATA, "PrismLauncher"), "Prism Launcher")),
        ("PolyMC", lambda: scan_prism(os.path.join(APPDATA, "PolyMC"), "PolyMC")),
        ("MultiMC", lambda: scan_prism(os.path.join(APPDATA, "MultiMC"), "MultiMC")),
        ("Modrinth App", scan_modrinth),
        ("CurseForge", scan_curseforge),
        ("ATLauncher", scan_atl),
        ("GDLauncher", scan_gdl),
    ]
    found = {}
    for name, fn in cands:
        try:
            r = fn()
        except Exception:
            r = None
        if r is not None:
            found[name] = r
    return found

# ---------- скачивание ----------
def http_get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)

def pick_version(project, mc, loader):
    q = urllib.parse.urlencode({"loaders": json.dumps([loader]), "game_versions": json.dumps([mc])})
    vs = json.load(http_get("https://api.modrinth.com/v2/project/%s/version?%s" % (project, q)))
    return vs[0] if vs else None

def download_file(v, mods, log):
    files = v["files"]
    f = next((x for x in files if x.get("primary")), files[0])
    dest = os.path.join(mods, f["filename"])
    if os.path.exists(dest):
        log("Уже есть: " + f["filename"])
        return
    log("Скачиваю %s..." % f["filename"])
    with http_get(f["url"]) as r, open(dest, "wb") as out:
        shutil.copyfileobj(r, out)

def install_voice_chat(game_dir, mc, loader, log):
    log("Ищу Simple Voice Chat для %s %s..." % (loader, mc))
    v = pick_version(MOD_SLUG, mc, loader)
    if not v:
        raise RuntimeError("Для %s %s нет Simple Voice Chat" % (loader, mc))
    mods = os.path.join(game_dir, "mods")
    os.makedirs(mods, exist_ok=True)
    for old in os.listdir(mods):
        if "voicechat" in old.lower() and old.endswith(".jar"):
            os.remove(os.path.join(mods, old))
            log("Удалил старую версию: " + old)
    download_file(v, mods, log)
    for dep in v.get("dependencies", []):
        if dep.get("dependency_type") == "required" and dep.get("project_id"):
            dv = pick_version(dep["project_id"], mc, loader)
            if dv:
                log("Нужная зависимость:")
                download_file(dv, mods, log)
    log("Мод установлен ✔")

def create_new_build(vid):
    """Отдельная папка + профиль в .minecraft лаунчере с той же версией."""
    gd = os.path.join(MC_DIR, "sphinxlandia")
    os.makedirs(gd, exist_ok=True)
    pj = os.path.join(MC_DIR, "launcher_profiles.json")
    data = read_json(pj) or {"profiles": {}}
    if os.path.exists(pj):
        shutil.copy2(pj, pj + ".bak")
    data.setdefault("profiles", {})["sphinxlandia"] = {
        "name": SERVER_NAME, "type": "custom", "lastVersionId": vid, "gameDir": gd}
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return gd

DOWNLOADS = {
    "Официальный Minecraft Launcher (скачать exe)": None,
    "Prism Launcher": "https://prismlauncher.org/download/",
    "Modrinth App": "https://modrinth.com/app",
    "CurseForge": "https://www.curseforge.com/download/app",
    "TLauncher": "https://tlauncher.org/",
}

# ---------- GUI ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Сфинксляндия — установщик")
        root.geometry("640x640")
        self.found = {}
        self.extra = None
        pad = {"padx": 12, "pady": 4}
        B = ("Segoe UI", 11, "bold")
        ttk.Label(root, text="1. Лаунчер", font=B).pack(anchor="w", **pad)
        self.lcombo = ttk.Combobox(root, state="readonly", width=70)
        self.lcombo.pack(**pad)
        self.lcombo.bind("<<ComboboxSelected>>", lambda e: self.fill_instances())
        row = ttk.Frame(root); row.pack(anchor="w", **pad)
        ttk.Button(row, text="Обновить", command=self.refresh).pack(side="left")
        ttk.Button(row, text="Указать папку лаунчера/сборки...", command=self.pick_folder).pack(side="left", padx=6)
        ttk.Label(root, text="2. Сборка", font=B).pack(anchor="w", **pad)
        self.icombo = ttk.Combobox(root, state="readonly", width=70)
        self.icombo.pack(**pad)
        ttk.Label(root, text="3. Адрес сервера", font=B).pack(anchor="w", **pad)
        self.ip = ttk.Entry(root, width=40)
        self.ip.insert(0, SERVER_IP)
        self.ip.pack(anchor="w", **pad)
        ttk.Button(root, text="УСТАНОВИТЬ мод + добавить сервер", command=self.go).pack(**pad)
        ttk.Label(root, text="Нет нужного лаунчера? Скачать:", font=B).pack(anchor="w", **pad)
        row2 = ttk.Frame(root); row2.pack(anchor="w", **pad)
        self.dl = ttk.Combobox(row2, state="readonly", width=46, values=list(DOWNLOADS))
        self.dl.current(0); self.dl.pack(side="left")
        ttk.Button(row2, text="Скачать", command=self.download_launcher).pack(side="left", padx=6)
        self.logbox = tk.Text(root, height=9, state="disabled")
        self.logbox.pack(fill="both", expand=True, **pad)
        self.refresh()

    def log(self, s):
        def f():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", s + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.root.after(0, f)

    def refresh(self):
        self.found = find_launchers()
        if self.extra:
            self.found["Выбрано вручную"] = self.extra
        names = ["%s — сборок: %d" % (k, len(v)) for k, v in self.found.items()]
        self.keys = list(self.found)
        self.lcombo["values"] = names
        if names:
            self.lcombo.current(0)
        else:
            self.lcombo.set("")
            self.log("Лаунчеры не найдены. Скачай один из списка внизу или укажи папку вручную.")
        self.fill_instances()
        self.log("Найдено лаунчеров: %d" % len(self.found))

    def fill_instances(self):
        i = self.lcombo.current()
        self.cur = self.found[self.keys[i]] if i >= 0 and self.keys else []
        def label(b):
            l = b["loader"] or "?"
            return "%s  [%s %s]" % (b["name"], l, b["mc"] or "?")
        self.icombo["values"] = [label(b) for b in self.cur]
        if self.cur:
            self.icombo.current(0)
        else:
            self.icombo.set("")

    def pick_folder(self):
        d = filedialog.askdirectory(title="Папка лаунчера (с instances/profiles) или самой сборки (с mods)")
        if not d:
            return
        self.extra = scan_folder(d)
        self.refresh()
        self.lcombo.current(len(self.keys) - 1)
        self.fill_instances()

    def download_launcher(self):
        name = self.dl.get()
        url = DOWNLOADS[name]
        if url:
            webbrowser.open(url)
            self.log("Открыл сайт: %s. Поставь лаунчер, создай сборку с Forge/Fabric и нажми «Обновить»." % url)
            return
        def work():
            try:
                self.log("Скачиваю официальный лаунчер Minecraft...")
                p = os.path.join(tempfile.gettempdir(), "MinecraftInstaller.exe")
                with http_get(LAUNCHER_URL) as r, open(p, "wb") as o:
                    shutil.copyfileobj(r, o)
                self.log("Запускаю установщик. После установки войди в аккаунт и поставь Forge, затем «Обновить».")
                os.startfile(p)
            except Exception as e:
                self.log("Ошибка: %s" % e)
        threading.Thread(target=work, daemon=True).start()

    def go(self):
        i = self.icombo.current()
        if i < 0:
            return messagebox.showwarning("Нет сборки", "Выбери сборку или создай её в лаунчере.")
        b = dict(self.cur[i])
        ip = self.ip.get().strip()
        if not ip or "ВПИШИ" in ip:
            return messagebox.showwarning("Адрес", "Впиши адрес сервера.")
        if not b["mc"]:
            b["mc"] = simpledialog.askstring("Версия", "Версия Minecraft этой сборки (например 1.20.1):")
        if not b["loader"]:
            b["loader"] = (simpledialog.askstring("Загрузчик", "Какой загрузчик? forge / neoforge / fabric / quilt") or "").strip().lower()
        if not b["mc"] or b["loader"] not in LOADERS:
            return messagebox.showwarning("Данные", "Нужны версия Minecraft и загрузчик.")
        gd = b["game_dir"]
        mods = os.path.join(gd, "mods")
        if os.path.isdir(mods) and any(f.endswith(".jar") for f in os.listdir(mods)):
            if b["dotmc"] and b["vid"]:
                ans = messagebox.askyesnocancel(
                    "В сборке уже есть моды",
                    "В этой сборке уже установлены моды. Добавить Simple Voice Chat к ним?\n\n"
                    "Да — добавить в эту сборку\nНет — создать новую отдельную сборку\nОтмена — выйти")
            else:
                ans = messagebox.askokcancel(
                    "В сборке уже есть моды",
                    "В этой сборке уже установлены моды. Добавить Simple Voice Chat к ним?") or None
            if ans is None:
                return
            if ans is False:
                gd = None

        def work():
            try:
                g = gd or create_new_build(b["vid"])
                if not gd:
                    self.log("Создана новая сборка: " + g)
                install_voice_chat(g, b["mc"], b["loader"], self.log)
                self.log("Сервер добавлен ✔" if add_server(g, SERVER_NAME, ip) else "Сервер уже был в списке")
                self.log("Готово! Запускай игру.")
            except Exception as e:
                self.log("Ошибка: %s" % e)
        threading.Thread(target=work, daemon=True).start()

if __name__ == "__main__":
    r = tk.Tk()
    App(r)
    r.mainloop()
