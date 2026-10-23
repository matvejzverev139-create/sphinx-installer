# 🐰 Сфинксляндия Installer (C# / WPF)

Переписанная версия установщика на C# (.NET 8, WPF) с новым тёмным интерфейсом.
Логика та же, что в `sphinx_installer.py`: поиск лаунчеров, установка Simple Voice Chat, добавление сервера,
создание сборки (Fabric / Forge / NeoForge), языки RU / EN / UK.

## Сборка

Нужен .NET 8 SDK:

```
dotnet publish SphinxInstaller.csproj -c Release -r win-x64 --self-contained true ^
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true -o out
```

Без ПК: пуш в репозиторий запускает GitHub Actions (`.github/workflows/build.yml`), exe лежит в Actions → Artifacts.

## Файлы

- `MainWindow.xaml(.cs)` — окно, страницы, шаги
- `App.xaml` — цвета и стили (кнопки, карточки, скроллбар)
- `Launchers.cs` — поиск лаунчеров и сборок
- `Installer.cs` — мод, загрузчики, Java
- `Nbt.cs` — запись `servers.dat`
- `Loc.cs` — переводы
- `Dialogs.cs` — тёмные диалоги

Настройки сервера — в начале `Installer.cs`.

## Лицензия

MIT — см. файл [LICENSE](LICENSE). Автор: Qwermix_lol.
