using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared.Models;
using BepInEx.Logging;

namespace ReaperEmporiumLocalization.Shared
{
    public static class TranslationManager
    {
        // 🎯 核心：字典的 Key 直接使用日文原文
        public static Dictionary<string, string> Dictionary { get; private set; } = new Dictionary<string, string>();
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.Shared");

        public static int LoadTranslations(string jsonFilePath, bool clearBeforeLoad = false)
        {
            if (clearBeforeLoad) Dictionary.Clear();
            if (!File.Exists(jsonFilePath)) return 0;

            try
            {
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
                        // 统一换行符标准，防止转义字符导致匹配失败
                        string original = entry.Original.Replace("\\n", "\n").Replace("\r", "");
                        string translation = entry.Translation.Replace("\\n", "\n").Replace("\r", "");

                        if (!Dictionary.ContainsKey(original))
                        {
                            Dictionary[original] = translation;
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
    }
}