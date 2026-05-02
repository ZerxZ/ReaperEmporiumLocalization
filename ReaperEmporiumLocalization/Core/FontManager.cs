using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared.Models;
using UnityEngine;
using UnityEngine.UI;

namespace ReaperEmporiumLocalization.Core
{
    public class FontReplacementRule
    {
        public Font CustomFont { get; set; } = null!;
        public FontStyle Style { get; set; } = FontStyle.Normal;
    }

    public static class FontManager
    {
        public static readonly Dictionary<string, FontReplacementRule> ReplacementRules =
            new Dictionary<string, FontReplacementRule>(StringComparer.OrdinalIgnoreCase);

        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.Fonts");
        private static readonly string[] SupportedBundleExtensions = { "", ".ab", ".bundle" };
        private static bool _isInitialized = false;

        public static void InitFont()
        {
            if (_isInitialized) return;
            LoadRules();
        }

        public static void Reload()
        {
            LoadRules();
        }

        public static bool TryApply(Text target)
        {
            if (target == null || target.font == null) return false;

            InitFont();

            if (!TryGetRule(target.font.name, out FontReplacementRule? rule) || rule?.CustomFont == null)
            {
                return false;
            }

            bool changed = false;

            if (target.font != rule.CustomFont)
            {
                target.font = rule.CustomFont;
                changed = true;
            }

            if (target.fontStyle != rule.Style)
            {
                target.fontStyle = rule.Style;
                changed = true;
            }

            return changed;
        }

        private static void LoadRules()
        {
            ReplacementRules.Clear();

            string fontsDir = Path.Combine(Paths.GameRootPath, "localization", "fonts");
            Logger.LogInfo($"[REL] 扫描字体目录：{fontsDir}");

            if (!Directory.Exists(fontsDir))
            {
                Directory.CreateDirectory(fontsDir);
                Logger.LogInfo("[REL] 字体目录不存在，已自动创建 localization/fonts。");
                _isInitialized = true;
                return;
            }

            string[] jsonFiles = Directory.GetFiles(fontsDir, "*.json");
            Array.Sort(jsonFiles, StringComparer.OrdinalIgnoreCase);

            if (jsonFiles.Length == 0)
            {
                Logger.LogInfo("[REL] 未找到字体规则 JSON，跳过字体替换规则加载。");
                _isInitialized = true;
                return;
            }

            Dictionary<string, Font?> bundleCache = new Dictionary<string, Font?>(StringComparer.OrdinalIgnoreCase);
            int loadedJsonCount = 0;

            foreach (string jsonPath in jsonFiles)
            {
                string bundleName = Path.GetFileNameWithoutExtension(jsonPath);
                string? bundlePath = ResolveBundlePath(fontsDir, bundleName);

                if (bundlePath == null)
                {
                    Logger.LogWarning($"[REL] 字体规则 {Path.GetFileName(jsonPath)} 未找到对应字体包，支持无后缀、.ab、.bundle。");
                    continue;
                }

                try
                {
                    string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
                    List<FontConfig>? configs = JsonConvert.DeserializeObject<List<FontConfig>>(jsonContent);
                    if (configs == null || configs.Count == 0)
                    {
                        Logger.LogWarning($"[REL] 字体规则 {Path.GetFileName(jsonPath)} 为空，已跳过。");
                        continue;
                    }

                    if (!bundleCache.TryGetValue(bundlePath, out Font? targetFont))
                    {
                        targetFont = LoadFontFromAssetBundle(bundlePath);
                        bundleCache[bundlePath] = targetFont;
                    }

                    if (targetFont == null)
                    {
                        Logger.LogWarning($"[REL] 字体包加载失败：{bundlePath}");
                        continue;
                    }

                    int rulesBefore = ReplacementRules.Count;
                    foreach (FontConfig config in configs)
                    {
                        if (!Enum.TryParse(config.FontStyleStr, true, out FontStyle parsedStyle))
                        {
                            Logger.LogWarning($"[REL] 字体样式 {config.FontStyleStr} 无效，已回退为 Normal。");
                            parsedStyle = FontStyle.Normal;
                        }

                        foreach (string targetName in EnumerateTargetFontNames(config))
                        {
                            ReplacementRules[targetName] = new FontReplacementRule
                            {
                                CustomFont = targetFont,
                                Style = parsedStyle,
                            };
                        }
                    }

                    int addedRules = ReplacementRules.Count - rulesBefore;
                    loadedJsonCount++;
                    Logger.LogInfo(
                        $"[REL] 已加载字体规则 {Path.GetFileName(jsonPath)} -> {Path.GetFileName(bundlePath)}，字体 {targetFont.name}，新增 {addedRules} 条规则。"
                    );
                }
                catch (Exception ex)
                {
                    Logger.LogError($"[REL] 读取字体规则失败 {jsonPath}: {ex.Message}");
                }
            }

            Logger.LogInfo($"[REL] 字体规则加载完成：{loadedJsonCount} 个规则文件，{ReplacementRules.Count} 条替换规则。");
            _isInitialized = true;
        }

