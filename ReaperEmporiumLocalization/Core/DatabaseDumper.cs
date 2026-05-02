using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using BepInEx;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared.Models;
using UnityEngine;

namespace ReaperEmporiumLocalization.Core
{
    public static class DatabaseDumper
    {
        private static readonly Regex JapaneseRegex = new Regex(@"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]");

        public static void DumpTsvToJson(string bundleName, string assetName, string text)
        {
            if (string.IsNullOrEmpty(text)) return;

            // 数据库转储必须保留 bundleName 层级，保持与运行时 database/{bundleName}/{assetName} 对称。
            string dumpDir = Path.Combine(Paths.GameRootPath, "localization", "dump", "database", bundleName);
            if (!Directory.Exists(dumpDir)) Directory.CreateDirectory(dumpDir);

            // 导出的文件名绝对纯净，如 db_EventInfo.json
            string dumpPath = Path.Combine(dumpDir, $"{assetName}.json");

            // 如果文件已存在，说明之前提取过，跳过以节省性能
            if (File.Exists(dumpPath)) return;

            List<ParatranzData> dumpList = new List<ParatranzData>();
            HashSet<string> seenOriginals = new HashSet<string>();
            string[] lines = text.Split(new[] { "\r\n", "\n" }, System.StringSplitOptions.None);

            for (int i = 0; i < lines.Length; i++)
            {
                if (string.IsNullOrEmpty(lines[i])) continue;

                string[] cells = lines[i].Split('\t');

                for (int j = 0; j < cells.Length; j++)
                {
                    string cellText = cells[j];
                    if (!string.IsNullOrWhiteSpace(cellText) && JapaneseRegex.IsMatch(cellText))
                    {
                        string cleanOriginal = cellText.Replace("\r", "").Replace("\n", "\\n");
                        if (!seenOriginals.Add(cleanOriginal)) continue;

                        // 数据库转储 key 只使用当前 JSON 文件内的递增索引：0, 1, 2...
                        string entryKey = dumpList.Count.ToString();

                        dumpList.Add(new ParatranzData
                        {
                            Key = entryKey,
                            Original = cleanOriginal,
                            Translation = "",
                            Stage = StageEnum.未翻译,
                            Context = ""
                        });
                    }
                }
            }

            if (dumpList.Count > 0)
            {
                File.WriteAllText(dumpPath, JsonConvert.SerializeObject(dumpList, Formatting.Indented), System.Text.Encoding.UTF8);
                // 日志也同步修改，方便在控制台确认层级
                Debug.Log($"[REL.Dumper] 成功提取表格并保存至: database/{bundleName}/{assetName}.json");
            }
        }
    }
}
