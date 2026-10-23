using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;

namespace SphinxInstaller;

public class Instance
{
    public string Launcher, Name, GameDir, Mc, Loader, Vid;
    public bool DotMc;
    // для «создать новую сборку»
    public bool Create;
    public string Kind, Root;

    public Instance Clone() => (Instance)MemberwiseClone();
}

public class Group
{
    public string Key, Name;
    public List<Instance> Items;
}

/// <summary>Поиск установленных лаунчеров и их сборок.</summary>
public static class Launchers
{
    public static readonly string AppData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
    public static readonly string Home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    public static readonly string McDir = Path.Combine(AppData, ".minecraft");

    public static readonly string[] Loaders = { "neoforge", "forge", "fabric", "quilt" };
    public static readonly Dictionary<string, string> LoaderNames = new()
    {
        ["fabric"] = "Fabric", ["forge"] = "Forge", ["neoforge"] = "NeoForge", ["quilt"] = "Quilt"
    };
    public const string McGroup = "Minecraft Launcher / TLauncher / SKLauncher";
    public const string ManualKey = "__manual__";

    // ---------- утилиты ----------
    public static string LoaderFromText(string s)
    {
        s = (s ?? "").ToLowerInvariant();
        foreach (var l in Loaders) if (s.Contains(l)) return l;
        return null;
    }

    public static string McVersion(string vid)
    {
        var v = (vid ?? "").ToLowerInvariant();
        var m = Regex.Match(v, @"neoforge[-_ ]?(\d+(?:\.\d+)*)");
        if (m.Success)
        {
            var n = m.Groups[1].Value.Split('.');
            if (int.Parse(n[0]) >= 25)   // 26.2.0.57 -> 26.2 ; 26.1.2.78 -> 26.1.2
            {
                if (n.Length < 2) return n[0];
                return n[0] + "." + n[1] + (n.Length < 3 || n[2] == "0" ? "" : "." + n[2]);
            }
            return n.Length < 2 || n[1] == "0" ? "1." + n[0] : "1." + n[0] + "." + n[1];
        }
        m = Regex.Match(v, @"(?<![\d.])((?:1\.\d+|\d{2})\.\d+(?:\.\d+)?|1\.\d+)");
        return m.Success ? m.Groups[1].Value : null;
    }

    static JsonNode ReadJson(string path)
    {
        try { return JsonNode.Parse(File.ReadAllText(path)); }
        catch { return null; }
    }

    static string Str(JsonNode n, string key)
    {
        try { return n?[key] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null; }
        catch { return null; }
    }

    static List<string> SubDirs(string p)
    {
        try
        {
            return Directory.GetDirectories(p).Select(x => Path.GetFileName(x))
                .OrderBy(x => x, StringComparer.OrdinalIgnoreCase).ToList();
        }
        catch { return new List<string>(); }
    }

    static Instance Inst(string launcher, string name, string gameDir, string mc, string loader,
                         string vid = null, bool dotMc = false)
        => new() { Launcher = launcher, Name = name, GameDir = gameDir, Mc = mc, Loader = loader, Vid = vid, DotMc = dotMc };

    // ---------- сканеры ----------
    static bool OfficialInstalled()
    {
        foreach (var env in new[] { "ProgramFiles(x86)", "ProgramFiles" })
        {
            var p = Environment.GetEnvironmentVariable(env);
            if (!string.IsNullOrEmpty(p) && Directory.Exists(Path.Combine(p, "Minecraft Launcher"))) return true;
        }
        try
        {
            var lp = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            return !string.IsNullOrEmpty(lp) && Directory.GetDirectories(Path.Combine(lp, "Packages"))
                .Any(d => Path.GetFileName(d).StartsWith("Microsoft.4297127D64EC6"));
        }
        catch { return false; }
    }

