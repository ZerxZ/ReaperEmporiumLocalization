using System.IO;
using BepInEx;
using BepInEx.Configuration;

namespace ReaperEmporiumLocalization.Shared
{
    public static class LocalizationConfig
    {
        public static ConfigEntry<bool> EnableDllDump      { get; private set; } = null!;
        public static ConfigEntry<bool> EnableDatabaseDump { get; private set; } = null!;
        public static ConfigEntry<bool> EnableFontReplacement { get; private set; } = null!;
        
        // 【关键修改】使用普通 string 替代 UnityEngine.KeyCode
        public static ConfigEntry<string> HotReloadKey { get; private set; } = null!;

        private static bool _isInitialized = false;

        public static void Init()
        {
            if (_isInitialized) return;

            string     configPath = Path.Combine(Paths.ConfigPath, "ReaperEmporiumLocalization.cfg");
            ConfigFile config     = new ConfigFile(configPath, true);

            EnableDllDump = config.Bind("Developer",      "EnableDllDump",      false, "【开发者】是否开启 DLL 硬编码日文文本提取？");
            EnableDatabaseDump = config.Bind("Developer", "EnableDatabaseDump", false, "【开发者】是否开启 AssetBundle 原版数据库文本提取？");
            EnableFontReplacement = config.Bind("Feature", "EnableFontReplacement", true, "是否启用 localization/fonts 下的字体替换规则？");
            
            // 默认值改为字符串 "F5"
            HotReloadKey = config.Bind("Developer", "HotReloadKey", "F5", "【开发者】热重载快捷键名称 (如 F5, F6, F12)");
            // ==========================================
            // 🎯 新增：自动创建汉化注入区文件夹骨架
            // ==========================================
            string rootPath       = Path.Combine(Paths.GameRootPath, "localization");
            string dllStringsPath = Path.Combine(rootPath,           "dll_strings");
            string databasePath   = Path.Combine(rootPath,           "database");
            string fontsPath      = Path.Combine(rootPath,           "fonts"); // 新增字体文件夹路径

            // 一次性生成所有注入区文件夹
            if (!Directory.Exists(dllStringsPath)) Directory.CreateDirectory(dllStringsPath);
            if (!Directory.Exists(databasePath)) Directory.CreateDirectory(databasePath);
            if (!Directory.Exists(fontsPath)) Directory.CreateDirectory(fontsPath); // 新增创建逻辑
            _isInitialized = true;
        }
    }
}
