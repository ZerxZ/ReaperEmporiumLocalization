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
            LocalizationConfig.Init();

            // 递归读取 database 文件夹下所有 JSON (不改文件名，默默读原文)
            int dbCount = LoadAllDatabaseTranslations();

            Harmony.CreateAndPatchAll(typeof(Patchers.DatabaseHook));
            // Harmony.CreateAndPatchAll(typeof(Patchers.FontHook)); // 如果有字体补丁取消注释

            Logger.LogInfo($"[REL] 本地化核心引擎已启动！共加载了 {dbCount} 条 Database 翻译原文匹配。");
        }

        private int LoadAllDatabaseTranslations()
        {
            int    totalLoaded = 0;
            string dbFolder    = Path.Combine(Paths.GameRootPath, "localization", "database");

            if (Directory.Exists(dbFolder))
            {
                string[] jsonFiles = Directory.GetFiles(dbFolder, "*.json", SearchOption.AllDirectories);
                foreach (string file in jsonFiles)
                {
                    totalLoaded += TranslationManager.LoadTranslations(file, false);
                }
            }
            return totalLoaded;
        }
    }
}