    static List<Instance> ScanDotMinecraft(string label)
    {
        if (!Directory.Exists(McDir)) return OfficialInstalled() ? new List<Instance>() : null;
        var res = new List<Instance>();
        var seen = new HashSet<string>();

        foreach (var fn in new[] { "launcher_profiles.json", "tlauncher_profiles.json" })
        {
            var data = ReadJson(Path.Combine(McDir, fn));
            if (data?["profiles"] is not JsonObject profiles) continue;
            foreach (var kv in profiles)
            {
                if (kv.Value is not JsonObject p) continue;
                var vid = Str(p, "lastVersionId") ?? "";
                var loader = LoaderFromText(vid);
                if (loader == null) continue;
                var pname = Str(p, "name");
                if (string.IsNullOrEmpty(pname)) pname = kv.Key;
                var gd = Str(p, "gameDir");
                if (string.IsNullOrEmpty(gd)) gd = McDir;
                res.Add(Inst(label, pname + " [" + vid + "]", gd, McVersion(vid), loader, vid, true));
                seen.Add(vid);
            }
        }
        foreach (var v in SubDirs(Path.Combine(McDir, "versions")))
        {
            var loader = LoaderFromText(v);
            if (loader != null && !seen.Contains(v))
                res.Add(Inst(label, v + " (.minecraft)", McDir, McVersion(v), loader, v, true));
        }
        return res;
    }

    static List<Instance> ScanPrism(string root, string label)
    {
        var idir = Path.Combine(root, "instances");
        if (!Directory.Exists(idir)) return null;
        var uidMap = new Dictionary<string, string>
        {
            ["net.minecraftforge"] = "forge", ["net.neoforged"] = "neoforge",
            ["net.fabricmc.fabric-loader"] = "fabric", ["org.quiltmc.quilt-loader"] = "quilt"
        };
        var res = new List<Instance>();
        foreach (var d in SubDirs(idir))
        {
            if (d.StartsWith("_")) continue;
            var bas = Path.Combine(idir, d);
            var pack = ReadJson(Path.Combine(bas, "mmc-pack.json"));
            if (pack == null) continue;
            string mc = null, loader = null;
            if (pack["components"] is JsonArray comps)
                foreach (var c in comps)
                {
                    var uid = Str(c, "uid");
                    if (uid == "net.minecraft") mc = Str(c, "version");
                    if (uid != null && uidMap.TryGetValue(uid, out var ld)) loader = ld;
                }
            var name = d;
            try
            {
                foreach (var line in File.ReadLines(Path.Combine(bas, "instance.cfg")))
                    if (line.StartsWith("name="))
                    {
                        var n = line.Substring(5).Trim();
                        if (n.Length > 0) name = n;
                    }
            }
            catch { }
            var gd = new[] { "minecraft", ".minecraft" }.Select(x => Path.Combine(bas, x))
                .FirstOrDefault(Directory.Exists) ?? Path.Combine(bas, "minecraft");
            res.Add(Inst(label, name, gd, mc, loader));
        }
        return res;
    }

    static List<Instance> ScanModrinth()
    {
        var root = new[] { "ModrinthApp", "com.modrinth.theseus" }
            .Select(x => Path.Combine(AppData, x)).FirstOrDefault(Directory.Exists);
        if (root == null) return null;
        var pdir = Path.Combine(root, "profiles");
        var meta = new Dictionary<string, (string Name, string Gv, string Ml)>();
        try
        {
            using var con = new SqliteConnection("Data Source=" + Path.Combine(root, "app.db") + ";Mode=ReadOnly");
            con.Open();
            using var cmd = con.CreateCommand();
            cmd.CommandText = "SELECT path, name, game_version, mod_loader FROM profiles";
            using var r = cmd.ExecuteReader();
            while (r.Read())
                meta[r.GetString(0)] = (r.IsDBNull(1) ? null : r.GetString(1),
                                        r.IsDBNull(2) ? null : r.GetString(2),
                                        r.IsDBNull(3) ? null : r.GetString(3));
        }
        catch { }
        var res = new List<Instance>();
        foreach (var d in SubDirs(pdir))
        {
            meta.TryGetValue(d, out var m);
            var ml = (m.Ml ?? "").ToLowerInvariant();
            res.Add(Inst("Modrinth App", m.Name ?? d, Path.Combine(pdir, d), m.Gv,
                         Array.IndexOf(Loaders, ml) >= 0 ? ml : null));
        }
        return res;
    }

    static List<Instance> ScanCurseForge()
    {
        var root = new[]
        {
            Path.Combine(Home, "curseforge", "minecraft", "Instances"),
            Path.Combine(Home, "Documents", "curseforge", "minecraft", "Instances")
        }.FirstOrDefault(Directory.Exists);
        return root == null ? null : ScanCurseDir(root);
    }

