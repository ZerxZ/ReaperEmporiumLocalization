using System.Collections;
using System.IO;
using BepInEx;
using HarmonyLib;
using ReaperEmporiumLocalization.Core;
using ReaperEmporiumLocalization.Shared;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace ReaperEmporiumLocalization
{
    [BepInPlugin("com.reaperemporium.localization", "Reaper Emporium Localization", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        private bool _fontSceneRefreshRegistered;

        private void Awake()
        {
            LocalizationConfig.Init();

            Logger.LogInfo("[REL] ======= 启动本地化引擎 =======");

            Logger.LogInfo("[REL] [阶段 1/2] 正在全量读取 localization/database 目录下的翻译...");
            int dbCount = LoadAllDatabaseTranslations();
            Logger.LogInfo($"[REL] [阶段 1/2] 完成！已将 {dbCount} 条文本安全载入内存字典。");

            Logger.LogInfo("[REL] [阶段 2/2] 正在挂载底层 API 拦截器...");
            Harmony.CreateAndPatchAll(typeof(Patchers.DatabaseHook));

            if (LocalizationConfig.EnableFontReplacement.Value)
            {
                FontManager.InitFont();
                Harmony.CreateAndPatchAll(typeof(Patchers.FontHook));
                RegisterFontSceneRefresh();

                int patchedTexts = Patchers.FontHook.RefreshAllTexts();
                Logger.LogInfo(
                    $"[REL] 字体替换已启用：发现 {FontManager.LastDiscoveredFontSourceCount} 个字体来源，自动生成 {FontManager.LastGeneratedJsonCount} 个 json，加载 {FontManager.LastLoadedJsonCount} 个规则文件，{FontManager.ReplacementRules.Count} 条规则，已刷新 {patchedTexts} 个文本组件。"
                );
            }
            else
            {
                Logger.LogInfo("[REL] 字体替换未启用，跳过 FontHook 挂载。");
            }

            Logger.LogInfo("[REL] ======= 本地化引擎已全部就绪！ =======");
        }

        private void OnDestroy()
        {
            if (_fontSceneRefreshRegistered)
            {
                SceneManager.sceneLoaded -= OnSceneLoaded;
                _fontSceneRefreshRegistered = false;
            }
        }

        private void Update()
        {
            if (System.Enum.TryParse(LocalizationConfig.HotReloadKey.Value, true, out KeyCode hotkey))
            {
                if (Input.GetKeyDown(hotkey))
                {
                    Logger.LogInfo("[REL] 热重载启动：清空缓存，重新合并字典...");

                    AssetCache.ClearTranslations();

                    string dllPath = Path.Combine(Paths.GameRootPath, "localization", "dll_strings", "dll_strings.json");
                    TranslationManager.LoadTranslations(dllPath, true);
                    LoadAllDatabaseTranslations();

                    if (LocalizationConfig.EnableFontReplacement.Value)
                    {
                        FontManager.Reload();
                        int patchedTexts = Patchers.FontHook.RefreshAllTexts();
                        Logger.LogInfo(
                            $"[REL] 字体规则热重载完成：发现 {FontManager.LastDiscoveredFontSourceCount} 个字体来源，自动生成 {FontManager.LastGeneratedJsonCount} 个 json，加载 {FontManager.LastLoadedJsonCount} 个规则文件，{FontManager.ReplacementRules.Count} 条规则，刷新 {patchedTexts} 个文本组件。"
                        );
                    }

                    Logger.LogInfo("[REL] 热重载完成！");
                }
            }
        }

        private void RegisterFontSceneRefresh()
        {
            if (_fontSceneRefreshRegistered)
            {
                return;
            }

            SceneManager.sceneLoaded += OnSceneLoaded;
            _fontSceneRefreshRegistered = true;
            Logger.LogInfo("[REL] 已注册场景加载后的字体二次刷新。");
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            if (!LocalizationConfig.EnableFontReplacement.Value)
            {
                return;
            }

            Logger.LogInfo($"[REL] 场景加载完成，准备延迟刷新字体：{scene.name}（{mode}）");
            StartCoroutine(RefreshFontsAfterSceneLoad(scene.name));
        }

        private IEnumerator RefreshFontsAfterSceneLoad(string sceneName)
        {
            yield return null;
            yield return null;

            int patchedTexts = Patchers.FontHook.RefreshAllTexts();
            Logger.LogInfo(
                $"[REL] 场景 {sceneName} 的字体二次刷新完成：当前 {FontManager.ReplacementRules.Count} 条规则，刷新 {patchedTexts} 个文本组件。"
            );
        }

        private int LoadAllDatabaseTranslations()
        {
            int totalLoaded = 0;
            string dbFolder = Path.Combine(Paths.GameRootPath, "localization", "database");

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
