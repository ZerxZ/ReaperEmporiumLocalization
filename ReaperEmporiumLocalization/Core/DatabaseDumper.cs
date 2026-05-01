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

            // 🎯 核心修复：在此处加上 "database" 层级，保持与读取目录的绝对对称
            string dumpDir = Path.Combine(Paths.GameRootPath, "localization", "dump", "database");
            if (!Directory.Exists(dumpDir)) Directory.CreateDirectory(dumpDir);

            // 导出的文件名绝对纯净，如 db_EventInfo.json
            string dumpPath = Path.Combine(dumpDir, $"{assetName}.json");

            // 如果文件已存在，说明之前提取过，跳过以节省性能
            if (File.Exists(dumpPath)) return;

            List<ParatranzData> dumpList = new List<ParatranzData>();
            string[] lines = text.Split(new[] { "\r\n", "\n" }, System.StringSplitOptions.None);

            for (int i = 0; i < lines.Length; i++)
            {
                if (string.IsNullOrEmpty(lines[i])) continue;

                string[] cells = lines[i].Split('\t');
                string rowId = cells.Length > 0 ? cells[0] : "UNKNOWN";

                for (int j = 0; j < cells.Length; j++)
                {
                    string cellText = cells[j];
                    if (!string.IsNullOrWhiteSpace(cellText) && JapaneseRegex.IsMatch(cellText))
                    {
                        // 生成唯一 Key，仅供 Paratranz 网站做记忆库绑定使用
                        string entryKey = $"{assetName}_{rowId}_{j}";
                        string cleanOriginal = cellText.Replace("\r", "").Replace("\n", "\\n");

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
                Debug.Log($"[REL.Dumper] 成功提取表格并保存至: database/{assetName}.json");
            }
        }
    }
}