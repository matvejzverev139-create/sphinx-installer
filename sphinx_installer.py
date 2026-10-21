# -*- coding: utf-8 -*-
"""Сфинксляндия Installer: находит установленные лаунчеры (официальный, TLauncher, Prism, PolyMC,
MultiMC, Modrinth App, CurseForge, ATLauncher, GDLauncher), даёт выбрать сборку, ставит туда
Simple Voice Chat и добавляет сервер."""
import json, os, re, shutil, sqlite3, struct, subprocess, tempfile, threading, urllib.error, urllib.parse, urllib.request, webbrowser, zipfile
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
LN = {"fabric": "Fabric", "forge": "Forge", "neoforge": "NeoForge", "quilt": "Quilt"}
MC_GROUP = "Minecraft Launcher / TLauncher / SKLauncher"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def loader_from_text(s):
    s = (s or "").lower()
    for l in LOADERS:
        if l in s:
            return l
    return None

def mc_version(vid):
    v = (vid or "").lower()
    m = re.search(r"neoforge[-_ ]?(\d+(?:\.\d+)*)", v)
    if m:
        n = m.group(1).split(".")
        if int(n[0]) >= 25:  # 26.2.0.57 -> 26.2 ; 26.1.2.78 -> 26.1.2
            return n[0] + "." + n[1] + ("" if len(n) < 3 or n[2] == "0" else "." + n[2])
        return "1.%s" % n[0] if len(n) < 2 or n[1] == "0" else "1.%s.%s" % (n[0], n[1])
    m = re.search(r"(?<![\d.])((?:1\.\d+|\d{2})\.\d+(?:\.\d+)?|1\.\d+)", v)
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

def official_installed():
    for p in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if p and os.path.isdir(os.path.join(p, "Minecraft Launcher")):
            return True
    lp = os.environ.get("LOCALAPPDATA")
    try:
        return bool(lp) and any(x.startswith("Microsoft.4297127D64EC6") for x in os.listdir(os.path.join(lp, "Packages")))
    except Exception:
        return False

def scan_dotminecraft(label):
    """Официальный лаунчер / TLauncher / SKLauncher: общая папка .minecraft."""
    if not os.path.isdir(MC_DIR):
        return [] if official_installed() else None
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
            out.append(inst(label, "%s (.minecraft)" % v, MC_DIR, mc_version(v), l, v, True))
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
        (MC_GROUP, lambda: scan_dotminecraft(".minecraft")),
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
        log(T("log_exists", f["filename"]))
        return
    log(T("log_dl", f["filename"]))
    with http_get(f["url"]) as r, open(dest, "wb") as out:
        shutil.copyfileobj(r, out)

def install_voice_chat(game_dir, mc, loader, log):
    log(T("log_search", loader, mc))
    v = pick_version(MOD_SLUG, mc, loader)
    if not v:
        raise RuntimeError(T("err_nomod", loader, mc))
    mods = os.path.join(game_dir, "mods")
    os.makedirs(mods, exist_ok=True)
    for old in os.listdir(mods):
        if "voicechat" in old.lower() and old.endswith(".jar"):
            os.remove(os.path.join(mods, old))
            log(T("log_removed", old))
    download_file(v, mods, log)
    for dep in v.get("dependencies", []):
        if dep.get("dependency_type") == "required" and dep.get("project_id"):
            dv = pick_version(dep["project_id"], mc, loader)
            if dv:
                log(T("log_dep"))
                download_file(dv, mods, log)
    log(T("log_modok"))

def create_new_build(vid):
    """Отдельная папка + профиль в .minecraft лаунчере с той же версией."""
    gd = os.path.join(MC_DIR, "sphinxlandia")
    os.makedirs(gd, exist_ok=True)
    pj = os.path.join(MC_DIR, "launcher_profiles.json")
    data = read_json(pj) or {"profiles": {}, "version": 3}
    if os.path.exists(pj):
        shutil.copy2(pj, pj + ".bak")
    data.setdefault("profiles", {})["sphinxlandia"] = {
        "name": SERVER_NAME, "type": "custom", "lastVersionId": vid, "gameDir": gd}
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return gd

# ---------- создание новой сборки (Fabric / Forge / NeoForge) ----------
def jget(url):
    with http_get(url) as r:
        return json.load(r)

def forge_version(mc):
    p = jget("https://files.minecraftforge.net/net.minecraftforge.files/promotions_slim.json").get("promos", {})
    v = p.get(mc + "-recommended") or p.get(mc + "-latest")
    if not v:
        raise RuntimeError(T("err_nover", "Forge", mc))
    return v

def neoforge_version(mc):
    p = mc.split(".")
    try:
        if int(p[0]) >= 25:   # 26.2 -> "26.2.0." , 26.1.2 -> "26.1.2."
            pref = ".".join(p + ["0"] * (3 - len(p))) + "."
        else:                 # 1.21.11 -> "21.11."
            pref = "%s.%s." % (p[1], p[2] if len(p) > 2 else "0")
    except Exception:
        raise RuntimeError(T("err_nover", "NeoForge", mc))
    vs = jget("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge").get("versions", [])
    stable = [v for v in vs if v.startswith(pref) and "-" not in v]
    pool = stable or [v for v in vs if v.startswith(pref)]
    if not pool:
        raise RuntimeError(T("err_nover", "NeoForge", mc))
    return max(pool, key=lambda v: tuple(int(x) for x in re.findall(r"\d+", v)))