        private static IEnumerable<string> EnumerateTargetFontNames(FontConfig config)
        {
            foreach (string fontName in SplitFontNames(config.TargetFont))
            {
                yield return fontName;
            }

            if (config.TargetFonts == null) yield break;

            foreach (string targetFont in config.TargetFonts)
            {
                foreach (string fontName in SplitFontNames(targetFont))
                {
                    yield return fontName;
                }
            }
        }

        private static IEnumerable<string> SplitFontNames(string rawNames)
        {
            if (string.IsNullOrWhiteSpace(rawNames)) yield break;

            string[] parts = rawNames.Split(new[] { ',', ';', '|' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (string part in parts)
            {
                string normalized = NormalizeFontName(part);
                if (!string.IsNullOrWhiteSpace(normalized))
                {
                    yield return normalized;
                }
            }
        }

        private static bool TryGetRule(string fontName, out FontReplacementRule? rule)
        {
            string normalized = NormalizeFontName(fontName);
            return ReplacementRules.TryGetValue(normalized, out rule);
        }

        private static string NormalizeFontName(string fontName)
        {
            if (string.IsNullOrWhiteSpace(fontName)) return string.Empty;

            string normalized = fontName.Trim();
            const string cloneSuffix = " (Clone)";
            if (normalized.EndsWith(cloneSuffix, StringComparison.OrdinalIgnoreCase))
            {
                normalized = normalized.Substring(0, normalized.Length - cloneSuffix.Length);
            }

            return normalized.Trim();
        }

        private static string? ResolveBundlePath(string fontsDir, string bundleName)
        {
            foreach (string extension in SupportedBundleExtensions)
            {
                string candidate = Path.Combine(fontsDir, bundleName + extension);
                if (File.Exists(candidate))
                {
                    Logger.LogInfo($"[REL] 字体规则 {bundleName}.json 命中字库文件：{Path.GetFileName(candidate)}");
                    return candidate;
                }
            }

            return null;
        }

        private static Font? LoadFontFromAssetBundle(string fullPath)
        {
            AssetBundle bundle = AssetBundle.LoadFromFile(fullPath);
            if (bundle == null)
            {
                Logger.LogWarning($"[REL] AssetBundle 打开失败：{fullPath}");
                return null;
            }

            try
            {
                Font[] fonts = bundle.LoadAllAssets<Font>();
                if (fonts != null && fonts.Length > 0)
                {
                    Logger.LogInfo($"[REL] 从字体包 {Path.GetFileName(fullPath)} 中读取到 {fonts.Length} 个 Font，使用 {fonts[0].name}。");
                    return fonts[0];
                }

                foreach (UnityEngine.Object asset in bundle.LoadAllAssets())
                {
                    if (asset is Font font)
                    {
                        Logger.LogInfo($"[REL] 从字体包 {Path.GetFileName(fullPath)} 中回退找到字体 {font.name}。");
                        return font;
                    }
                }

                Logger.LogWarning($"[REL] 字体包 {Path.GetFileName(fullPath)} 中未找到 Font 资源。");
                return null;
            }
            finally
            {
                bundle.Unload(false);
            }
        }
    }
}
