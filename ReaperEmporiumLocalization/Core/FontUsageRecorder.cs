using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace ReaperEmporiumLocalization.Core
{
    public static class FontUsageRecorder
    {
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.FontUsage");
        private static readonly Dictionary<string, HashSet<string>> UsageByFont =
            new Dictionary<string, HashSet<string>>(System.StringComparer.OrdinalIgnoreCase);

        public static bool RecordText(Text target)
        {
            if (!LocalizationConfig.EnableFontUsageDump.Value)
            {
                return false;
            }

            bool added = RecordTextInternal(target);
            if (added)
            {
                WriteSnapshot();
            }

            return added;
        }

        public static int RecordScene(Scene scene)
        {
            if (!LocalizationConfig.EnableFontUsageDump.Value || !scene.IsValid())
            {
                return 0;
            }

            int addedCount = 0;
            foreach (Text text in SceneTextSupport.EnumerateSceneTexts(scene))
            {
                if (SceneTextSupport.IsNovelText(text))
                {
                    continue;
                }

                if (RecordTextInternal(text))
                {
                    addedCount++;
                }
            }

            if (addedCount > 0)
            {
                WriteSnapshot();
                Logger.LogInfo($"[REL] 字体使用记录已更新：场景 {scene.name} 新增 {addedCount} 条对象记录。");
            }

            return addedCount;
        }

        private static bool RecordTextInternal(Text target)
        {
            if (target == null || target.font == null)
            {
                return false;
            }

            string fontName = SceneTextSupport.NormalizeFontName(target.font.name);
            if (string.IsNullOrWhiteSpace(fontName))
            {
                return false;
            }

            string descriptor = SceneTextSupport.GetObjectDescriptor(target);
            if (string.IsNullOrWhiteSpace(descriptor))
            {
                return false;
            }

            if (!UsageByFont.TryGetValue(fontName, out HashSet<string> objects))
            {
                objects = new HashSet<string>(System.StringComparer.Ordinal);
                UsageByFont[fontName] = objects;
            }

            bool added = objects.Add(descriptor);
            if (added)
            {
                Logger.LogInfo($"[REL] 记录本体字体：{fontName} -> {descriptor}");
            }

            return added;
        }

        private static void WriteSnapshot()
        {
            Dictionary<string, List<string>> snapshot = UsageByFont
                .OrderBy(pair => pair.Key, System.StringComparer.OrdinalIgnoreCase)
                .ToDictionary(
                    pair => pair.Key,
                    pair => pair.Value.OrderBy(item => item, System.StringComparer.Ordinal).ToList(),
                    System.StringComparer.OrdinalIgnoreCase
                );

            string outputPath = Path.Combine(Paths.GameRootPath, "localization", "dump", "font_usage.json");
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? Path.Combine(Paths.GameRootPath, "localization", "dump"));
            File.WriteAllText(outputPath, JsonConvert.SerializeObject(snapshot, Formatting.Indented), new UTF8Encoding(false));
        }
    }
}
