using System.Diagnostics;
using System.IO.Compression;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using static SphinxInstaller.Loc;

namespace SphinxInstaller;

/// <summary>Скачивание мода, установка загрузчиков, создание сборок. Все методы блокирующие — звать из Task.Run.</summary>
public static class Installer
{
    // ====== НАСТРОЙКИ (поменяй тут) ======
    public const string ServerName = "Сфинксляндия";
    public const string ServerIp = "FatSphynx.gomc.me";
    public const string ModSlug = "simple-voice-chat";
    public const string LauncherUrl = "https://launcher.mojang.com/download/MinecraftInstaller.exe";
    // =====================================

    static readonly string McDir = Launchers.McDir;
    static readonly HttpClient Http = MakeClient();
    static readonly JsonSerializerOptions Pretty = new()
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };

    static HttpClient MakeClient()
    {
        var c = new HttpClient { Timeout = TimeSpan.FromMinutes(15) };
        c.DefaultRequestHeaders.UserAgent.ParseAdd("SphinxInstaller/2.0");
        return c;
    }

    // ---------- http ----------
    static Stream GetStream(string url) => Http.GetStreamAsync(url).GetAwaiter().GetResult();
    static string GetString(string url) => Http.GetStringAsync(url).GetAwaiter().GetResult();
    static JsonNode JGet(string url) => JsonNode.Parse(GetString(url));

    public static void DownloadTo(string url, string dest)
    {
        var tmp = dest + ".part";
        using (var r = GetStream(url))
        using (var o = File.Create(tmp))
            r.CopyTo(o);
        File.Move(tmp, dest, true);
    }

    static List<string> SubDirs(string p)
    {
        try { return Directory.GetDirectories(p).Select(x => Path.GetFileName(x)).ToList(); }
        catch { return new List<string>(); }
    }

    // ---------- мод ----------
    static JsonNode PickVersion(string project, string mc, string loader)
    {
        var q = "loaders=" + Uri.EscapeDataString("[\"" + loader + "\"]") +
                "&game_versions=" + Uri.EscapeDataString("[\"" + mc + "\"]");
        var arr = JGet($"https://api.modrinth.com/v2/project/{project}/version?{q}") as JsonArray;
        return arr != null && arr.Count > 0 ? arr[0] : null;
    }

    static void DownloadFile(JsonNode v, string mods, Action<string> log)
    {
        var files = v["files"].AsArray();
        var f = files.FirstOrDefault(x => x["primary"]?.GetValue<bool>() == true) ?? files[0];
        var filename = f["filename"].GetValue<string>();
        var dest = Path.Combine(mods, filename);
        if (File.Exists(dest)) { log(T("log_exists", filename)); return; }
        log(T("log_dl", filename));
        DownloadTo(f["url"].GetValue<string>(), dest);
    }

    public static void InstallVoiceChat(string gameDir, string mc, string loader, Action<string> log)
    {
        log(T("log_search", loader, mc));
        var v = PickVersion(ModSlug, mc, loader);
        if (v == null) throw new InvalidOperationException(T("err_nomod", loader, mc));
        var mods = Path.Combine(gameDir, "mods");
        Directory.CreateDirectory(mods);
        foreach (var old in Directory.GetFiles(mods, "*.jar"))
        {
            var n = Path.GetFileName(old);
            if (n.Contains("voicechat", StringComparison.OrdinalIgnoreCase))
            {
                File.Delete(old);
                log(T("log_removed", n));
            }
        }
        DownloadFile(v, mods, log);
        if (v["dependencies"] is JsonArray deps)
            foreach (var dep in deps)
            {
                var type = dep["dependency_type"]?.GetValue<string>();
                var pid = dep["project_id"]?.GetValue<string>();
                if (type == "required" && !string.IsNullOrEmpty(pid))
                {
                    var dv = PickVersion(pid, mc, loader);
                    if (dv != null) { log(T("log_dep")); DownloadFile(dv, mods, log); }
                }
            }
        log(T("log_modok"));
    }

    /// <summary>Отдельная папка + профиль в .minecraft лаунчере с той же версией.</summary>
    public static string CreateNewBuild(string vid)
    {
        var gd = Path.Combine(McDir, "sphinxlandia");
        Directory.CreateDirectory(gd);
        var pj = Path.Combine(McDir, "launcher_profiles.json");
        JsonObject data = null;
        try { data = JsonNode.Parse(File.ReadAllText(pj)) as JsonObject; } catch { }
        data ??= new JsonObject { ["profiles"] = new JsonObject(), ["version"] = 3 };
        if (File.Exists(pj)) File.Copy(pj, pj + ".bak", true);
        if (data["profiles"] is not JsonObject profiles)
        {
            profiles = new JsonObject();
            data["profiles"] = profiles;
        }
        profiles["sphinxlandia"] = new JsonObject
        {
            ["name"] = ServerName, ["type"] = "custom", ["lastVersionId"] = vid, ["gameDir"] = gd
        };
        File.WriteAllText(pj, data.ToJsonString(Pretty));
        return gd;
    }

    // ---------- версии загрузчиков ----------
    static string ForgeVersion(string mc)
    {
        var promos = JGet("https://files.minecraftforge.net/net.minecraftforge.files/promotions_slim.json")?["promos"];
        var v = promos?[mc + "-recommended"]?.GetValue<string>() ?? promos?[mc + "-latest"]?.GetValue<string>();
        if (string.IsNullOrEmpty(v)) throw new InvalidOperationException(T("err_nover", "Forge", mc));
        return v;
    }

    static Version NumKey(string s)
    {
        var nums = Regex.Matches(s, @"\d+").Select(m => m.Value).Take(4).ToList();
        while (nums.Count < 2) nums.Add("0");
        return Version.TryParse(string.Join(".", nums), out var v) ? v : new Version(0, 0);
    }

    static string NeoForgeVersion(string mc)
    {
        string pref;
        try
        {
            var p = mc.Split('.');
            if (int.Parse(p[0]) >= 25)   // 26.2 -> "26.2.0." , 26.1.2 -> "26.1.2."
            {
                var parts = p.ToList();
                while (parts.Count < 3) parts.Add("0");
                pref = string.Join(".", parts) + ".";
            }
            else                         // 1.21.11 -> "21.11."
                pref = p[1] + "." + (p.Length > 2 ? p[2] : "0") + ".";
        }
        catch { throw new InvalidOperationException(T("err_nover", "NeoForge", mc)); }

        var vs = (JGet("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge")?["versions"] as JsonArray)
            ?.Select(x => x.GetValue<string>()).Where(x => x.StartsWith(pref)).ToList() ?? new List<string>();
        var stable = vs.Where(x => !x.Contains('-')).ToList();
        var pool = stable.Count > 0 ? stable : vs;
        if (pool.Count == 0) throw new InvalidOperationException(T("err_nover", "NeoForge", mc));
        return pool.OrderByDescending(NumKey).First();
    }

    static string FabricVersion(string mc)
    {
        var vs = JGet("https://meta.fabricmc.net/v2/versions/loader/" + mc) as JsonArray;
        if (vs != null)
        {
            foreach (var e in vs)
                if (e["loader"]?["stable"]?.GetValue<bool>() == true)
                    return e["loader"]["version"].GetValue<string>();
            if (vs.Count > 0) return vs[0]["loader"]["version"].GetValue<string>();
        }
        throw new InvalidOperationException(T("err_nover", "Fabric", mc));
    }

    /// <summary>Самая новая версия игры (из манифеста Mojang).</summary>
    public static string LatestMc()
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(6));
            var s = Http.GetStringAsync("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", cts.Token)
                .GetAwaiter().GetResult();
            return JsonNode.Parse(s)["latest"]["release"].GetValue<string>();
        }
        catch { return "26.2"; }
    }

    // ---------- Java ----------
    static int JavaMajor(string path)
    {
        try
        {
            var psi = new ProcessStartInfo(path, "-version")
            {
                RedirectStandardError = true, RedirectStandardOutput = true,
                UseShellExecute = false, CreateNoWindow = true
            };
            using var p = Process.Start(psi);
            var o = p.StandardError.ReadToEnd() + p.StandardOutput.ReadToEnd();
            p.WaitForExit(20000);
            var m = Regex.Match(o, "version \"(\\d+)(?:\\.(\\d+))?");
            if (m.Success)
                return m.Groups[1].Value == "1" && m.Groups[2].Success
                    ? int.Parse(m.Groups[2].Value) : int.Parse(m.Groups[1].Value);
        }
        catch { }
        return 0;
    }

    static int NeedJava(string mc)
    {
        try { return int.Parse(mc.Split('.')[0]) >= 25 ? 25 : 21; }
        catch { return 21; }
    }

    static string FindJavaExe(string dir)
    {
        try { return Directory.EnumerateFiles(dir, "java.exe", SearchOption.AllDirectories).FirstOrDefault(); }
        catch { return null; }
    }

    static string FindJava(Action<string> log, int need)
    {
        log(T("log_java"));
        var cands = new List<string>();
        var jh = Environment.GetEnvironmentVariable("JAVA_HOME");
        if (!string.IsNullOrEmpty(jh)) cands.Add(Path.Combine(jh, "bin", "java.exe"));
        foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';', StringSplitOptions.RemoveEmptyEntries))
            try { cands.Add(Path.Combine(dir.Trim('"'), "java.exe")); } catch { }
        var cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                 "SphinxInstaller", "jre-" + need);
        if (Directory.Exists(cache)) { var c = FindJavaExe(cache); if (c != null) cands.Add(c); }
        if (Directory.Exists(Path.Combine(McDir, "runtime")))
            cands.AddRange(Directory.EnumerateFiles(Path.Combine(McDir, "runtime"), "java.exe", SearchOption.AllDirectories));

        foreach (var c in cands)
            if (File.Exists(c) && JavaMajor(c) >= need) return c;

        log(T("log_java_dl"));
        var tmp = Path.Combine(Path.GetTempPath(), "sphinx-jre-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tmp);
        var zip = Path.Combine(tmp, "jre.zip");
        DownloadTo($"https://api.adoptium.net/v3/binary/latest/{need}/ga/windows/x64/jre/hotspot/normal/eclipse", zip);
        Directory.CreateDirectory(cache);
        ZipFile.ExtractToDirectory(zip, cache, true);
        try { Directory.Delete(tmp, true); } catch { }
        return FindJavaExe(cache) ?? throw new FileNotFoundException("Java not found");
    }

    // ---------- загрузчики ----------
    static void EnsureProfilesFile()
    {
        Directory.CreateDirectory(McDir);
        var pj = Path.Combine(McDir, "launcher_profiles.json");
        if (!File.Exists(pj)) File.WriteAllText(pj, "{\"profiles\":{},\"version\":3}");
    }

    static string RunInstaller(string url, string loader, string expectedId, string mc, Action<string> log)
    {
        var java = FindJava(log, NeedJava(mc));
        EnsureProfilesFile();
        var tmp = Path.Combine(Path.GetTempPath(), "sphinx-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tmp);
        var jar = Path.Combine(tmp, "installer.jar");
        log(T("log_dl", Launchers.LoaderNames[loader]));
        DownloadTo(url, jar);

        var vdir = Path.Combine(McDir, "versions");
        var before = new HashSet<string>(SubDirs(vdir));

        var psi = new ProcessStartInfo(java)
        {
            WorkingDirectory = tmp, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        psi.ArgumentList.Add("-jar"); psi.ArgumentList.Add(jar);
        psi.ArgumentList.Add("--installClient"); psi.ArgumentList.Add(McDir);

        var output = new StringBuilder();
        using var p = new Process { StartInfo = psi };
        p.OutputDataReceived += (_, e) => { if (e.Data != null) lock (output) output.AppendLine(e.Data); };
        p.ErrorDataReceived += (_, e) => { if (e.Data != null) lock (output) output.AppendLine(e.Data); };
        p.Start();
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        if (!p.WaitForExit(25 * 60 * 1000))
        {
            try { p.Kill(true); } catch { }
            throw new InvalidOperationException(T("err_loader", Launchers.LoaderNames[loader]));
        }
        p.WaitForExit();
        try { Directory.Delete(tmp, true); } catch { }

        if (p.ExitCode != 0)
        {
            string tail;
            lock (output) { var s = output.ToString(); tail = s.Length > 300 ? s[^300..] : s; }
            throw new InvalidOperationException(T("err_loader", Launchers.LoaderNames[loader]) + "\n\n" + tail);
        }
        var added = SubDirs(vdir).Where(v => !before.Contains(v) && Launchers.LoaderFromText(v) == loader).ToList();
        if (added.Count > 0) return added[0];
        if (Directory.Exists(Path.Combine(vdir, expectedId))) return expectedId;
        throw new InvalidOperationException(T("err_loader", Launchers.LoaderNames[loader]));
    }

    /// <summary>Ставит загрузчик в .minecraft, возвращает id версии.</summary>
    static string InstallLoaderDotMc(string loader, string mc, Action<string> log)
    {
        log(T("log_loader", Launchers.LoaderNames[loader]));
        string vid;
        if (loader == "fabric")
        {
            var lv = FabricVersion(mc);
            var json = GetString($"https://meta.fabricmc.net/v2/versions/loader/{mc}/{lv}/profile/json");
            vid = JsonNode.Parse(json)["id"].GetValue<string>();
            var d = Path.Combine(McDir, "versions", vid);
            Directory.CreateDirectory(d);
            EnsureProfilesFile();
            File.WriteAllText(Path.Combine(d, vid + ".json"), json);
        }
        else if (loader == "forge")
        {
            var v = ForgeVersion(mc);
            var url = $"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{v}/forge-{mc}-{v}-installer.jar";
            vid = RunInstaller(url, loader, $"{mc}-forge-{v}", mc, log);
        }
        else
        {
            var v = NeoForgeVersion(mc);
            var url = $"https://maven.neoforged.net/releases/net/neoforged/neoforge/{v}/neoforge-{v}-installer.jar";
            vid = RunInstaller(url, loader, "neoforge-" + v, mc, log);
        }
        log(T("log_loader_ok", Launchers.LoaderNames[loader]));
        return vid;
    }

    static string CreatePrismInstance(string root, string loader, string mc, Action<string> log)
    {
        log(T("log_prism"));
        var uid = loader switch
        {
            "forge" => "net.minecraftforge", "neoforge" => "net.neoforged", _ => "net.fabricmc.fabric-loader"
        };
        var lv = loader switch { "forge" => ForgeVersion(mc), "neoforge" => NeoForgeVersion(mc), _ => FabricVersion(mc) };

        var bas = Path.Combine(root, "instances", ServerName);
        int n = 2;
        while (Directory.Exists(bas)) bas = Path.Combine(root, "instances", ServerName + " " + n++);
        Directory.CreateDirectory(Path.Combine(bas, "minecraft", "mods"));

        var pack = new JsonObject
        {
            ["formatVersion"] = 1,
            ["components"] = new JsonArray
            {
                new JsonObject { ["uid"] = "net.minecraft", ["version"] = mc, ["important"] = true },
                new JsonObject { ["uid"] = uid, ["version"] = lv }
            }
        };
        File.WriteAllText(Path.Combine(bas, "mmc-pack.json"), pack.ToJsonString(Pretty));
        File.WriteAllText(Path.Combine(bas, "instance.cfg"),
                          "InstanceType=OneSix\nname=" + Path.GetFileName(bas) + "\n");
        log(T("log_loader_ok", Launchers.LoaderNames[loader]));
        return Path.Combine(bas, "minecraft");
    }

    /// <summary>Создаёт новую сборку. kind: "dot" (.minecraft) или "prism". Возвращает папку игры.</summary>
    public static string CreateBuild(string kind, string root, string loader, string mc, Action<string> log)
    {
        if (kind == "prism") return CreatePrismInstance(root, loader, mc, log);
        var vid = InstallLoaderDotMc(loader, mc, log);
        var g = CreateNewBuild(vid);
        log(T("log_newbuild", g));
        return g;
    }
}
