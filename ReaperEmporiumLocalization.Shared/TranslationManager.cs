using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared.Models;
using BepInEx.Logging;

namespace ReaperEmporiumLocalization.Shared
{
    public static class TranslationManager
    {
        // 🎯 核心改变：使用专门的集合类，告别多层泛型嵌套
        public static TranslationCollection Data { get; } = new TranslationCollection();
        
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.Shared");

        public static int LoadTranslations(string jsonFilePath, bool clearBeforeLoad = false)
        {
            if (clearBeforeLoad) Data.Clear();
            if (!File.Exists(jsonFilePath)) return 0;

            try
            {
                string fileName = Path.GetFileNameWithoutExtension(jsonFilePath);
                string cleanCategory = CleanUpCategoryName(fileName);

                string jsonContent = File.ReadAllText(jsonFilePath, System.Text.Encoding.UTF8);
                var entries = JsonConvert.DeserializeObject<List<ParatranzData>>(jsonContent);
                if (entries == null) return 0;

                int loadedCount = 0;
                foreach (var entry in entries)
                {
                    if (entry.Stage >= StageEnum.已翻译 && 
                        !string.IsNullOrWhiteSpace(entry.Translation) && 
                        !string.IsNullOrWhiteSpace(entry.Original))
                    {
                        string original = entry.Original.Replace("\\n", "\n").Replace("\r", "");
                        string translation = entry.Translation.Replace("\\n", "\n").Replace("\r", "");

                        // 🎯 核心改变：调用对象的 Add 方法，逻辑更清晰
                        if (Data.AddTranslation(cleanCategory, original, translation))
                        {
                            loadedCount++;
                        }
                    }
                }
                return loadedCount;
            }
            catch (Exception ex)
            {
                Logger.LogError($"[REL] 加载 JSON 失败 {jsonFilePath}: {ex.Message}");
                return 0;
            }
        }

        private static string CleanUpCategoryName(string fileName)
        {
            int cabIndex = fileName.IndexOf("-CAB-");
            if (cabIndex > 0) fileName = fileName.Substring(0, cabIndex);

            fileName = Regex.Replace(fileName, @"_\d+$", "");
            return fileName;
        }
    }
}