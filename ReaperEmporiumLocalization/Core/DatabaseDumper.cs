using System;
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
        private static readonly object FilterLock = new object();
        private static readonly HashSet<string> WarnedInvalidRegex = new HashSet<string>();
        private static readonly HashSet<string> LoggedSkippedAssets = new HashSet<string>();
        private static DatabaseDumpFilterConfig? filterConfig;
        private static DateTime filterConfigLastWriteUtc;

        public static void DumpTsvToJson(string bundleName, string assetName, string text)
        {
            if (string.IsNullOrEmpty(text)) return;
            if (ShouldSkipAsset(assetName))
            {
                LogSkippedAssetOnce(assetName);
                return;
            }

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

        public static void EnsureDefaultFilterConfig()
        {
            string configPath = GetFilterConfigPath();
            lock (FilterLock)
            {
                try
                {
                    EnsureFilterConfigFile(configPath);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[REL.Dumper] 生成 database_dump_filter.json 默认配置失败：{ex.Message}");
                }
            }
        }

        private static bool ShouldSkipAsset(string assetName)
        {
            if (string.IsNullOrEmpty(assetName))
            {
                return false;
            }

            DatabaseDumpFilterConfig config = LoadFilterConfig();
            if (config.ExcludedAssetNames.Contains(assetName))
            {
                return true;
            }

            foreach (string pattern in config.ExcludedAssetNameRegex)
            {
                if (string.IsNullOrWhiteSpace(pattern))
                {
                    continue;
                }

                try
                {
                    if (Regex.IsMatch(assetName, pattern))
                    {
                        return true;
                    }
                }
                catch (ArgumentException ex)
                {
                    WarnInvalidRegexOnce(pattern, ex);
                }
            }

            return false;
        }

        private static DatabaseDumpFilterConfig LoadFilterConfig()
        {
            string configPath = GetFilterConfigPath();
            lock (FilterLock)
            {
                try
                {
                    EnsureFilterConfigFile(configPath);
                    DateTime lastWriteUtc = File.GetLastWriteTimeUtc(configPath);
                    if (filterConfig != null && lastWriteUtc == filterConfigLastWriteUtc)
                    {
                        return filterConfig;
                    }

                    string json = File.ReadAllText(configPath, System.Text.Encoding.UTF8);
                    filterConfig = JsonConvert.DeserializeObject<DatabaseDumpFilterConfig>(json) ?? new DatabaseDumpFilterConfig();
                    filterConfig.Normalize();
                    filterConfigLastWriteUtc = lastWriteUtc;
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[REL.Dumper] 读取 database_dump_filter.json 失败，将不启用数据库过滤：{ex.Message}");
                    filterConfig = DatabaseDumpFilterConfig.Empty();
                    filterConfigLastWriteUtc = File.Exists(configPath) ? File.GetLastWriteTimeUtc(configPath) : DateTime.MinValue;
                }

                return filterConfig;
            }
        }

        private static void EnsureFilterConfigFile(string configPath)
        {
            string? configDir = Path.GetDirectoryName(configPath);
            if (!string.IsNullOrEmpty(configDir) && !Directory.Exists(configDir))
            {
                Directory.CreateDirectory(configDir);
            }

            if (File.Exists(configPath))
            {
                return;
            }

            DatabaseDumpFilterConfig template = new DatabaseDumpFilterConfig();
            string json = JsonConvert.SerializeObject(template, Formatting.Indented);
            File.WriteAllText(configPath, json, System.Text.Encoding.UTF8);
            Debug.Log($"[REL.Dumper] 已生成数据库导出过滤配置模板：{configPath}");
        }

        private static string GetFilterConfigPath()
        {
            return Path.Combine(Paths.GameRootPath, "localization", "config", "database_dump_filter.json");
        }

        private static void WarnInvalidRegexOnce(string pattern, ArgumentException ex)
        {
            lock (FilterLock)
            {
                if (!WarnedInvalidRegex.Add(pattern))
                {
                    return;
                }
            }

            Debug.LogWarning($"[REL.Dumper] database_dump_filter.json 正则无效，已忽略：{pattern} ({ex.Message})");
        }

        private static void LogSkippedAssetOnce(string assetName)
        {
            lock (FilterLock)
            {
                if (!LoggedSkippedAssets.Add(assetName))
                {
                    return;
                }
            }

            Debug.Log($"[REL.Dumper] 已按 database_dump_filter.json 跳过数据库导出：assetName={assetName}");
        }

        private sealed class DatabaseDumpFilterConfig
        {
            [JsonProperty("excluded_asset_names")]
            public HashSet<string> ExcludedAssetNames { get; set; } = new HashSet<string>
            {
                "db_Direct",
                "db_VoiceChara",
                "db_ResourceSoundBgmUse",
                "db_ResourceSoundSeUse"
            };

            [JsonProperty("excluded_asset_name_regex")]
            public List<string> ExcludedAssetNameRegex { get; set; } = new List<string>
            {
                "^db_Image"
            };

            public void Normalize()
            {
                ExcludedAssetNames ??= new HashSet<string>();
                ExcludedAssetNameRegex ??= new List<string>();
            }

            public static DatabaseDumpFilterConfig Empty()
            {
                return new DatabaseDumpFilterConfig
                {
                    ExcludedAssetNames = new HashSet<string>(),
                    ExcludedAssetNameRegex = new List<string>()
                };
            }
        }
    }
}
