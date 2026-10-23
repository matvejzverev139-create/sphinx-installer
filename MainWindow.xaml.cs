using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
using static SphinxInstaller.Loc;
using static SphinxInstaller.UI;

namespace SphinxInstaller;

public partial class MainWindow : Window
{
    // ---------- состояние ----------
    string page = "welcome";
    bool busy;
    List<Group> found = new();
    List<Instance> manual;
    int selL = -1, selI = -1;
    List<Instance> cur = new();
    Instance inst;
    string target;
    string newLoader = "fabric", newMc;
    string err;
    TextBox logBox;
    TextBlock status;

    public MainWindow()
    {
        InitializeComponent();
        Lang = SystemLang();
        TitleText.Text = Installer.ServerName;
        Go("welcome");
    }

    // ---------- окно ----------
    void Drag(object s, MouseButtonEventArgs e) { if (e.ChangedButton == MouseButton.Left) DragMove(); }
    void OnMin(object s, RoutedEventArgs e) => WindowState = WindowState.Minimized;
    void OnClose(object s, RoutedEventArgs e) => Close();

    // ---------- навигация ----------
    void Go(string p)
    {
        if (p == "build" && (selL < 0 || selL >= found.Count)) p = "launcher";
        page = p;
        logBox = null;
        status = null;
        Footer.Children.Clear();
        DrawLangs();
        DrawSteps(p switch
        {
            "welcome" => 0, "launcher" => 1, "build" or "newl" or "newv" => 2,
            "confirm" or "install" or "error" => 3, _ => 4
        });

        UIElement content = p switch
        {
            "welcome" => PageWelcome(),
            "launcher" => PageLauncher(),
            "build" => PageBuild(),
            "newl" => PageNewL(),
            "newv" => PageNewV(),
            "confirm" => PageConfirm(),
            "install" => PageInstall(),
            "error" => PageError(),
            _ => PageDone()
        };
        Swap(content);
        if (p == "install") RunInstall();
    }

