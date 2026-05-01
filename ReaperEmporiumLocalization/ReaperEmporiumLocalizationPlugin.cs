using System.IO;
using BepInEx;
using HarmonyLib;
using ReaperEmporiumLocalization.Core;
using ReaperEmporiumLocalization.Shared;
using UnityEngine;

namespace ReaperEmporiumLocalization
{
    [BepInPlugin("com.reaperemporium.localization", "Reaper Emporium Localization", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        private void Awake()
        {
            // 0. 基础配置初始化
            LocalizationConfig.Init();

            Logger.LogInfo("[REL] ======= 启动本地化引擎 =======");

            // ==========================================
            // 🎯 阶段一：绝对优先全量加载 JSON
            // 在这一步完成前，绝对不会启动任何拦截器
            // ==========================================
            Logger.LogInfo("[REL] [阶段 1/2] 正在全量读取 localization/database 目录下的翻译...");
            int dbCount = LoadAllDatabaseTranslations();
            Logger.LogInfo($"[REL] [阶段 1/2] 完成！已将 {dbCount} 条文本安全载入内存字典。");

            // ==========================================
            // 🎯 阶段二：内存就绪后，启动 Hook 替换
            // ==========================================
            Logger.LogInfo("[REL] [阶段 2/2] 正在挂载底层 API 拦截器...");
            
            // 启动 Database 拦截
            Harmony.CreateAndPatchAll(typeof(Patchers.DatabaseHook));
            
            // 如果启用了字体替换，取消下面的注释
            // Harmony.CreateAndPatchAll(typeof(Patchers.FontHook)); 

            Logger.LogInfo("[REL] ======= 本地化引擎已全部就绪！ =======");
        }

        private void Update()
        {
            // F5 热重载逻辑保持不变
            if (System.Enum.TryParse(LocalizationConfig.HotReloadKey.Value, true, out KeyCode hotkey))
            {
                if (Input.GetKeyDown(hotkey))
                {
                    Logger.LogInfo("[REL] 热重载启动：清空缓存，重新合并字典...");
                    
                    AssetCache.ClearTranslations();
                    
                    // 重新加载 DLL 翻译 (清空旧字典)
                    string dllPath = Path.Combine(Paths.GameRootPath, "localization", "dll_strings", "dll_strings.json");
                    TranslationManager.LoadTranslations(dllPath, true); 

                    // 重新全量加载 Database 翻译 (追加模式)
                    LoadAllDatabaseTranslations(); 

                    Logger.LogInfo("[REL] 热重载完成！");
                }
            }
        }

        /// <summary>
        /// 递归扫描并读取所有 Database JSON 文件
        /// </summary>
        private int LoadAllDatabaseTranslations()
        {
            int totalLoaded = 0;
            string dbFolder = Path.Combine(Paths.GameRootPath, "localization", "database");

            if (Directory.Exists(dbFolder))
            {
                // 无脑递归读取所有 json
                string[] jsonFiles = Directory.GetFiles(dbFolder, "*.json", SearchOption.AllDirectories);
                foreach (string file in jsonFiles)
                {
                    // false 代表不自动清空字典，因为要将多个文件的翻译合并到同一个大字典里
                    totalLoaded += TranslationManager.LoadTranslations(file, false); 
                }
            }
            return totalLoaded;
        }
    }
}