using System.IO;
using BepInEx;
using BepInEx.Configuration;

namespace ReaperEmporiumLocalization.Shared
{
    public static class LocalizationConfig
    {
        private static bool _initialized;

        public static ConfigEntry<bool> EnableDllDump { get; private set; } = null!;
        public static ConfigEntry<bool> EnableDatabaseDump { get; private set; } = null!;
        public static ConfigEntry<bool> EnableFontReplacement { get; private set; } = null!;
        public static ConfigEntry<bool> EnableAutoGenerateFontJson { get; private set; } = null!;
        public static ConfigEntry<bool> EnableSceneDump { get; private set; } = null!;
        public static ConfigEntry<bool> EnableSceneTranslation { get; private set; } = null!;
        public static ConfigEntry<bool> EnableFontUsageDump { get; private set; } = null!;
        public static ConfigEntry<bool> EnableFontDebugLogging { get; private set; } = null!;
        public static ConfigEntry<int> FontDebugSizeOffset { get; private set; } = null!;
        public static ConfigEntry<string> HotReloadKey { get; private set; } = null!;

        public static void Init()
        {
            if (_initialized)
            {
                return;
            }

            string configPath = Path.Combine(Paths.ConfigPath, "ReaperEmporiumLocalization.cfg");
            ConfigFile configFile = new ConfigFile(configPath, true);

            EnableDllDump = configFile.Bind(
                "Developer",
                "EnableDllDump",
                false,
                "Export extracted DLL strings to localization/dump/dll_strings.json."
            );
            EnableDatabaseDump = configFile.Bind(
                "Developer",
                "EnableDatabaseDump",
                false,
                "Export database TSV text to localization/dump/database."
            );
            EnableSceneDump = configFile.Bind(
                "Developer",
                "EnableSceneDump",
                false,
                "Dump current scene Text/UguiNovelText content to localization/dump/scene after scene load."
            );
            EnableFontUsageDump = configFile.Bind(
                "Developer",
                "EnableFontUsageDump",
                false,
                "Continuously record in-game font usage to localization/dump/font_usage.json."
            );
            EnableFontDebugLogging = configFile.Bind(
                "Developer",
                "EnableFontDebugLogging",
                false,
                "Enable extra debug logging for matched Text components during font replacement, including font, size, best fit, and rect information."
            );
            FontDebugSizeOffset = configFile.Bind(
                "Developer",
                "FontDebugSizeOffset",
                0,
                "Debug only: temporary fontSize offset added on top of the current Text.fontSize when a font replacement is applied. Set to 0 to disable."
            );

            EnableFontReplacement = configFile.Bind(
                "Feature",
                "EnableFontReplacement",
                true,
                "Enable runtime font replacement."
            );
            EnableAutoGenerateFontJson = configFile.Bind(
                "Feature",
                "EnableAutoGenerateFontJson",
                false,
                "Automatically generate default font rule json files for sources in localization/fonts that do not already have matching rule files."
            );
            EnableSceneTranslation = configFile.Bind(
                "Feature",
                "EnableSceneTranslation",
                false,
                "Read scene translations from localization/scene/{SceneName}.json and apply them back to the current scene text."
            );

            HotReloadKey = configFile.Bind(
                "HotReload",
                "HotReloadKey",
                "F5",
                "Hot reload key for translations and font rules."
            );

            EnsureDirectories();
            configFile.Save();
            _initialized = true;
        }

        private static void EnsureDirectories()
        {
            string localizationRoot = Path.Combine(Paths.GameRootPath, "localization");
            EnsureDirectory(localizationRoot);
            EnsureDirectory(Path.Combine(localizationRoot, "database"));
            EnsureDirectory(Path.Combine(localizationRoot, "dll_strings"));
            EnsureDirectory(Path.Combine(localizationRoot, "fonts"));
            EnsureDirectory(Path.Combine(localizationRoot, "scene"));

            string dumpRoot = Path.Combine(localizationRoot, "dump");
            EnsureDirectory(dumpRoot);
            EnsureDirectory(Path.Combine(dumpRoot, "database"));
            EnsureDirectory(Path.Combine(dumpRoot, "scene"));
        }

        private static void EnsureDirectory(string path)
        {
            if (!Directory.Exists(path))
            {
                Directory.CreateDirectory(path);
            }
        }
    }
}