    void Swap(UIElement el)
    {
        PageHost.Content = el;
        el.Opacity = 0;
        var tt = new TranslateTransform(0, 16);
        el.RenderTransform = tt;
        el.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(280)));
        tt.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(16, 0, TimeSpan.FromMilliseconds(320))
        {
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
        });
    }

    void Recheck() { Refresh(); Go(page); }

    void Refresh()
    {
        found = Launchers.Find();
        if (manual != null)
            found.Add(new Group { Key = Launchers.ManualKey, Name = T("manual_group"), Items = manual });
    }

    string GroupName(Group g) => g.Key == Launchers.ManualKey ? T("manual_group") : g.Name;

    // ---------- общие куски ----------
    void DrawLangs()
    {
        LangBox.Children.Clear();
        foreach (var (code, name) in Langs)
        {
            bool active = Lang == code;
            var b = new Border
            {
                Background = Br(active ? "Acc" : "Card2"), CornerRadius = new CornerRadius(9),
                Padding = new Thickness(11, 5, 11, 5), Margin = new Thickness(3, 0, 3, 0), Cursor = Cursors.Hand,
                Child = new TextBlock
                {
                    Text = name, FontSize = 11, FontWeight = FontWeights.Bold,
                    Foreground = Br(active ? "Dark" : "Fg")
                }
            };
            var c = code;
            b.MouseLeftButtonUp += (_, _) => { if (!busy) { Lang = c; Go(page); } };
            LangBox.Children.Add(b);
        }
    }

    void DrawSteps(int n)
    {
        if (n == 0) { StepHost.Content = null; return; }
        var g = new Grid();
        for (int i = 0; i < 4; i++) g.ColumnDefinitions.Add(new ColumnDefinition());

        Border Line(bool visible, bool on, int col)
        {
            var l = new Border
            {
                Height = 3, CornerRadius = new CornerRadius(2), VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(4, 0, 4, 0),
                Background = on ? Br("Acc") : visible ? Br("Card2") : Brushes.Transparent
            };
            Grid.SetColumn(l, col);
            return l;
        }

        for (int i = 0; i < 4; i++)
        {
            int k = i + 1;
            bool reached = k <= n;
            bool tick = k < n || n == 4;

            var top = new Grid();
            top.ColumnDefinitions.Add(new ColumnDefinition());
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            top.ColumnDefinitions.Add(new ColumnDefinition());
            top.Children.Add(Line(k > 1, k <= n, 0));
            top.Children.Add(Line(k < 4, k < n, 2));

            var circle = new Border
            {
                Width = 34, Height = 34, CornerRadius = new CornerRadius(17), BorderThickness = new Thickness(2),
                Background = reached ? Br("Acc") : Br("Bg"),
                BorderBrush = k == n ? Br("Acc2") : reached ? Br("Acc") : Br("Card2"),
                Child = new TextBlock
                {
                    Text = tick ? "✓" : k.ToString(), FontWeight = FontWeights.Bold, FontSize = 14,
                    Foreground = reached ? Br("Dark") : Br("Muted"),
                    HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center
                }
            };
            Grid.SetColumn(circle, 1);
            top.Children.Add(circle);

            var label = Text(T("s" + k), reached ? "Fg" : "Muted", 12, true);
            label.HorizontalAlignment = HorizontalAlignment.Center;
            label.Margin = new Thickness(0, 8, 0, 0);
            Grid.SetRow(label, 1);

            var cell = new Grid();
            cell.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            cell.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            cell.Children.Add(top);
            cell.Children.Add(label);
            Grid.SetColumn(cell, i);
            g.Children.Add(cell);
        }
        StepHost.Content = g;
    }

    TextBlock H(string t, string color = "Fg")
    {
        var tb = Text(t, color, 26, true);
        tb.FontWeight = FontWeights.Bold;
        tb.Margin = new Thickness(0, 6, 0, 8);
        return tb;
    }

    TextBlock P(string t, string color = "Muted", double size = 14)
    {
        var tb = Text(t, color, size);
        tb.Margin = new Thickness(0, 0, 0, 12);
        return tb;
    }

    Border Card(UIElement child, double pad = 20)
        => new() { Background = Br("Card"), CornerRadius = new CornerRadius(14), Padding = new Thickness(pad, pad * 0.7, pad, pad * 0.7), Child = child };

    UIElement Choice(string title, string sub)
    {
        var sp = new StackPanel();
        sp.Children.Add(Text(title, "Fg", 16, true));
        if (!string.IsNullOrEmpty(sub))
        {
            var s = Text(sub, "Muted", 12);
            s.Margin = new Thickness(0, 3, 0, 0);
            sp.Children.Add(s);
        }
        return sp;
    }

    ListBox MakeList(List<UIElement> items, int sel, Action<int> onPick)
    {
        var lb = new ListBox { Style = St("PlainList"), ItemContainerStyle = St("CardItem") };
        foreach (var it in items) lb.Items.Add(it);
        lb.SelectionChanged += (_, _) => onPick(lb.SelectedIndex);
        lb.SelectedIndex = sel >= 0 && sel < items.Count ? sel : items.Count > 0 ? 0 : -1;
        return lb;
    }

    Button SetFooter(Action back = null, IEnumerable<(string Text, Action Click)> extra = null,
                     Action next = null, string nextText = null)
    {
        Footer.Children.Clear();
        var left = new StackPanel { Orientation = Orientation.Horizontal };
        if (back != null) left.Children.Add(Btn(T("back"), back, false));
        if (extra != null)
            foreach (var (t, a) in extra)
            {
                var b = Btn(t, a, false);
                b.Margin = new Thickness(10, 0, 0, 0);
                left.Children.Add(b);
            }
        DockPanel.SetDock(left, Dock.Left);
        Footer.Children.Add(left);
        Button nb = null;
        if (next != null)
        {
            nb = Btn(nextText ?? T("next"), next);
            DockPanel.SetDock(nb, Dock.Right);
            Footer.Children.Add(nb);
        }
        return nb;
    }

    static DockPanel Dock2(out StackPanel head)
    {
        var dock = new DockPanel { LastChildFill = true };
        head = new StackPanel();
        DockPanel.SetDock(head, Dock.Top);
        dock.Children.Add(head);
        return dock;
    }

    // ---------- страница: приветствие ----------
    UIElement PageWelcome()
    {
        var sp = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        var img = new Image
        {
            Source = new BitmapImage(new Uri("pack://application:,,,/Assets/logo.png")),
            Width = 128, Height = 128, Margin = new Thickness(0, 0, 0, 6)
        };
        RenderOptions.SetBitmapScalingMode(img, BitmapScalingMode.HighQuality);
        sp.Children.Add(img);

        var h = H(T("w_h"));
        h.HorizontalAlignment = HorizontalAlignment.Center;
        sp.Children.Add(h);

        var t = P(T("w_t", Installer.ServerName), "Fg", 16);
        t.TextAlignment = TextAlignment.Center;
        t.Margin = new Thickness(0, 0, 0, 18);
        sp.Children.Add(t);

        var rows = new StackPanel();
        foreach (var (icon, key) in new[] { ("🔎", "w1"), ("🎙", "w2"), ("🌐", "w3") })
        {
            var r = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 7, 0, 7) };
            r.Children.Add(new Border
            {
                Width = 42, Height = 42, CornerRadius = new CornerRadius(21), Background = Br("AccSoft"),
                Child = new TextBlock
                {
                    Text = icon, FontSize = 19, HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center
                }
            });
            var tx = Text(T(key), "Fg", 16);
            tx.VerticalAlignment = VerticalAlignment.Center;
            tx.Margin = new Thickness(16, 0, 0, 0);
            r.Children.Add(tx);
            rows.Children.Add(r);
        }
        sp.Children.Add(Card(rows, 26));

        SetFooter(next: () => { Refresh(); Go("launcher"); }, nextText: T("start"));
        return sp;
    }

    // ---------- страница: лаунчер ----------
    UIElement PageLauncher()
    {
        var dock = Dock2(out var head);
        head.Children.Add(H(T("l_h")));

        if (found.Count == 0)
        {
            head.Children.Add(P(T("l_none_t"), "Fg", 15));
            var sp = new StackPanel();
            var links = new (string Label, string Url, string Desc)[]
            {
                (T("dl_official"), null, "ld_official"),
                ("Prism Launcher", "https://prismlauncher.org/download/", "ld_prism"),
                ("Modrinth App", "https://modrinth.com/app", "ld_modrinth"),
                ("CurseForge", "https://www.curseforge.com/download/app", "ld_curse"),
                ("TLauncher", "https://tlauncher.org/", "ld_tl"),
            };
            foreach (var l in links)
            {
                var row = new Grid { Margin = new Thickness(0, 5, 0, 5) };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(270) });
                row.ColumnDefinitions.Add(new ColumnDefinition());
                var url = l.Url;
                row.Children.Add(Btn("⬇  " + l.Label, () => Download(url), false));
                var d = Text(T(l.Desc), "Muted", 12);
                d.VerticalAlignment = VerticalAlignment.Center;
                d.Margin = new Thickness(16, 0, 0, 0);
                Grid.SetColumn(d, 1);
                row.Children.Add(d);
                sp.Children.Add(row);
            }
            status = Text("", "Acc", 13);
            status.Margin = new Thickness(0, 10, 0, 0);
            sp.Children.Add(status);
            dock.Children.Add(sp);
            SetFooter(() => Go("welcome"),
                new List<(string, Action)> { (T("recheck"), Recheck), (T("manual"), PickManual) });
            return dock;
        }

        head.Children.Add(P(T("l_t")));
        var next = SetFooter(() => Go("welcome"),
            new List<(string, Action)> { (T("recheck"), Recheck), (T("manual"), PickManual) },
            () => Go("build"));
        var items = found.Select(g => Choice(GroupName(g), T("n_builds", g.Items.Count))).ToList();
        dock.Children.Add(MakeList(items, selL, i =>
        {
            if (i != selL) selI = -1;
            selL = i;
            next.IsEnabled = i >= 0;
        }));
        return dock;
    }

    void PickManual()
    {
        var dlg = new OpenFolderDialog { Title = T("pick_dir") };
        if (dlg.ShowDialog(this) != true) return;
        manual = Launchers.ScanFolder(dlg.FolderName);
        Refresh();
        selL = found.Count - 1;
        selI = -1;
        Go("build");
    }

    void Download(string url)
    {
        if (url != null)
        {
            try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch { }
            if (status != null) { status.Text = T("dl_open"); status.Foreground = Br("Acc"); }
            return;
        }
        status.Text = T("dl_started");
        status.Foreground = Br("Acc");
        Task.Run(() =>
        {
            try
            {
                var p = Path.Combine(Path.GetTempPath(), "MinecraftInstaller.exe");
                Installer.DownloadTo(Installer.LauncherUrl, p);
                Process.Start(new ProcessStartInfo(p) { UseShellExecute = true });
            }
            catch
            {
                Dispatcher.InvokeAsync(() =>
                {
                    if (status != null) { status.Text = T("err_net"); status.Foreground = Br("Bad"); }
                });
            }
        });
    }

    // ---------- страница: сборка ----------
    (string Kind, string Root)? Creator()
    {
        var key = found[selL].Key;
        if (key == Launchers.McGroup) return ("dot", null);
        var map = new Dictionary<string, string>
        {
            ["Prism Launcher"] = "PrismLauncher", ["PolyMC"] = "PolyMC", ["MultiMC"] = "MultiMC"
        };
        return map.TryGetValue(key, out var d) ? ("prism", Path.Combine(Launchers.AppData, d)) : null;
    }

    UIElement PageBuild()
    {
        cur = found[selL].Items;
        var creator = Creator();
        var dock = Dock2(out var head);
        head.Children.Add(H(T("b_h")));

        if (cur.Count == 0)
        {
            head.Children.Add(P(creator != null ? T("b_none_t") : T("b_none_nc"), "Fg", 15));
            var ex = new List<(string, Action)> { (T("recheck"), Recheck) };
            if (creator != null) SetFooter(() => Go("launcher"), ex, NewFlow, T("new_build"));
            else SetFooter(() => Go("launcher"), ex);
            return dock;
        }

        head.Children.Add(P(T("b_t")));
        var ex2 = new List<(string, Action)>();
        if (creator != null) ex2.Add((T("new_build"), NewFlow));
        ex2.Add((T("recheck"), Recheck));
        var next = SetFooter(() => Go("launcher"), ex2, BuildNext);

        var items = cur.Select(b => Choice(b.Name,
            (b.Loader != null ? Launchers.LoaderNames[b.Loader] : "?") + "  ·  " + (b.Mc ?? "?"))).ToList();
        dock.Children.Add(MakeList(items, selI, i => { selI = i; next.IsEnabled = i >= 0; }));
        return dock;
    }

    void NewFlow() { newLoader = "fabric"; Go("newl"); }

    void BuildNext()
    {
        if (selI < 0 || selI >= cur.Count) return;
        var b = cur[selI].Clone();
        if (string.IsNullOrEmpty(b.Mc)) b.Mc = Dialogs.Prompt(this, T("ask_ver")) ?? "";
        if (string.IsNullOrEmpty(b.Loader)) b.Loader = (Dialogs.Prompt(this, T("ask_loader")) ?? "").ToLowerInvariant();
        if (string.IsNullOrEmpty(b.Mc) || Array.IndexOf(Launchers.Loaders, b.Loader ?? "") < 0)
        {
            Dialogs.Info(this, T("need_data"));
            return;
        }
        inst = b;
        Go("confirm");
    }

    // ---------- новая сборка ----------
    UIElement PageNewL()
    {
        var dock = Dock2(out var head);
        head.Children.Add(H(T("nl_h")));
        head.Children.Add(P(T("nl_t")));
        SetFooter(() => Go("build"), next: () => Go("newv"));

        var desc = Text("", "Fg", 14);
        var loaders = new[] { "fabric", "forge", "neoforge" };
        var items = loaders.Select(l => Choice(Launchers.LoaderNames[l] + (l == "fabric" ? "  ⭐" : ""), null)).ToList();
        var lb = MakeList(items, Array.IndexOf(loaders, newLoader), i =>
        {
            if (i < 0) return;
            newLoader = loaders[i];
            desc.Text = T("d_" + newLoader);
        });
        lb.VerticalAlignment = VerticalAlignment.Top;

        var grid = new Grid { Margin = new Thickness(0, 4, 0, 0) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(240) });
        grid.ColumnDefinitions.Add(new ColumnDefinition());
        grid.Children.Add(lb);
        var card = Card(desc, 24);
        card.Margin = new Thickness(18, 0, 0, 8);
        card.VerticalAlignment = VerticalAlignment.Top;
        Grid.SetColumn(card, 1);
        grid.Children.Add(card);
        dock.Children.Add(grid);
        return dock;
    }

    UIElement PageNewV()
    {
        var dock = Dock2(out var head);
        head.Children.Add(H(T("nv_h")));
        head.Children.Add(P(T("nv_t")));
        var next = SetFooter(() => Go("newl"), next: MakeNew);
        next.IsEnabled = false;
        var holder = new ContentControl { Content = Text("…", "Muted", 16) };
        dock.Children.Add(holder);
        LoadVersions(holder, next);
        return dock;
    }

    async void LoadVersions(ContentControl holder, Button next)
    {
        var lat = await Task.Run(() => Installer.LatestMc());
        if (page != "newv") return;
        var vs = new List<(string V, string K)> { (lat, "v_latest") };
        if (lat != "1.21.11") vs.Add(("1.21.11", "v_12111"));
        newMc = vs[0].V;
        var items = vs.Select(x => Choice(x.V, T(x.K))).ToList();
        holder.Content = MakeList(items, 0, i => { if (i >= 0) newMc = vs[i].V; });
        next.IsEnabled = true;
    }

    void MakeNew()
    {
        var c = Creator().Value;
        inst = new Instance
        {
            Create = true, Kind = c.Kind, Root = c.Root, Loader = newLoader, Mc = newMc, Name = Installer.ServerName
        };
        Go("confirm");
    }

    // ---------- подтверждение ----------
    UIElement PageConfirm()
    {
        var b = inst;
        var sp = new StackPanel();
        sp.Children.Add(H(T("c_h")));
        sp.Children.Add(P(T("c_t")));

        var rows = new (string K, string V)[]
        {
            (T("sum_l"), GroupName(found[selL])),
            (T("sum_b"), b.Create
                ? T("sum_new", Installer.ServerName, Launchers.LoaderNames[b.Loader], b.Mc)
                : b.Name + "  [" + Launchers.LoaderNames[b.Loader] + " " + b.Mc + "]"),
            (T("sum_s"), Installer.ServerName + " — " + Installer.ServerIp),
        };
        var inner = new StackPanel();
        for (int i = 0; i < rows.Length; i++)
        {
            var r = new Grid { Margin = new Thickness(0, 10, 0, 10) };
            r.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(120) });
            r.ColumnDefinitions.Add(new ColumnDefinition());
            r.Children.Add(Text(rows[i].K, "Muted", 13));
            var v = Text(rows[i].V, "Fg", 15, true);
            Grid.SetColumn(v, 1);
            r.Children.Add(v);
            inner.Children.Add(r);
            if (i < rows.Length - 1)
                inner.Children.Add(new Border { Height = 1, Background = Br("Card2") });
        }
        sp.Children.Add(Card(inner, 24));
        SetFooter(() => Go(b.Create ? "newv" : "build"), next: StartInstall, nextText: T("install"));
        return sp;
    }

    void StartInstall()
    {
        var b = inst;
        target = b.GameDir;
        if (b.Create) { Go("install"); return; }

        var mods = Path.Combine(target, "mods");
        if (Directory.Exists(mods) && Directory.GetFiles(mods, "*.jar").Length > 0)
        {
            int ans;
            if (b.DotMc && !string.IsNullOrEmpty(b.Vid))
                ans = Dialogs.Ask(this, T("ex_title"), T("ex_text"), T("ex_add"), T("ex_new"), T("cancel"));
            else
                ans = Dialogs.Ask(this, T("ex_title"), T("ex_text"), T("ex_add"), T("cancel")) == 0 ? 0 : -1;
            if (ans == 1) target = null;     // новая отдельная сборка
            else if (ans != 0) return;       // отмена
        }
        Go("install");
    }

    // ---------- установка ----------
    UIElement PageInstall()
    {
        var dock = Dock2(out var head);
        head.Children.Add(H(T("ing_h")));
        head.Children.Add(P(T("ing_t")));

        var track = new Border
        {
            Height = 8, CornerRadius = new CornerRadius(4), Background = Br("Card"), ClipToBounds = true,
            Margin = new Thickness(0, 0, 0, 16)
        };
        var bar = new Border
        {
            Width = 180, CornerRadius = new CornerRadius(4), Background = Br("Acc"),
            HorizontalAlignment = HorizontalAlignment.Left
        };
        var tt = new TranslateTransform();
        bar.RenderTransform = tt;
        track.Child = bar;
        track.Loaded += (_, _) => tt.BeginAnimation(TranslateTransform.XProperty,
            new DoubleAnimation(-180, Math.Max(track.ActualWidth, 400), TimeSpan.FromSeconds(1.3))
            { RepeatBehavior = RepeatBehavior.Forever });
        head.Children.Add(track);

        logBox = new TextBox
        {
            Background = Brushes.Transparent, Foreground = Br("Fg"), BorderThickness = new Thickness(0),
            IsReadOnly = true, TextWrapping = TextWrapping.Wrap, FontSize = 13, Padding = new Thickness(0),
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto, CaretBrush = Brushes.Transparent
        };
        var card = Card(logBox, 18);
        card.Margin = new Thickness(0, 0, 0, 10);
        dock.Children.Add(card);
        return dock;
    }

    void Log(string s)
    {
        Dispatcher.InvokeAsync(() =>
        {
            if (logBox == null) return;
            logBox.AppendText(s + "\n");
            logBox.ScrollToEnd();
        });
    }

    async void RunInstall()
    {
        busy = true;
        var b = inst;
        var tgt = target;
        string error = null;

        await Task.Run(() =>
        {
            try
            {
                string g;
                if (b.Create)
                    g = Installer.CreateBuild(b.Kind, b.Root, b.Loader, b.Mc, Log);
                else
                {
                    g = tgt;
                    if (g == null)
                    {
                        g = Installer.CreateNewBuild(b.Vid);
                        Log(T("log_newbuild", g));
                    }
                }
                Installer.InstallVoiceChat(g, b.Mc, b.Loader, Log);
                Log(Servers.Add(g, Installer.ServerName, Installer.ServerIp) ? T("log_srv_ok") : T("log_srv_have"));
            }
            catch (HttpRequestException) { error = T("err_net"); }
            catch (TaskCanceledException) { error = T("err_net"); }
            catch (Exception e) { error = e.Message; }
        });

        if (error == null) await Task.Delay(700);
        busy = false;
        err = error;
        Go(error != null ? "error" : "done");
    }

    // ---------- финал ----------
    UIElement PageDone()
    {
        var sp = new StackPanel();
        var check = new Border
        {
            Width = 76, Height = 76, CornerRadius = new CornerRadius(38), Background = Br("Good"),
            HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 10),
            Child = new TextBlock
            {
                Text = "✓", FontSize = 40, FontWeight = FontWeights.Bold, Foreground = Br("Dark"),
                HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center
            }
        };
        sp.Children.Add(check);
        sp.Children.Add(H(T("done_h")));
        sp.Children.Add(Card(Text(T("done_t", Installer.ServerName), "Fg", 16), 26));
        SetFooter(next: () => Close(), nextText: T("close"));
        return sp;
    }

    UIElement PageError()
    {
        var sp = new StackPanel();
        sp.Children.Add(H(T("err_h"), "Bad"));
        sp.Children.Add(Card(Text(err ?? "", "Fg", 14), 22));
        SetFooter(() => Go("confirm"), next: () => Go("install"), nextText: T("retry"));
        return sp;
    }
}
