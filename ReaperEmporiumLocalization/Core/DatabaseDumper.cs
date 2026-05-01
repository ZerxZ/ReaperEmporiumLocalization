using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using BepInEx;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared.Models;

namespace ReaperEmporiumLocalization.Core
{
    public static class DatabaseDumper
    {
        private static readonly Regex JapaneseRegex = new Regex(@"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]");

        public static void DumpTsvToJson(string bundleName, string assetName, string originalText)
        {
            if (string.IsNullOrWhiteSpace(originalText) || !JapaneseRegex.IsMatch(originalText)) return;

            string dumpPath = Path.Combine(Paths.GameRootPath, "localization", "dump", "database", bundleName, $"{assetName}.json");
            Dictionary<string, ParatranzData> localData = new Dictionary<string, ParatranzData>();

            string[] lines = originalText.Split(new[] { "\r\n", "\n" }, System.StringSplitOptions.None);
            foreach (var line in lines)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;

                string[] cells = line.Split('\t');
                string rowId = cells.Length > 0 ? cells[0] : "UNKNOWN";

                for (int j = 1; j < cells.Length; j++)
                {
                    string cellText = cells[j];
                    if (!string.IsNullOrWhiteSpace(cellText) && JapaneseRegex.IsMatch(cellText))
                    {
                        // 🎯 核心修改：生成相同的坐标 Key，彻底抛弃 MD5
                        string coordinateKey = $"{assetName}_{rowId}_{j}";
                        string cleanText = cellText.Replace("\r\n", "\\n").Replace("\n", "\\n");

                        if (!localData.ContainsKey(coordinateKey))
                        {
                            localData[coordinateKey] = new ParatranzData
                            {
                                Key = coordinateKey,
                                Original = cleanText,
                                Translation = "",
                                Stage = StageEnum.未翻译,
                                Context = ""
                            };
                        }
                    }
                }
            }

            if (localData.Count > 0)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(dumpPath));
                var dataList = localData.Values.OrderBy(d => d.Key).ToList();
                File.WriteAllText(dumpPath, JsonConvert.SerializeObject(dataList, Formatting.Indented), Encoding.UTF8);
            }
        }
    }
}