using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared;
using ReaperEmporiumLocalization.Shared.Models;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace ReaperEmporiumLocalization.Core
{
    public static class SceneTextTranslator
    {
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.SceneText");
        private static readonly Dictionary<string, Dictionary<string, string>> CachedSceneTranslations =
            new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);

        public static void Reload()
        {
            CachedSceneTranslations.Clear();
        }

        public static int ApplyScene(Scene scene)
        {
            if (!LocalizationConfig.EnableSceneTranslation.Value || !scene.IsValid() || string.IsNullOrWhiteSpace(scene.name))
            {
                return 0;
            }

            int changedCount = 0;
            foreach (Text text in SceneTextSupport.EnumerateSceneTexts(scene))
            {
                if (TryApplyToText(text))
                {
                    changedCount++;
                }
            }

            Logger.LogInfo($"[REL] 场景文本回写完成：{scene.name}，替换 {changedCount} 个 Text/UguiNovelText。");
            return changedCount;
        }

        public static bool TryApplyToText(Text target)
        {
            if (!LocalizationConfig.EnableSceneTranslation.Value || target == null)
            {
                return false;
            }

            Scene scene = target.gameObject.scene;
            if (!scene.IsValid() || string.IsNullOrWhiteSpace(scene.name))
            {
                return false;
            }

            string original = SceneTextSupport.NormalizeRuntimeText(target.text);
            if (string.IsNullOrWhiteSpace(original))
            {
                return false;
            }

            Dictionary<string, string> translations = GetSceneTranslations(scene.name);
            if (!translations.TryGetValue(original, out string translation) || string.IsNullOrWhiteSpace(translation))
            {
                return false;
            }

            if (target.text == translation)
            {
                return false;
            }

            target.text = translation;
            return true;
        }

        private static Dictionary<string, string> GetSceneTranslations(string sceneName)
        {
            if (CachedSceneTranslations.TryGetValue(sceneName, out Dictionary<string, string> cachedTranslations))
            {
                return cachedTranslations;
            }

            Dictionary<string, string> sceneTranslations = new Dictionary<string, string>(StringComparer.Ordinal);
            string sceneFilePath = Path.Combine(Paths.GameRootPath, "localization", "scene", $"{sceneName}.json");

            if (!File.Exists(sceneFilePath))
            {
                CachedSceneTranslations[sceneName] = sceneTranslations;
                return sceneTranslations;
            }

            try
            {
                string json = File.ReadAllText(sceneFilePath, Encoding.UTF8);
                List<ParatranzData> entries = JsonConvert.DeserializeObject<List<ParatranzData>>(json) ?? new List<ParatranzData>();
                foreach (ParatranzData entry in entries)
                {
                    if (entry.Stage < StageEnum.已翻译 ||
                        string.IsNullOrWhiteSpace(entry.Original) ||
                        string.IsNullOrWhiteSpace(entry.Translation))
                    {
                        continue;
                    }

                    string original = SceneTextSupport.UnescapeStoredText(entry.Original);
                    string translation = SceneTextSupport.UnescapeStoredText(entry.Translation);
                    if (string.IsNullOrWhiteSpace(original) || string.IsNullOrWhiteSpace(translation))
                    {
                        continue;
                    }

                    if (!sceneTranslations.ContainsKey(original))
                    {
                        sceneTranslations[original] = translation;
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.LogError($"[REL] 读取场景翻译失败 {sceneFilePath}: {ex.Message}");
            }

            CachedSceneTranslations[sceneName] = sceneTranslations;
            return sceneTranslations;
        }
    }
}