def latest_mc():
    """Самая новая версия игры (из манифеста Mojang)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", headers=UA), timeout=6) as r:
            return json.load(r)["latest"]["release"]
    except Exception:
        return "26.2"

def fabric_version(mc):
    vs = jget("https://meta.fabricmc.net/v2/versions/loader/" + mc)
    for e in vs:
        if e["loader"].get("stable"):
            return e["loader"]["version"]
    if vs:
        return vs[0]["loader"]["version"]
    raise RuntimeError(T("err_nover", "Fabric", mc))

def java_major(path):
    try:
        p = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20,
                           creationflags=NOWIN, errors="ignore")
        m = re.search(r'version "(\d+)(?:\.(\d+))?', (p.stderr or "") + (p.stdout or ""))
        if m:
            return int(m.group(2)) if m.group(1) == "1" and m.group(2) else int(m.group(1))
    except Exception:
        pass
    return 0

def need_java(mc):
    try:
        return 25 if int(mc.split(".")[0]) >= 25 else 21
    except Exception:
        return 21

def find_java(log, need=21):
    log(T("log_java"))
    cands = []
    jh = os.environ.get("JAVA_HOME")
    if jh:
        cands.append(os.path.join(jh, "bin", "java.exe"))
    w = shutil.which("java")
    if w:
        cands.append(w)
    for base, _, files in os.walk(os.path.join(MC_DIR, "runtime")):
        if "java.exe" in files:
            cands.append(os.path.join(base, "java.exe"))
    for c in cands:
        if os.path.isfile(c) and java_major(c) >= need:
            return c
    log(T("log_java_dl"))
    tmp = tempfile.mkdtemp()
    z = os.path.join(tmp, "jre.zip")
    with http_get("https://api.adoptium.net/v3/binary/latest/%d/ga/windows/x64/jre/hotspot/normal/eclipse" % need) as r, open(z, "wb") as o:
        shutil.copyfileobj(r, o)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(tmp)
    for base, _, files in os.walk(tmp):
        if "java.exe" in files:
            return os.path.join(base, "java.exe")
    raise RuntimeError("Java not found")

def ensure_profiles_file():
    os.makedirs(MC_DIR, exist_ok=True)
    pj = os.path.join(MC_DIR, "launcher_profiles.json")
    if not os.path.exists(pj):
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"profiles": {}, "version": 3}, f)

def run_installer(url, loader, expected_id, mc, log):
    java = find_java(log, need_java(mc))
    ensure_profiles_file()
    tmp = tempfile.mkdtemp()
    jar = os.path.join(tmp, "installer.jar")
    log(T("log_dl", LN[loader]))
    with http_get(url) as r, open(jar, "wb") as o:
        shutil.copyfileobj(r, o)
    vdir = os.path.join(MC_DIR, "versions")
    before = set(sub_dirs(vdir))
    p = subprocess.run([java, "-jar", jar, "--installClient", MC_DIR], capture_output=True, text=True,
                       timeout=1500, creationflags=NOWIN, cwd=tmp, errors="ignore")
    if p.returncode != 0:
        raise RuntimeError(T("err_loader", LN[loader]) + "\n\n" + ((p.stdout or "") + (p.stderr or ""))[-300:])
    new = [v for v in sub_dirs(vdir) if v not in before and loader_from_text(v) == loader]
    if new:
        return new[0]
    if os.path.isdir(os.path.join(vdir, expected_id)):
        return expected_id
    raise RuntimeError(T("err_loader", LN[loader]))

def install_loader_dotmc(loader, mc, log):
    """Ставит загрузчик в .minecraft, возвращает id версии."""
    log(T("log_loader", LN[loader]))
    if loader == "fabric":
        lv = fabric_version(mc)
        prof = jget("https://meta.fabricmc.net/v2/versions/loader/%s/%s/profile/json" % (mc, lv))
        vid = prof["id"]
        d = os.path.join(MC_DIR, "versions", vid)
        os.makedirs(d, exist_ok=True)
        ensure_profiles_file()
        with open(os.path.join(d, vid + ".json"), "w", encoding="utf-8") as f:
            json.dump(prof, f)
    elif loader == "forge":
        v = forge_version(mc)
        url = "https://maven.minecraftforge.net/net/minecraftforge/forge/%s-%s/forge-%s-%s-installer.jar" % (mc, v, mc, v)
        vid = run_installer(url, loader, "%s-forge-%s" % (mc, v), mc, log)
    else:
        v = neoforge_version(mc)
        url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/%s/neoforge-%s-installer.jar" % (v, v)
        vid = run_installer(url, loader, "neoforge-%s" % v, mc, log)
    log(T("log_loader_ok", LN[loader]))
    return vid

def create_prism_instance(root, loader, mc, log):
    log(T("log_prism"))
    uid = {"forge": "net.minecraftforge", "neoforge": "net.neoforged", "fabric": "net.fabricmc.fabric-loader"}[loader]
    lv = {"forge": forge_version, "neoforge": neoforge_version, "fabric": fabric_version}[loader](mc)
    base = os.path.join(root, "instances", SERVER_NAME)
    n = 2
    while os.path.exists(base):
        base = os.path.join(root, "instances", "%s %d" % (SERVER_NAME, n))
        n += 1
    os.makedirs(os.path.join(base, "minecraft", "mods"))
    with open(os.path.join(base, "mmc-pack.json"), "w", encoding="utf-8") as f:
        json.dump({"formatVersion": 1, "components": [
            {"uid": "net.minecraft", "version": mc, "important": True},
            {"uid": uid, "version": lv}]}, f, indent=2)
    with open(os.path.join(base, "instance.cfg"), "w", encoding="utf-8") as f:
        f.write("InstanceType=OneSix\nname=%s\n" % os.path.basename(base))
    log(T("log_loader_ok", LN[loader]))
    return os.path.join(base, "minecraft")

def create_build(kind, root, loader, mc, log):
    """Создаёт новую сборку. kind: 'dot' (.minecraft) или 'prism'. -> папка игры."""
    if kind == "prism":
        return create_prism_instance(root, loader, mc, log)
    vid = install_loader_dotmc(loader, mc, log)
    g = create_new_build(vid)
    log(T("log_newbuild", g))
    return g

# ---------- ЯЗЫКИ ----------
# Чтобы добавить язык: скопируй любой блок в STR, переведи, и добавь строчку в LANGS.
LANGS = [("ru", "RU"), ("en", "EN"), ("uk", "UK")]
CUR = {"lang": "en"}

STR = {
"ru": {
 "w_h": "Привет! 👋",
 "w_t": "Я помогу тебе зайти на сервер «{0}».\nЯ всё сделаю сам — тебе нужно только нажимать кнопки.",
 "w1": "🔎   Найду твой Minecraft", "w2": "🎙   Поставлю голосовой чат", "w3": "🌐   Добавлю сервер в игру",
 "start": "Поехали!  ▶", "next": "Дальше  ▶", "back": "◀  Назад",
 "s1": "Лаунчер", "s2": "Сборка", "s3": "Установка", "s4": "Готово",
 "l_h": "Где ты играешь в Minecraft?",
 "l_t": "Лаунчер — это программа, из которой ты запускаешь игру. Вот те, что я нашёл. Выбери свой и нажми «Дальше».",
 "l_none_t": "Я не нашёл ни одного лаунчера 😕\nСкачай любой из списка, поставь его, создай в нём сборку с Forge — и нажми «Проверить снова».",
 "recheck": "🔄  Проверить снова", "manual": "📁  Найти папку самому",
 "dl_official": "Официальный Minecraft Launcher",
 "dl_started": "Скачиваю... Когда откроется установщик — поставь лаунчер.",
 "dl_open": "Открыл сайт в браузере. Скачай и поставь лаунчер.",
 "b_h": "Какую сборку используем?",
 "b_t": "Сборка — это твой Minecraft с модами. Выбери ту, в которой будешь играть на сервере.",
 "b_none_t": "В этом лаунчере нет сборок с модами 😕\nСоздай в нём сборку с Forge (или Fabric) — и нажми «Проверить снова».",
 "c_h": "Всё готово! Нажми «Установить»",
 "c_t": "Я поставлю голосовой чат и добавлю сервер. Твои миры и сохранения не пострадают.",
 "sum_l": "Лаунчер", "sum_b": "Сборка", "sum_s": "Сервер",
 "install": "✨  Установить",
 "ing_h": "Устанавливаю...", "ing_t": "Подожди немного и не закрывай окно.",
 "done_h": "Готово! 🎉",
 "done_t": "Теперь сделай так:\n\n1.   Запусти свою сборку в лаунчере\n2.   Нажми «Сетевая игра»\n3.   Выбери «{0}» и заходи!\n\n🎙   В игре нажми кнопку V — откроются настройки микрофона.",
 "close": "Закрыть",
 "err_h": "Ой, что-то пошло не так 😢", "retry": "Попробовать снова",
 "err_net": "Нет интернета или сайт не отвечает. Проверь подключение и попробуй ещё раз.",
 "err_nomod": "Для {0} {1} голосового чата нет. Нужна сборка другой версии.",
 "ex_title": "В сборке уже есть моды",
 "ex_text3": "В этой сборке уже есть моды. Добавить голосовой чат к ним?\n\nДа — добавить сюда\nНет — сделать новую отдельную сборку\nОтмена — вернуться назад",
 "ex_text2": "В этой сборке уже есть моды. Добавить голосовой чат к ним?",
 "ask_ver": "Не смог узнать версию Minecraft этой сборки.\nНапиши её (например 1.20.1):",
 "ask_loader": "Не смог узнать загрузчик.\nНапиши: forge, neoforge, fabric или quilt",
 "need_data": "Без версии и загрузчика я не смогу поставить мод.",
 "pick_dir": "Выбери папку лаунчера или сборки",
 "manual_group": "Выбрано вручную", "n_builds": "сборок: {0}",
 "log_search": "Ищу голосовой чат для {0} {1}...", "log_removed": "Убрал старую версию: {0}",
 "log_exists": "Уже скачано: {0}", "log_dl": "Скачиваю {0}...", "log_dep": "Скачиваю нужное дополнение...",
 "log_modok": "Голосовой чат установлен ✔", "log_srv_ok": "Сервер добавлен в игру ✔",
 "log_srv_have": "Сервер уже был в списке ✔", "log_newbuild": "Создал новую сборку: {0}",
},
"en": {
 "w_h": "Hi! 👋",
 "w_t": "I'll help you join the \"{0}\" server.\nI'll do everything myself — you only need to press buttons.",
 "w1": "🔎   Find your Minecraft", "w2": "🎙   Install voice chat", "w3": "🌐   Add the server to the game",
 "start": "Let's go!  ▶", "next": "Next  ▶", "back": "◀  Back",
 "s1": "Launcher", "s2": "Build", "s3": "Install", "s4": "Done",
 "l_h": "Where do you play Minecraft?",
 "l_t": "A launcher is the program you start the game from. Here's what I found. Pick yours and press Next.",
 "l_none_t": "I couldn't find any launcher 😕\nDownload one from the list, install it, create a Forge build in it — then press \"Check again\".",
 "recheck": "🔄  Check again", "manual": "📁  Find the folder myself",
 "dl_official": "Official Minecraft Launcher",
 "dl_started": "Downloading... When the installer opens, install the launcher.",
 "dl_open": "Opened the website in your browser. Download and install the launcher.",
 "b_h": "Which build should we use?",
 "b_t": "A build is your Minecraft with mods. Pick the one you'll play on the server with.",
 "b_none_t": "This launcher has no modded builds 😕\nCreate a Forge (or Fabric) build in it — then press \"Check again\".",
 "c_h": "All set! Press \"Install\"",
 "c_t": "I'll install voice chat and add the server. Your worlds and saves stay safe.",
 "sum_l": "Launcher", "sum_b": "Build", "sum_s": "Server",
 "install": "✨  Install",
 "ing_h": "Installing...", "ing_t": "Please wait and don't close the window.",
 "done_h": "Done! 🎉",
 "done_t": "Now do this:\n\n1.   Start your build in the launcher\n2.   Click \"Multiplayer\"\n3.   Pick \"{0}\" and join!\n\n🎙   In the game press V — the microphone settings will open.",
 "close": "Close",
 "err_h": "Oops, something went wrong 😢", "retry": "Try again",
 "err_net": "No internet or the website isn't responding. Check your connection and try again.",
 "err_nomod": "There is no voice chat for {0} {1}. You need a build of another version.",
 "ex_title": "This build already has mods",
 "ex_text3": "This build already has mods. Add voice chat to them?\n\nYes — add it here\nNo — make a new separate build\nCancel — go back",
 "ex_text2": "This build already has mods. Add voice chat to them?",
 "ask_ver": "I couldn't find this build's Minecraft version.\nType it (for example 1.20.1):",
 "ask_loader": "I couldn't find the loader.\nType: forge, neoforge, fabric or quilt",
 "need_data": "I can't install the mod without the version and loader.",
 "pick_dir": "Choose the launcher or build folder",
 "manual_group": "Chosen manually", "n_builds": "builds: {0}",
 "log_search": "Looking for voice chat for {0} {1}...", "log_removed": "Removed the old version: {0}",
 "log_exists": "Already downloaded: {0}", "log_dl": "Downloading {0}...", "log_dep": "Downloading a required add-on...",
 "log_modok": "Voice chat installed ✔", "log_srv_ok": "Server added to the game ✔",
 "log_srv_have": "Server was already in the list ✔", "log_newbuild": "Created a new build: {0}",
},
"uk": {
 "w_h": "Привіт! 👋",
 "w_t": "Я допоможу тобі зайти на сервер «{0}».\nЯ все зроблю сам — тобі треба лише натискати кнопки.",
 "w1": "🔎   Знайду твій Minecraft", "w2": "🎙   Поставлю голосовий чат", "w3": "🌐   Додам сервер у гру",
 "start": "Поїхали!  ▶", "next": "Далі  ▶", "back": "◀  Назад",
 "s1": "Лаунчер", "s2": "Збірка", "s3": "Установка", "s4": "Готово",
 "l_h": "Де ти граєш у Minecraft?",
 "l_t": "Лаунчер — це програма, з якої ти запускаєш гру. Ось ті, що я знайшов. Обери свій і натисни «Далі».",
 "l_none_t": "Я не знайшов жодного лаунчера 😕\nЗавантаж будь-який зі списку, встанови його, створи в ньому збірку з Forge — і натисни «Перевірити знову».",
 "recheck": "🔄  Перевірити знову", "manual": "📁  Знайти папку самому",
 "dl_official": "Офіційний Minecraft Launcher",
 "dl_started": "Завантажую... Коли відкриється установник — встанови лаунчер.",
 "dl_open": "Відкрив сайт у браузері. Завантаж і встанови лаунчер.",
 "b_h": "Яку збірку використаємо?",
 "b_t": "Збірка — це твій Minecraft з модами. Обери ту, в якій гратимеш на сервері.",
 "b_none_t": "У цьому лаунчері немає збірок з модами 😕\nСтвори в ньому збірку з Forge (або Fabric) — і натисни «Перевірити знову».",
 "c_h": "Все готово! Натисни «Встановити»",
 "c_t": "Я поставлю голосовий чат і додам сервер. Твої світи та збереження не постраждають.",
 "sum_l": "Лаунчер", "sum_b": "Збірка", "sum_s": "Сервер",
 "install": "✨  Встановити",
 "ing_h": "Встановлюю...", "ing_t": "Зачекай трохи і не закривай вікно.",
 "done_h": "Готово! 🎉",
 "done_t": "Тепер зроби так:\n\n1.   Запусти свою збірку в лаунчері\n2.   Натисни «Мережева гра»\n3.   Обери «{0}» і заходь!\n\n🎙   У грі натисни кнопку V — відкриються налаштування мікрофона.",
 "close": "Закрити",
 "err_h": "Ой, щось пішло не так 😢", "retry": "Спробувати знову",
 "err_net": "Немає інтернету або сайт не відповідає. Перевір підключення і спробуй ще раз.",
 "err_nomod": "Для {0} {1} голосового чату немає. Потрібна збірка іншої версії.",
 "ex_title": "У збірці вже є моди",
 "ex_text3": "У цій збірці вже є моди. Додати голосовий чат до них?\n\nТак — додати сюди\nНі — зробити нову окрему збірку\nСкасувати — повернутися назад",
 "ex_text2": "У цій збірці вже є моди. Додати голосовий чат до них?",
 "ask_ver": "Не зміг дізнатися версію Minecraft цієї збірки.\nНапиши її (наприклад 1.20.1):",
 "ask_loader": "Не зміг дізнатися завантажувач.\nНапиши: forge, neoforge, fabric або quilt",
 "need_data": "Без версії та завантажувача я не зможу поставити мод.",
 "pick_dir": "Обери папку лаунчера або збірки",
 "manual_group": "Обрано вручну", "n_builds": "збірок: {0}",
 "log_search": "Шукаю голосовий чат для {0} {1}...", "log_removed": "Прибрав стару версію: {0}",
 "log_exists": "Вже завантажено: {0}", "log_dl": "Завантажую {0}...", "log_dep": "Завантажую потрібне доповнення...",
 "log_modok": "Голосовий чат встановлено ✔", "log_srv_ok": "Сервер додано в гру ✔",
 "log_srv_have": "Сервер вже був у списку ✔", "log_newbuild": "Створив нову збірку: {0}",
},
}

EXTRA = {'ru': {'new_build': '➕  Создать новую сборку', 'b_none_t': 'В этом лаунчере пока нет сборок с модами 😕\nНичего страшного — я могу создать её сам! Нажми «Создать новую сборку».', 'b_none_nc': 'В этом лаунчере нет сборок с модами 😕\nСоздай сборку с Forge или Fabric прямо в лаунчере и нажми «Проверить снова». Или вернись и выбери другой лаунчер.', 'nl_h': 'Выбери «движок» для модов', 'nl_t': 'Это программа, благодаря которой в игре работают моды. Не знаешь, что выбрать — бери Fabric.', 'd_fabric': '⭐  Рекомендуем, если не знаешь, что выбрать\n\n👍  Плюсы\n•  Самый лёгкий и быстрый\n•  Игра запускается быстрее\n•  Новые версии появляются первыми\n•  Не нужно ставить Java\n\n👎  Минусы\n•  Некоторых больших старых модов нет', 'd_forge': '👍  Плюсы\n•  Больше всего модов в мире\n•  Подходит для больших сборок (магия, техника)\n•  Много гайдов и подсказок\n\n👎  Минусы\n•  Игра грузится дольше\n•  Установка дольше (Java я скачаю сам, если её нет)', 'd_neoforge': '👍  Плюсы\n•  Современная ветка Forge\n•  Активно развивается\n•  Хорош для новых версий игры\n\n👎  Минусы\n•  Модов пока меньше, чем у Forge и Fabric\n•  Здесь доступен только для версии 1.21.1', 'nv_h': 'Какую версию игры ставим?', 'nv_t': 'Если не уверен — оставь первую.', 'v_1211': 'новая, свежие моды', 'v_1201': 'самая популярная для модов', 'sum_new': 'Новая сборка «{0}» — {1} {2}', 'ing_t': 'Это может занять несколько минут. Не закрывай окно.', 'ld_official': 'Просто и привычно, от создателей игры. Нужен аккаунт Microsoft с купленной игрой.', 'ld_prism': '⭐ Лучший для модов: легко делает сборки с Forge и Fabric. Бесплатный, без рекламы.', 'ld_modrinth': 'Красивый и удобный: моды и сборки ставятся в один клик.', 'ld_curse': 'Огромный каталог готовых сборок. Немного тяжелее остальных.', 'ld_tl': 'Сторонний лаунчер (не от Mojang). Ставь, только если знаешь, зачем он тебе.', 'log_java': 'Ищу Java...', 'log_java_dl': 'Скачиваю Java (один раз, примерно 50 МБ)...', 'log_loader': 'Устанавливаю {0} (это может занять пару минут)...', 'log_loader_ok': '{0} установлен ✔', 'log_prism': 'Создаю сборку в лаунчере... Если он открыт — перезапусти его.', 'err_loader': 'Не получилось установить {0}. Попробуй другой движок или версию.', 'err_nover': 'Для {0} нет версии под Minecraft {1}. Выбери другую версию.'}, 'en': {'new_build': '➕  Create a new build', 'b_none_t': 'This launcher has no modded builds yet 😕\nNo problem — I can create one for you! Press "Create a new build".', 'b_none_nc': 'This launcher has no modded builds 😕\nCreate a Forge or Fabric build in the launcher itself and press "Check again". Or go back and pick another launcher.', 'nl_h': 'Pick a mod "engine"', 'nl_t': 'This is the program that makes mods work in the game. Not sure? Take Fabric.', 'd_fabric': "⭐  Recommended if you're not sure\n\n👍  Pros\n•  Lightest and fastest\n•  The game starts faster\n•  New versions arrive first\n•  No need to install Java\n\n👎  Cons\n•  Some big old mods are missing", 'd_forge': "👍  Pros\n•  The most mods in the world\n•  Great for big modpacks (magic, tech)\n•  Lots of guides and tips\n\n👎  Cons\n•  The game loads slower\n•  Takes longer to install (I'll download Java if you don't have it)", 'd_neoforge': '👍  Pros\n•  The modern branch of Forge\n•  Actively developed\n•  Good for new game versions\n\n👎  Cons\n•  Fewer mods than Forge and Fabric\n•  Available here only for version 1.21.1', 'nv_h': 'Which game version?', 'nv_t': "If you're not sure, keep the first one.", 'v_1211': 'new, fresh mods', 'v_1201': 'the most popular for mods', 'sum_new': 'New build "{0}" — {1} {2}', 'ing_t': "This can take a few minutes. Don't close the window.", 'ld_official': "Simple and familiar, from the game's makers. Needs a Microsoft account that owns the game.", 'ld_prism': '⭐ Best for mods: easily makes Forge and Fabric builds. Free, no ads.', 'ld_modrinth': 'Pretty and handy: mods and modpacks install in one click.', 'ld_curse': 'A huge catalog of ready modpacks. A bit heavier than the others.', 'ld_tl': 'Third-party launcher (not from Mojang). Install it only if you know why you need it.', 'log_java': 'Looking for Java...', 'log_java_dl': 'Downloading Java (one time, about 50 MB)...', 'log_loader': 'Installing {0} (this can take a couple of minutes)...', 'log_loader_ok': '{0} installed ✔', 'log_prism': "Creating the build in the launcher... If it's open, restart it.", 'err_loader': "Couldn't install {0}. Try another engine or version.", 'err_nover': '{0} has no version for Minecraft {1}. Pick another version.'}, 'uk': {'new_build': '➕  Створити нову збірку', 'b_none_t': 'У цьому лаунчері поки немає збірок з модами 😕\nНічого страшного — я можу створити її сам! Натисни «Створити нову збірку».', 'b_none_nc': 'У цьому лаунчері немає збірок з модами 😕\nСтвори збірку з Forge або Fabric прямо в лаунчері і натисни «Перевірити знову». Або повернись і обери інший лаунчер.', 'nl_h': 'Обери «рушій» для модів', 'nl_t': 'Це програма, завдяки якій у грі працюють моди. Не знаєш, що обрати — бери Fabric.', 'd_fabric': "⭐  Рекомендуємо, якщо не знаєш, що обрати\n\n👍  Плюси\n•  Найлегший і найшвидший\n•  Гра запускається швидше\n•  Нові версії з'являються першими\n•  Не треба ставити Java\n\n👎  Мінуси\n•  Деяких великих старих модів немає", 'd_forge': '👍  Плюси\n•  Найбільше модів у світі\n•  Підходить для великих збірок (магія, техніка)\n•  Багато гайдів і підказок\n\n👎  Мінуси\n•  Гра вантажиться довше\n•  Установка довша (Java я завантажу сам, якщо її немає)', 'd_neoforge': '👍  Плюси\n•  Сучасна гілка Forge\n•  Активно розвивається\n•  Добрий для нових версій гри\n\n👎  Мінуси\n•  Модів поки менше, ніж у Forge і Fabric\n•  Тут доступний лише для версії 1.21.1', 'nv_h': 'Яку версію гри ставимо?', 'nv_t': 'Якщо не впевнений — залиш першу.', 'v_1211': 'нова, свіжі моди', 'v_1201': 'найпопулярніша для модів', 'sum_new': 'Нова збірка «{0}» — {1} {2}', 'ing_t': 'Це може тривати кілька хвилин. Не закривай вікно.', 'ld_official': 'Просто і звично, від творців гри. Потрібен акаунт Microsoft з купленою грою.', 'ld_prism': '⭐ Найкращий для модів: легко робить збірки з Forge і Fabric. Безкоштовний, без реклами.', 'ld_modrinth': 'Гарний і зручний: моди та збірки ставляться в один клік.', 'ld_curse': 'Величезний каталог готових збірок. Трохи важчий за інші.', 'ld_tl': 'Сторонній лаунчер (не від Mojang). Став, лише якщо знаєш, навіщо він тобі.', 'log_java': 'Шукаю Java...', 'log_java_dl': 'Завантажую Java (один раз, приблизно 50 МБ)...', 'log_loader': 'Встановлюю {0} (це може тривати пару хвилин)...', 'log_loader_ok': '{0} встановлено ✔', 'log_prism': 'Створюю збірку в лаунчері... Якщо він відкритий — перезапусти його.', 'err_loader': 'Не вийшло встановити {0}. Спробуй інший рушій або версію.', 'err_nover': 'Для {0} немає версії під Minecraft {1}. Обери іншу версію.'}}
for _l, _d in EXTRA.items():
    STR[_l].update(_d)

EXTRA2 = {'ru': {'v_latest': 'самая новая версия игры', 'v_12111': 'проверенная, много модов', 'nv_t': 'Первая — самая свежая. Вторая — для тех, кому важны проверенные моды.', 'd_forge': '👍  Плюсы\n•  Больше всего модов в мире\n•  Подходит для больших сборок (магия, техника)\n•  Много гайдов и подсказок\n\n👎  Минусы\n•  Игра грузится дольше\n•  Установка дольше (Java я скачаю сам, если её нет)\n•  Для самых новых версий игры может ещё не быть', 'd_neoforge': '👍  Плюсы\n•  Современная ветка Forge\n•  Активно развивается\n•  Хорош для новых версий игры\n\n👎  Минусы\n•  Модов пока меньше, чем у Forge и Fabric\n•  Для самых новых версий бывает ещё в тестовой стадии'}, 'en': {'v_latest': 'the newest game version', 'v_12111': 'proven, lots of mods', 'nv_t': 'The first one is the freshest. The second is for those who want proven mods.', 'd_forge': "👍  Pros\n•  The most mods in the world\n•  Great for big modpacks (magic, tech)\n•  Lots of guides and tips\n\n👎  Cons\n•  The game loads slower\n•  Takes longer to install (I'll download Java if you don't have it)\n•  May not exist yet for the very newest game versions", 'd_neoforge': '👍  Pros\n•  The modern branch of Forge\n•  Actively developed\n•  Good for new game versions\n\n👎  Cons\n•  Fewer mods than Forge and Fabric\n•  Sometimes still in testing for the very newest versions'}, 'uk': {'v_latest': 'найновіша версія гри', 'v_12111': 'перевірена, багато модів', 'nv_t': 'Перша — найсвіжіша. Друга — для тих, кому важливі перевірені моди.', 'd_forge': '👍  Плюси\n•  Найбільше модів у світі\n•  Підходить для великих збірок (магія, техніка)\n•  Багато гайдів і підказок\n\n👎  Мінуси\n•  Гра вантажиться довше\n•  Установка довша (Java я завантажу сам, якщо її немає)\n•  Для найновіших версій гри може ще не бути', 'd_neoforge': '👍  Плюси\n•  Сучасна гілка Forge\n•  Активно розвивається\n•  Добрий для нових версій гри\n\n👎  Мінуси\n•  Модів поки менше, ніж у Forge і Fabric\n•  Для найновіших версій буває ще в тестовій стадії'}}
for _l, _d in EXTRA2.items():
    STR[_l].update(_d)

def T(key, *a):
    s = STR.get(CUR["lang"], {}).get(key) or STR["en"].get(key) or key
    return s.format(*a) if a else s

def system_lang():
    try:
        import ctypes
        pl = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return {0x19: "ru", 0x22: "uk"}.get(pl, "en")
    except Exception:
        return "en"

LOGO_B64 = "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"

# ---------- ОКНО ----------
BG, CARD, CARD2 = "#0f0f11", "#1b1b20", "#2a2a31"
ACC, ACC2 = "#FCC145", "#ffd36e"
FG, MUTED, GOOD, BAD = "#f5f5f5", "#9a9aa3", "#5fd38d", "#ff7b7b"
FONT = "Segoe UI"

class Btn(tk.Label):
    """Большая плоская кнопка."""
    def __init__(self, parent, text, cmd, primary=True, size=13, width=None):
        self.cmd, self.on = cmd, True
        self.c1, self.c2 = (ACC, ACC2) if primary else (CARD2, "#3a3a44")
        self.fg = "#111111" if primary else FG
        super().__init__(parent, text=text, bg=self.c1, fg=self.fg, cursor="hand2",
                         font=(FONT, size, "bold"), padx=22, pady=10, **({"width": width} if width else {}))
        self.bind("<Enter>", lambda e: self.on and self.config(bg=self.c2))
        self.bind("<Leave>", lambda e: self.on and self.config(bg=self.c1))
        self.bind("<Button-1>", lambda e: self.on and self.cmd())
    def enable(self, flag):
        self.on = flag
        self.config(bg=self.c1 if flag else CARD, fg=self.fg if flag else MUTED,
                    cursor="hand2" if flag else "arrow")

class App:
    def __init__(self, root):
        self.root = root
        CUR["lang"] = system_lang()
        root.title(SERVER_NAME)
        root.geometry("820x660")
        root.minsize(760, 600)
        root.configure(bg=BG)
        self.logo = tk.PhotoImage(data=LOGO_B64)
        try:
            root.iconphoto(True, self.logo)
        except Exception:
            pass
        self.small = self.logo.subsample(4)
        self.mid = self.logo.subsample(2)
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Y.Horizontal.TProgressbar", troughcolor=CARD, background=ACC,
                     bordercolor=BG, lightcolor=ACC, darkcolor=ACC)
        # шапка
        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=28, pady=(16, 0))
        tk.Label(top, image=self.small, bg=BG).pack(side="left")
        tk.Label(top, text=SERVER_NAME, bg=BG, fg=ACC, font=(FONT, 20, "bold")).pack(side="left", padx=12)
        self.langbox = tk.Frame(top, bg=BG)
        self.langbox.pack(side="right")
        self.steps = tk.Canvas(root, height=74, bg=BG, highlightthickness=0)
        self.body = tk.Frame(root, bg=BG)
        self.footer = tk.Frame(root, bg=BG)
        self.footer.pack(side="bottom", fill="x", padx=32, pady=(0, 22))
        self.body.pack(fill="both", expand=True, padx=32, pady=(8, 8))
        self.found, self.keys, self.extra = {}, [], None
        self.sel_l = self.sel_i = None
        self.inst = None
        self.target = None
        self.busy = False
        self.logbox = None
        self.page = "welcome"
        self.show("welcome")

    # --- общие куски ---
    def draw_langs(self):
        for w in self.langbox.winfo_children():
            w.destroy()
        for code, name in LANGS:
            cur = CUR["lang"] == code
            l = tk.Label(self.langbox, text=name, bg=ACC if cur else CARD2, fg="#111" if cur else FG,
                         font=(FONT, 10, "bold"), padx=10, pady=4, cursor="hand2")
            l.pack(side="left", padx=3)
            l.bind("<Button-1>", lambda e, c=code: self.set_lang(c))

    def set_lang(self, code):
        if self.busy:
            return
        CUR["lang"] = code
        self.show(self.page)

    def draw_steps(self, n):
        if n == 0:
            self.steps.pack_forget()
            return
        self.steps.pack(fill="x", padx=28, before=self.body)
        c = self.steps
        c.delete("all")
        w = 764
        xs = [w * (i + 0.5) / 4 for i in range(4)]
        for i in range(3):
            c.create_line(xs[i] + 20, 22, xs[i + 1] - 20, 22, fill=ACC if i + 1 < n else CARD2, width=3)
        for i, x in enumerate(xs):
            k = i + 1
            if k < n:
                c.create_oval(x - 16, 6, x + 16, 38, fill=ACC, outline=ACC)
                c.create_text(x, 22, text="✓", fill="#111", font=(FONT, 13, "bold"))
            elif k == n:
                c.create_oval(x - 16, 6, x + 16, 38, fill=ACC, outline=ACC2, width=2)
                c.create_text(x, 22, text=str(k), fill="#111", font=(FONT, 13, "bold"))
            else:
                c.create_oval(x - 16, 6, x + 16, 38, fill=BG, outline=CARD2, width=2)
                c.create_text(x, 22, text=str(k), fill=MUTED, font=(FONT, 12, "bold"))
            c.create_text(x, 56, text=T("s%d" % k), fill=FG if k <= n else MUTED, font=(FONT, 10, "bold"))

    def H(self, text):
        tk.Label(self.body, text=text, bg=BG, fg=FG, font=(FONT, 22, "bold"),
                 anchor="w", justify="left", wraplength=740).pack(fill="x", pady=(6, 4))

    def P(self, text, color=MUTED, size=12):
        l = tk.Label(self.body, text=text, bg=BG, fg=color, font=(FONT, size),
                     anchor="w", justify="left", wraplength=740)
        l.pack(fill="x", pady=(0, 8))
        return l

    def listbox(self, items, on_pick):
        fr = tk.Frame(self.body, bg=BG)
        fr.pack(fill="both", expand=True, pady=4)
        sb = tk.Scrollbar(fr)
        lb = tk.Listbox(fr, font=(FONT, 14), bg=CARD, fg=FG, selectbackground=ACC, selectforeground="#111",
                        highlightthickness=0, bd=0, activestyle="none", exportselection=False,
                        yscrollcommand=sb.set)
        sb.config(command=lb.yview)
        for it in items:
            lb.insert("end", "   " + it)
        lb.pack(side="left", fill="both", expand=True, ipady=6)
        if len(items) > 8:
            sb.pack(side="right", fill="y")
        lb.bind("<<ListboxSelect>>", lambda e: on_pick(lb.curselection()[0] if lb.curselection() else None))
        if items:
            lb.selection_set(0)
            lb.focus_set()
            on_pick(0)
        return lb

    def show(self, page):
        self.page = page
        self.logbox = None
        for w in self.body.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()
        self.draw_langs()
        self.draw_steps({"welcome": 0, "launcher": 1, "build": 2, "newl": 2, "newv": 2, "confirm": 3, "install": 3, "error": 3, "done": 4}[page])
        getattr(self, "page_" + page)()

    def foot(self, back=None, extra=(), nxt=None, nxt_text=None):
        if back:
            Btn(self.footer, T("back"), back, primary=False).pack(side="left")
        for text, cmd in extra:
            Btn(self.footer, text, cmd, primary=False, size=11).pack(side="left", padx=8)
        b = None
        if nxt:
            b = Btn(self.footer, nxt_text or T("next"), nxt)
            b.pack(side="right")
        return b

    # --- страницы ---
    def page_welcome(self):
        tk.Label(self.body, image=self.mid, bg=BG).pack(pady=(6, 0))
        self.H(T("w_h"))
        self.P(T("w_t", SERVER_NAME), FG, 14)
        card = tk.Frame(self.body, bg=CARD)
        card.pack(fill="x", pady=10)
        for k in ("w1", "w2", "w3"):
            tk.Label(card, text=T(k), bg=CARD, fg=FG, font=(FONT, 14), anchor="w").pack(fill="x", padx=20, pady=7)
        self.foot(nxt=lambda: self.go_launcher(), nxt_text=T("start"))

    def go_launcher(self):
        self.refresh()
        self.show("launcher")

    def refresh(self):
        self.found = find_launchers()
        if self.extra:
            self.found["__manual__"] = self.extra
        self.keys = list(self.found)

    def lname(self, k):
        return T("manual_group") if k == "__manual__" else k

    def recheck(self):
        self.refresh()
        self.show(self.page)

    def pick_manual(self):
        d = filedialog.askdirectory(title=T("pick_dir"))
        if not d:
            return
        self.extra = scan_folder(d)
        self.refresh()
        self.sel_l = len(self.keys) - 1
        self.show("build")

    def page_launcher(self):
        self.H(T("l_h"))
        self.status = None
        if not self.keys:
            self.P(T("l_none_t"), FG, 13)
            links = [("dl_official", None, "ld_official"), ("Prism Launcher", "https://prismlauncher.org/download/", "ld_prism"),
                     ("Modrinth App", "https://modrinth.com/app", "ld_modrinth"),
                     ("CurseForge", "https://www.curseforge.com/download/app", "ld_curse"),
                     ("TLauncher", "https://tlauncher.org/", "ld_tl")]
            for lab, url, dk in links:
                r = tk.Frame(self.body, bg=BG)
                r.pack(fill="x", pady=4)
                Btn(r, "⬇  " + (T(lab) if lab == "dl_official" else lab), lambda u=url: self.download(u),
                    primary=False, size=11, width=24).pack(side="left")
                tk.Label(r, text=T(dk), bg=BG, fg=MUTED, font=(FONT, 11), anchor="w", justify="left",
                         wraplength=430).pack(side="left", padx=12, fill="x", expand=True)
            self.status = self.P("", ACC)
            self.foot(back=lambda: self.show("welcome"),
                      extra=[(T("recheck"), self.recheck), (T("manual"), self.pick_manual)])
            return
        self.P(T("l_t"))
        names = ["%s   —   %s" % (self.lname(k), T("n_builds", len(self.found[k]))) for k in self.keys]
        nb = self.foot(back=lambda: self.show("welcome"),
                       extra=[(T("recheck"), self.recheck), (T("manual"), self.pick_manual)],
                       nxt=lambda: self.show("build"))
        def pick(i):
            self.sel_l = i
            nb.enable(i is not None)
        self.listbox(names, pick)

    def download(self, url):
        if url:
            webbrowser.open(url)
            self.status.config(text=T("dl_open"))
            return
        self.status.config(text=T("dl_started"))
        def work():
            try:
                p = os.path.join(tempfile.gettempdir(), "MinecraftInstaller.exe")
                with http_get(LAUNCHER_URL) as r, open(p, "wb") as o:
                    shutil.copyfileobj(r, o)
                os.startfile(p)
            except Exception:
                self.root.after(0, lambda: self.status.config(text=T("err_net"), fg=BAD))
        threading.Thread(target=work, daemon=True).start()

    def page_build(self):
        if self.sel_l is None or self.sel_l >= len(self.keys):
            return self.show("launcher")
        self.cur = self.found[self.keys[self.sel_l]]
        self.H(T("b_h"))
        can = self.creator() is not None
        if not self.cur:
            self.P(T("b_none_t") if can else T("b_none_nc"), FG, 13)
            ex = [(T("recheck"), self.recheck)]
            if can:
                self.foot(back=lambda: self.show("launcher"), extra=ex, nxt=self.new_flow, nxt_text=T("new_build"))
            else:
                self.foot(back=lambda: self.show("launcher"), extra=ex)
            return
        self.P(T("b_t"))
        labels = ["%s   [%s %s]" % (b["name"], (b["loader"] or "?").capitalize(), b["mc"] or "?") for b in self.cur]
        ex = ([(T("new_build"), self.new_flow)] if can else []) + [(T("recheck"), self.recheck)]
        nb = self.foot(back=lambda: self.show("launcher"), extra=ex, nxt=self.build_next)
        def pick(i):
            self.sel_i = i
            nb.enable(i is not None)
        self.listbox(labels, pick)

    def creator(self):
        k = self.keys[self.sel_l]
        if k == MC_GROUP:
            return ("dot", None)
        roots = {"Prism Launcher": "PrismLauncher", "PolyMC": "PolyMC", "MultiMC": "MultiMC"}
        if k in roots:
            return ("prism", os.path.join(APPDATA, roots[k]))
        return None

    def new_flow(self):
        self.new_loader = "fabric"
        self.show("newl")

    def page_newl(self):
        self.H(T("nl_h"))
        self.P(T("nl_t"))
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="both", expand=True, pady=4)
        items = ["fabric", "forge", "neoforge"]
        lb = tk.Listbox(row, font=(FONT, 16, "bold"), bg=CARD, fg=FG, selectbackground=ACC, selectforeground="#111",
                        highlightthickness=0, bd=0, activestyle="none", exportselection=False, width=12, height=3)
        for it in items:
            lb.insert("end", "   " + LN[it] + ("  ⭐" if it == "fabric" else ""))
        lb.pack(side="left", fill="y", ipady=8)
        card = tk.Label(row, bg=CARD, fg=FG, font=(FONT, 12), anchor="nw", justify="left",
                        wraplength=440, padx=18, pady=14)
        card.pack(side="left", fill="both", expand=True, padx=(14, 0))
        def pick(e=None):
            s = lb.curselection()
            i = s[0] if s else items.index(self.new_loader)
            self.new_loader = items[i]
            card.config(text=T("d_" + items[i]))
        lb.bind("<<ListboxSelect>>", pick)
        lb.selection_set(items.index(self.new_loader))
        pick()
        self.foot(back=lambda: self.show("build"), nxt=lambda: self.show("newv"))

    def page_newv(self):
        self.H(T("nv_h"))
        self.P(T("nv_t"))
        lat = latest_mc()
        vs = [(lat, "v_latest")] + ([("1.21.11", "v_12111")] if lat != "1.21.11" else [])
        self.new_mc = vs[0][0]
        nb = self.foot(back=lambda: self.show("newl"), nxt=self.make_new)
        def pick(i):
            if i is not None:
                self.new_mc = vs[i][0]
        self.listbox(["%s   —   %s" % (v, T(k)) for v, k in vs], pick)

    def make_new(self):
        kind, root = self.creator()
        self.inst = {"create": True, "kind": kind, "root": root, "loader": self.new_loader, "mc": self.new_mc,
                     "name": SERVER_NAME, "game_dir": None, "vid": None, "dotmc": False}
        self.show("confirm")

    def build_next(self):
        b = dict(self.cur[self.sel_i])
        if not b["mc"]:
            b["mc"] = (simpledialog.askstring(SERVER_NAME, T("ask_ver"), parent=self.root) or "").strip()
        if not b["loader"]:
            b["loader"] = (simpledialog.askstring(SERVER_NAME, T("ask_loader"), parent=self.root) or "").strip().lower()
        if not b["mc"] or b["loader"] not in LOADERS:
            return messagebox.showwarning(SERVER_NAME, T("need_data"), parent=self.root)
        self.inst = b
        self.show("confirm")

    def page_confirm(self):
        b = self.inst
        self.H(T("c_h"))
        self.P(T("c_t"))
        card = tk.Frame(self.body, bg=CARD)
        card.pack(fill="x", pady=8)
        rows = [(T("sum_l"), self.lname(self.keys[self.sel_l])),
                (T("sum_b"), T("sum_new", SERVER_NAME, LN[b["loader"]], b["mc"]) if b.get("create")
                 else "%s  [%s %s]" % (b["name"], b["loader"].capitalize(), b["mc"])),
                (T("sum_s"), "%s — %s" % (SERVER_NAME, SERVER_IP))]
        for k, v in rows:
            r = tk.Frame(card, bg=CARD)
            r.pack(fill="x", padx=20, pady=8)
            tk.Label(r, text=k, bg=CARD, fg=MUTED, font=(FONT, 11), width=10, anchor="w").pack(side="left")
            tk.Label(r, text=v, bg=CARD, fg=FG, font=(FONT, 13, "bold"), anchor="w",
                     justify="left", wraplength=560).pack(side="left", fill="x")
        self.foot(back=lambda: self.show("newv" if b.get("create") else "build"), nxt=self.start_install, nxt_text=T("install"))

    def start_install(self):
        b = self.inst
        self.target = b["game_dir"]
        if b.get("create"):
            return self.show("install")
        mods = os.path.join(self.target, "mods")
        if os.path.isdir(mods) and any(f.endswith(".jar") for f in os.listdir(mods)):
            if b["dotmc"] and b["vid"]:
                ans = messagebox.askyesnocancel(T("ex_title"), T("ex_text3"), parent=self.root)
            else:
                ans = True if messagebox.askokcancel(T("ex_title"), T("ex_text2"), parent=self.root) else None
            if ans is None:
                return
            if ans is False:
                self.target = None
        self.show("install")

    def page_install(self):
        self.H(T("ing_h"))
        self.P(T("ing_t"))
        pb = ttk.Progressbar(self.body, mode="indeterminate", style="Y.Horizontal.TProgressbar")
        pb.pack(fill="x", pady=8, ipady=4)
        pb.start(12)
        self.logbox = tk.Text(self.body, height=9, bg=CARD, fg=FG, font=(FONT, 12), bd=0,
                              highlightthickness=0, padx=14, pady=10, state="disabled")
        self.logbox.pack(fill="both", expand=True, pady=6)
        self.busy = True
        b, target = self.inst, self.target
        def work():
            try:
                if b.get("create"):
                    g = create_build(b["kind"], b["root"], b["loader"], b["mc"], self.log)
                else:
                    g = target or create_new_build(b["vid"])
                    if not target:
                        self.log(T("log_newbuild", g))
                install_voice_chat(g, b["mc"], b["loader"], self.log)
                self.log(T("log_srv_ok") if add_server(g, SERVER_NAME, SERVER_IP) else T("log_srv_have"))
                self.root.after(600, lambda: self.finish(None))
            except urllib.error.URLError:
                self.root.after(0, lambda: self.finish(T("err_net")))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda m=msg: self.finish(m))
        threading.Thread(target=work, daemon=True).start()

    def log(self, s):
        def f():
            if self.logbox is not None:
                self.logbox.configure(state="normal")
                self.logbox.insert("end", s + "\n")
                self.logbox.see("end")
                self.logbox.configure(state="disabled")
        self.root.after(0, f)

    def finish(self, err):
        self.busy = False
        self.err = err
        self.show("error" if err else "done")

    def page_done(self):
        self.H(T("done_h"))
        card = tk.Frame(self.body, bg=CARD)
        card.pack(fill="x", pady=8)
        tk.Label(card, text=T("done_t", SERVER_NAME), bg=CARD, fg=FG, font=(FONT, 14),
                 anchor="w", justify="left", wraplength=700).pack(fill="x", padx=22, pady=18)
        self.foot(nxt=self.root.destroy, nxt_text=T("close"))

    def page_error(self):
        tk.Label(self.body, text=T("err_h"), bg=BG, fg=BAD, font=(FONT, 22, "bold"), anchor="w").pack(fill="x", pady=6)
        self.P(self.err, FG, 13)
        self.foot(back=lambda: self.show("confirm"), nxt=lambda: self.show("confirm"), nxt_text=T("retry"))

if __name__ == "__main__":
    r = tk.Tk()
    App(r)
    r.mainloop()