    static List<Instance> ScanCurseDir(string root)
    {
        var res = new List<Instance>();
        foreach (var d in SubDirs(root))
        {
            var bas = Path.Combine(root, d);
            var j = ReadJson(Path.Combine(bas, "minecraftinstance.json"));
            var bml = Str(j?["baseModLoader"], "name") ?? "";
            res.Add(Inst("CurseForge", d, bas, Str(j, "gameVersion") ?? McVersion(bml), LoaderFromText(bml)));
        }
        return res;
    }

    static List<Instance> ScanAtl(string root = null)
    {
        root ??= Path.Combine(AppData, "ATLauncher", "instances");
        if (!Directory.Exists(root)) return null;
        var res = new List<Instance>();
        foreach (var d in SubDirs(root))
        {
            var bas = Path.Combine(root, d);
            var j = ReadJson(Path.Combine(bas, "instance.json"));
            var launcher = j?["launcher"];
            var id = Str(j, "id");
            res.Add(Inst("ATLauncher", Str(launcher, "name") ?? d, bas,
                         McVersion(id) != null ? id : null,
                         LoaderFromText(Str(launcher?["loaderVersion"], "type") ?? "")));
        }
        return res;
    }

    static List<Instance> ScanGdl()
    {
        var root = Path.Combine(AppData, "gdlauncher_carbon", "data", "instances");
        if (!Directory.Exists(root)) return null;
        var res = new List<Instance>();
        foreach (var d in SubDirs(root))
        {
            var bas = Path.Combine(root, d);
            var inner = Path.Combine(bas, "instance");
            var gd = Directory.Exists(inner) ? inner : bas;
            var txt = "";
            try { txt = File.ReadAllText(Path.Combine(bas, "config.json")); } catch { }
            var m = Regex.Match(txt, "\"(?:mcVersion|minecraft|gameVersion)\"\\s*:\\s*\"(1\\.[\\d.]+)\"");
            res.Add(Inst("GDLauncher", d, gd, m.Success ? m.Groups[1].Value : null, LoaderFromText(txt)));
        }
        return res;
    }

    /// <summary>Ручной выбор: папка лаунчера или отдельной сборки.</summary>
    public static List<Instance> ScanFolder(string path)
    {
        var r = ScanPrism(path, "Manual");
        if (r is { Count: > 0 }) return r;
        r = ScanAtl(Path.Combine(path, "instances"));
        if (r is { Count: > 0 }) return r;
        var sd = SubDirs(path);
        if (sd.Count > 0 && File.Exists(Path.Combine(path, sd[0], "minecraftinstance.json")))
        {
            r = ScanCurseDir(path);
            if (r is { Count: > 0 }) return r;
        }
        var pd = Path.Combine(path, "profiles");
        if (Directory.Exists(pd))
            return SubDirs(pd).Select(d => Inst("Manual", d, Path.Combine(pd, d), null, null)).ToList();

        var gd = new[] { "minecraft", ".minecraft" }.Select(x => Path.Combine(path, x))
            .FirstOrDefault(Directory.Exists) ?? path;
        var nm = Path.GetFileName(path.TrimEnd('\\', '/'));
        return new List<Instance> { Inst("Manual", string.IsNullOrEmpty(nm) ? path : nm, gd, null, null) };
    }

    public static List<Group> Find()
    {
        var cands = new List<(string Name, Func<List<Instance>> Fn)>
        {
            (McGroup, () => ScanDotMinecraft(".minecraft")),
            ("Prism Launcher", () => ScanPrism(Path.Combine(AppData, "PrismLauncher"), "Prism Launcher")),
            ("PolyMC", () => ScanPrism(Path.Combine(AppData, "PolyMC"), "PolyMC")),
            ("MultiMC", () => ScanPrism(Path.Combine(AppData, "MultiMC"), "MultiMC")),
            ("Modrinth App", ScanModrinth),
            ("CurseForge", ScanCurseForge),
            ("ATLauncher", () => ScanAtl()),
            ("GDLauncher", ScanGdl),
        };
        var found = new List<Group>();
        foreach (var (name, fn) in cands)
        {
            List<Instance> r = null;
            try { r = fn(); } catch { }
            if (r != null) found.Add(new Group { Key = name, Name = name, Items = r });
        }
        return found;
    }
}
