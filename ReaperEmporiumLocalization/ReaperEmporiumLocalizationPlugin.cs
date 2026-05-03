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
        private bool _sceneWorkflowRegistered;

        private bool NeedRuntimeTextHook =>
            LocalizationConfig.EnableFontReplacement.Value ||
            LocalizationConfig.EnableSceneDump.Value ||
            LocalizationConfig.EnableSceneTranslation.Value ||
            LocalizationConfig.EnableFontUsageDump.Value;

        private void Awake()
        {
            LocalizationConfig.Init();

            Logger.LogInfo("[REL] ======= 启动本地化引擎 =======");

            Logger.LogInfo("[REL] [阶段 1/2] 正在读取 localization/database 下的翻译...");
            int dbCount = LoadAllDatabaseTranslations();
            Logger.LogInfo($"[REL] [阶段 1/2] 完成，已加载 {dbCount} 条数据库翻译。");

            Logger.LogInfo("[REL] [阶段 2/2] 正在挂载运行时补丁...");
            Harmony.CreateAndPatchAll(typeof(Patchers.DatabaseHook));

            if (LocalizationConfig.EnableFontReplacement.Value)
            {
                FontManager.InitFont();
                Logger.LogInfo(
                    $"[REL] 字体规则初始化完成：发现 {FontManager.LastDiscoveredFontSourceCount} 个字体来源，自动生成 {FontManager.LastGeneratedJsonCount} 个 json，加载 {FontManager.LastLoadedJsonCount} 个规则文件，共 {FontManager.ReplacementRules.Count} 条规则。"
                );
            }
            else
            {
                Logger.LogInfo("[REL] 字体替换未启用，跳过字体规则初始化。");
            }

            if (NeedRuntimeTextHook)
            {
                Harmony.CreateAndPatchAll(typeof(Patchers.FontHook));
                Logger.LogInfo("[REL] 已挂载 UguiNovelText.Awake 运行时补丁。");
                RegisterSceneWorkflow();

                Scene activeScene = SceneManager.GetActiveScene();
                if (activeScene.IsValid())
                {
                    StartCoroutine(ProcessSceneAfterLoad(activeScene, "启动时"));
                }
            }
            else
            {
                Logger.LogInfo("[REL] 未启用场景文本/字体相关功能，跳过 UguiNovelText.Awake 补丁与场景工作流。");
            }

            Logger.LogInfo("[REL] ======= 本地化引擎已全部就绪 =======");
        }

        private void OnDestroy()
        {
            if (_sceneWorkflowRegistered)
            {
                SceneManager.sceneLoaded -= OnSceneLoaded;
                _sceneWorkflowRegistered = false;
            }
        }

        private void Update()
        {
            if (System.Enum.TryParse(LocalizationConfig.HotReloadKey.Value, true, out KeyCode hotkey) &&
                Input.GetKeyDown(hotkey))
            {
                HandleHotReload();
            }
        }

        private void HandleHotReload()
        {
            Logger.LogInfo("[REL] 热重载启动：正在重新读取翻译与场景规则...");

            AssetCache.ClearTranslations();

            string dllPath = Path.Combine(Paths.GameRootPath, "localization", "dll_strings", "dll_strings.json");
            TranslationManager.LoadTranslations(dllPath, true);
            int dbCount = LoadAllDatabaseTranslations();

            if (LocalizationConfig.EnableFontReplacement.Value)
            {
                FontManager.Reload();
                Logger.LogInfo(
                    $"[REL] 字体规则热重载完成：发现 {FontManager.LastDiscoveredFontSourceCount} 个字体来源，自动生成 {FontManager.LastGeneratedJsonCount} 个 json，加载 {FontManager.LastLoadedJsonCount} 个规则文件，共 {FontManager.ReplacementRules.Count} 条规则。"
                );
            }

            if (LocalizationConfig.EnableSceneTranslation.Value)
            {
                SceneTextTranslator.Reload();
                Logger.LogInfo("[REL] 场景文本翻译缓存已清空，将在 UguiNovelText.Awake 时按需重新读取 localization/scene。");
            }

            if (NeedRuntimeTextHook)
            {
                Scene activeScene = SceneManager.GetActiveScene();
                if (activeScene.IsValid())
                {
                    StartCoroutine(ProcessSceneAfterLoad(activeScene, "热重载后"));
                }
            }

            Logger.LogInfo($"[REL] 热重载完成：重新加载数据库翻译 {dbCount} 条。");
        }

        private void RegisterSceneWorkflow()
        {
            if (_sceneWorkflowRegistered)
            {
                return;
            }

            SceneManager.sceneLoaded += OnSceneLoaded;
            _sceneWorkflowRegistered = true;
            Logger.LogInfo("[REL] 已注册场景加载后的场景文本/字体处理流程。");
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            if (!NeedRuntimeTextHook)
            {
                return;
            }

            Logger.LogInfo($"[REL] 场景加载完成，准备延迟处理：{scene.name} ({mode})");
            StartCoroutine(ProcessSceneAfterLoad(scene, "场景加载后"));
        }

        private IEnumerator ProcessSceneAfterLoad(Scene scene, string reason)
        {
            yield return null;
            yield return null;

            if (!scene.IsValid())
            {
                yield break;
            }

            int fontUsageCount = 0;
            int dumpedCount = 0;
            int refreshedCount = 0;

            if (LocalizationConfig.EnableFontUsageDump.Value)
            {
                fontUsageCount = FontUsageRecorder.RecordScene(scene);
            }

            if (LocalizationConfig.EnableSceneDump.Value)
            {
                dumpedCount = SceneTextDumper.DumpScene(scene);
            }

            if (LocalizationConfig.EnableFontReplacement.Value)
            {
                refreshedCount = Patchers.FontHook.RefreshAllTexts();
            }

            Logger.LogInfo(
                $"[REL] {reason}处理完成：场景={scene.name}，字体记录新增 {fontUsageCount} 条，场景导出 {dumpedCount} 条，UguiNovelText.Awake 场景回写按需触发，字体刷新 {refreshedCount} 个组件。"
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
