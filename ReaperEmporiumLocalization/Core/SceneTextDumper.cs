using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
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
    public static class SceneTextDumper
    {
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.SceneDump");
        private static readonly Dictionary<string, Dictionary<string, HashSet<string>>> AwakeContextsByScene =
            new Dictionary<string, Dictionary<string, HashSet<string>>>(StringComparer.OrdinalIgnoreCase);

        public static void RecordAwakeText(Text target)
        {
            if (!LocalizationConfig.EnableSceneDump.Value || !TryBuildSceneEntry(target, out string sceneName, out string original, out string context))
            {
                return;
            }

            AddContext(sceneName, original, context, AwakeContextsByScene);
        }

        public static int DumpScene(Scene scene)
        {
            if (!LocalizationConfig.EnableSceneDump.Value || !scene.IsValid() || string.IsNullOrWhiteSpace(scene.name))
            {
                return 0;
            }

            HashSet<string> excludedOriginals = LoadExcludedOriginals();
            Dictionary<string, HashSet<string>> sceneEntries =
                new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);

            if (AwakeContextsByScene.TryGetValue(scene.name, out Dictionary<string, HashSet<string>> awakeEntries))
            {
                foreach (KeyValuePair<string, HashSet<string>> pair in awakeEntries)
                {
                    foreach (string context in pair.Value)
                    {
                        if (!excludedOriginals.Contains(pair.Key))
                        {
                            AddContext(pair.Key, context, sceneEntries);
                        }
                    }
                }
            }

            foreach (Text text in SceneTextSupport.EnumerateSceneTexts(scene))
            {
                if (!TryBuildSceneEntry(text, out _, out string original, out string context))
                {
                    continue;
                }

                if (excludedOriginals.Contains(original))
                {
                    continue;
                }

                AddContext(original, context, sceneEntries);
            }

            List<ParatranzData> dumpEntries = sceneEntries
                .OrderBy(pair => pair.Key, StringComparer.Ordinal)
                .Select(
                    (pair, index) =>
                        new ParatranzData
                        {
                            Key = index.ToString(),
                            Original = pair.Key,
                            Translation = "",
                            Stage = StageEnum.未翻译,
                            Context = string.Join("\n", pair.Value.OrderBy(item => item, StringComparer.Ordinal)),
                        }
                )
                .ToList();

            string sceneDumpPath = Path.Combine(Paths.GameRootPath, "localization", "dump", "scene", $"{scene.name}.json");
            Directory.CreateDirectory(Path.GetDirectoryName(sceneDumpPath) ?? Path.Combine(Paths.GameRootPath, "localization", "dump", "scene"));
            File.WriteAllText(
                sceneDumpPath,
                JsonConvert.SerializeObject(dumpEntries, Formatting.Indented),
                new UTF8Encoding(false)
            );

            Logger.LogInfo(
                $"[REL] 场景文本导出完成：{scene.name}，写入 {dumpEntries.Count} 条，排除了 {excludedOriginals.Count} 条已在 database/dll_strings 中出现的原文。"
            );
            return dumpEntries.Count;
        }

        private static bool TryBuildSceneEntry(Text target, out string sceneName, out string original, out string context)
        {
            sceneName = string.Empty;
            original = string.Empty;
            context = string.Empty;

            if (target == null)
            {
                return false;
            }

            Scene scene = target.gameObject.scene;
            if (!scene.IsValid() || string.IsNullOrWhiteSpace(scene.name))
            {
                return false;
            }

            string runtimeText = SceneTextSupport.NormalizeRuntimeText(target.text);
            if (string.IsNullOrWhiteSpace(runtimeText) || !SceneTextSupport.ContainsJapanese(runtimeText))
            {
                return false;
            }

            sceneName = scene.name;
            original = SceneTextSupport.EscapeForStorage(runtimeText);
            context = SceneTextSupport.GetObjectDescriptor(target);
            return true;
        }

        private static HashSet<string> LoadExcludedOriginals()
        {
            HashSet<string> excluded = new HashSet<string>(StringComparer.Ordinal);
            string databaseDumpRoot = Path.Combine(Paths.GameRootPath, "localization", "dump", "database");
            if (Directory.Exists(databaseDumpRoot))
            {
                foreach (string filePath in Directory.GetFiles(databaseDumpRoot, "*.json", SearchOption.AllDirectories))
                {
                    CollectOriginalsFromJson(filePath, excluded);
                }
            }
            else
            {
                Logger.LogInfo("[REL] 场景导出时未找到 localization/dump/database，跳过 database 排重。");
            }

            string dllDumpPath = Path.Combine(Paths.GameRootPath, "localization", "dump", "dll_strings.json");
            if (File.Exists(dllDumpPath))
            {
                CollectOriginalsFromJson(dllDumpPath, excluded);
            }
            else
            {
                Logger.LogInfo("[REL] 场景导出时未找到 localization/dump/dll_strings.json，跳过 dll_strings 排重。");
            }

            return excluded;
        }

        private static void CollectOriginalsFromJson(string filePath, HashSet<string> excluded)
        {
            try
            {
                string json = File.ReadAllText(filePath, Encoding.UTF8);
                List<ParatranzData> entries = JsonConvert.DeserializeObject<List<ParatranzData>>(json) ?? new List<ParatranzData>();
                foreach (ParatranzData entry in entries)
                {
                    if (!string.IsNullOrWhiteSpace(entry.Original))
                    {
                        excluded.Add(entry.Original);
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.LogWarning($"[REL] 读取排重文件失败 {filePath}: {ex.Message}");
            }
        }

        private static void AddContext(
            string sceneName,
            string original,
            string context,
            Dictionary<string, Dictionary<string, HashSet<string>>> sceneCache
        )
        {
            if (!sceneCache.TryGetValue(sceneName, out Dictionary<string, HashSet<string>> sceneEntries))
            {
                sceneEntries = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
                sceneCache[sceneName] = sceneEntries;
            }

            AddContext(original, context, sceneEntries);
        }

        private static void AddContext(string original, string context, Dictionary<string, HashSet<string>> entries)
        {
            if (!entries.TryGetValue(original, out HashSet<string> contexts))
            {
                contexts = new HashSet<string>(StringComparer.Ordinal);
                entries[original] = contexts;
            }

            contexts.Add(context);
        }
    }
}
