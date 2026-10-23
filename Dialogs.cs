using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using static SphinxInstaller.Loc;

namespace SphinxInstaller;

/// <summary>Мелкие помощники для построения интерфейса из кода.</summary>
public static class UI
{
    public static Brush Br(string key) => (Brush)Application.Current.FindResource(key);
    public static Style St(string key) => (Style)Application.Current.FindResource(key);

    public static Button Btn(string text, Action click, bool primary = true)
    {
        var b = new Button { Content = text, Style = St(primary ? "PrimaryBtn" : "GhostBtn") };
        b.Click += (_, _) => click();
        return b;
    }

    public static TextBlock Text(string t, string color = "Fg", double size = 14, bool bold = false, double maxWidth = 0)
    {
        var tb = new TextBlock
        {
            Text = t, Foreground = Br(color), FontSize = size, TextWrapping = TextWrapping.Wrap,
            FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal
        };
        if (maxWidth > 0) tb.MaxWidth = maxWidth;
        return tb;
    }
}

/// <summary>Тёмное окно-диалог в стиле приложения.</summary>
public class DarkDialog : Window
{
    public int Result = -1;
    public string Input;
    readonly TextBox box;

    public DarkDialog(Window owner, string title, string text, string[] buttons, bool input)
    {
        Owner = owner;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        Background = Brushes.Transparent;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        SizeToContent = SizeToContent.Height;
        Width = 500;
        FontFamily = new FontFamily("Segoe UI");

        var panel = new StackPanel { Margin = new Thickness(28, 24, 28, 24) };
        if (!string.IsNullOrEmpty(title))
            panel.Children.Add(new TextBlock
            {
                Text = title, Foreground = UI.Br("Acc"), FontSize = 20, FontWeight = FontWeights.Bold,
                Margin = new Thickness(0, 0, 0, 10), TextWrapping = TextWrapping.Wrap
            });
        panel.Children.Add(UI.Text(text, "Fg", 14));

        if (input)
        {
            box = new TextBox
            {
                Margin = new Thickness(0, 14, 0, 0), Padding = new Thickness(12, 9, 12, 9), FontSize = 15,
                Background = UI.Br("Card"), Foreground = UI.Br("Fg"), CaretBrush = UI.Br("Acc"),
                BorderBrush = UI.Br("Card2"), BorderThickness = new Thickness(1)
            };
            box.KeyDown += (_, e) => { if (e.Key == Key.Enter) Finish(0); };
            panel.Children.Add(box);
        }

        var row = new StackPanel
        {
            Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 22, 0, 0)
        };
        for (int i = 0; i < buttons.Length; i++)
        {
            int idx = i;
            var b = UI.Btn(buttons[i], () => Finish(idx), primary: i == 0);
            b.Margin = new Thickness(0, 0, i == 0 ? 0 : 10, 0);
            // главная кнопка справа
            row.Children.Insert(0, b);
        }
        panel.Children.Add(row);

        Content = new Border
        {
            Margin = new Thickness(12), CornerRadius = new CornerRadius(18), Background = UI.Br("Bg"),
            BorderBrush = UI.Br("Card2"), BorderThickness = new Thickness(1), Child = panel,
            Effect = new DropShadowEffect { BlurRadius = 26, ShadowDepth = 0, Opacity = 0.7, Color = Colors.Black }
        };
        MouseLeftButtonDown += (_, e) => { if (e.ChangedButton == MouseButton.Left && !(box != null && box.IsMouseOver)) DragMove(); };
        Loaded += (_, _) => box?.Focus();
    }

    void Finish(int result)
    {
        Result = result;
        Input = box?.Text;
        Close();
    }
}

public static class Dialogs
{
    /// <summary>Возвращает номер нажатой кнопки или -1, если окно закрыли.</summary>
    public static int Ask(Window owner, string title, string text, params string[] buttons)
    {
        var d = new DarkDialog(owner, title, text, buttons, false);
        d.ShowDialog();
        return d.Result;
    }

    public static void Info(Window owner, string text)
        => Ask(owner, Installer.ServerName, text, T("ok"));

    /// <summary>Спрашивает строку. null — если отменили.</summary>
    public static string Prompt(Window owner, string text)
    {
        var d = new DarkDialog(owner, Installer.ServerName, text, new[] { T("ok"), T("cancel") }, true);
        d.ShowDialog();
        return d.Result == 0 ? (d.Input ?? "").Trim() : null;
    }
}
