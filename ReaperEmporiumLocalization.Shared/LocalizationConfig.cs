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
                "是否将 DLL 中提取到的日文文本导出到 localization/dump/dll_strings.json。"
            );
            EnableDatabaseDump = configFile.Bind(
                "Developer",
                "EnableDatabaseDump",
                false,
                "是否将数据库 TSV 文本导出到 localization/dump/database。"
            );
            EnableSceneDump = configFile.Bind(
                "Developer",
                "EnableSceneDump",
                false,
                "是否在切场景后导出当前场景中的 Text/UguiNovelText 到 localization/dump/scene。"
            );
            EnableFontUsageDump = configFile.Bind(
                "Developer",
                "EnableFontUsageDump",
                false,
                "是否持续记录本体字体使用情况到 localization/dump/font_usage.json。"
            );

            EnableFontReplacement = configFile.Bind(
                "Feature",
                "EnableFontReplacement",
                true,
                "是否启用字体替换。"
            );
            EnableAutoGenerateFontJson = configFile.Bind(
                "Feature",
                "EnableAutoGenerateFontJson",
                false,
                "是否在扫描 localization/fonts 时，为缺失规则的字体源自动生成同名 json 模板。"
            );
            EnableSceneTranslation = configFile.Bind(
                "Feature",
                "EnableSceneTranslation",
                false,
                "是否从 localization/scene/{SceneName}.json 读取翻译并回写当前场景文本。"
            );

            HotReloadKey = configFile.Bind(
                "HotReload",
                "HotReloadKey",
                "F5",
                "运行时热重载翻译与字体规则的按键。"
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
