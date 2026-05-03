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
using UnityEngine;
using UnityEngine.UI;

namespace ReaperEmporiumLocalization.Core
{
    public class FontReplacementRule
    {
        public Font CustomFont { get; set; } = null!;
        public FontStyle Style { get; set; } = FontStyle.Normal;
    }

    internal sealed class FontSourceInfo
    {
        public string BaseName { get; set; } = "";
        public string Label { get; set; } = "";
        public string CacheKey { get; set; } = "";
        public string TypeLabel { get; set; } = "";
        public string? FullPath { get; set; }
        public bool IsLocalFile => !string.IsNullOrWhiteSpace(FullPath);
    }

    public static class FontManager
    {
        public static readonly Dictionary<string, FontReplacementRule> ReplacementRules =
            new Dictionary<string, FontReplacementRule>(StringComparer.OrdinalIgnoreCase);

        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.Fonts");
        private static readonly string[] LocalSourceExtensionsByPriority = { "", ".ab", ".bundle", ".ttf", ".otf" };
        private static readonly HashSet<string> LocalSourceExtensions =
            new HashSet<string>(LocalSourceExtensionsByPriority, StringComparer.OrdinalIgnoreCase);
        private static readonly HashSet<string> AssetBundleExtensions =
            new HashSet<string>(new[] { "", ".ab", ".bundle" }, StringComparer.OrdinalIgnoreCase);
        private static readonly HashSet<string> DynamicFontExtensions =
            new HashSet<string>(new[] { ".ttf", ".otf" }, StringComparer.OrdinalIgnoreCase);

        private const string DefaultTargetFontPlaceholder = "请改成需要替换的原字体名";
        private const int DynamicFontSize = 16;

        private static bool _isInitialized;

        public static int LastDiscoveredFontSourceCount { get; private set; }
        public static int LastGeneratedJsonCount { get; private set; }
        public static int LastLoadedJsonCount { get; private set; }

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
            LastDiscoveredFontSourceCount = 0;
            LastGeneratedJsonCount = 0;
            LastLoadedJsonCount = 0;

            string fontsDir = Path.Combine(Paths.GameRootPath, "localization", "fonts");
            Logger.LogInfo($"[REL] 扫描字体目录：{fontsDir}");

            if (!Directory.Exists(fontsDir))
            {
                Directory.CreateDirectory(fontsDir);
                Logger.LogInfo("[REL] 字体目录不存在，已自动创建 localization/fonts。");
                _isInitialized = true;
                return;
            }

            Dictionary<string, List<string>> localSources = DiscoverLocalFontSources(fontsDir);
            LastDiscoveredFontSourceCount = localSources.Count;
            List<string> currentRuntimeFonts = DetectCurrentUiFontNames();
            LastGeneratedJsonCount = EnsureDefaultRuleJsons(fontsDir, localSources, currentRuntimeFonts);

            string[] jsonFiles = Directory.GetFiles(fontsDir, "*.json", SearchOption.TopDirectoryOnly);
            Array.Sort(jsonFiles, StringComparer.OrdinalIgnoreCase);

            if (jsonFiles.Length == 0)
            {
                Logger.LogInfo("[REL] 未找到字体规则 JSON，跳过字体替换规则加载。");
                _isInitialized = true;
                return;
            }

            Dictionary<string, Font?> fontCache = new Dictionary<string, Font?>(StringComparer.OrdinalIgnoreCase);

            foreach (string jsonPath in jsonFiles)
            {
                string baseName = Path.GetFileNameWithoutExtension(jsonPath);
                FontSourceInfo source = ResolveFontSource(baseName, localSources);

                if (source.FullPath == null && source.TypeLabel == "系统字体")
                {
                    Logger.LogInfo($"[REL] 字体规则 {Path.GetFileName(jsonPath)} 未命中本地字体文件，尝试回退到同名系统字体：{baseName}");
                }
                else
                {
                    Logger.LogInfo($"[REL] 字体规则 {Path.GetFileName(jsonPath)} 命中字体来源：{source.Label}（{source.TypeLabel}）");
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

                    int rulesBefore = ReplacementRules.Count;
                    foreach (FontConfig config in configs)
                    {
                        Font? targetFont = GetOrLoadFont(fontCache, source, config.CustomFont);
                        if (targetFont == null)
                        {
                            Logger.LogWarning(
                                $"[REL] 字体规则 {Path.GetFileName(jsonPath)} 的字体来源加载失败：{source.Label}，custom_font={config.CustomFont}"
                            );
                            continue;
                        }

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
                    LastLoadedJsonCount++;
                    Logger.LogInfo(
                        $"[REL] 已加载字体规则 {Path.GetFileName(jsonPath)} -> {source.Label}，新增 {addedRules} 条规则。"
                    );
                }
                catch (Exception ex)
                {
                    Logger.LogError($"[REL] 读取字体规则失败 {jsonPath}: {ex.Message}");
                }
            }

            Logger.LogInfo(
                $"[REL] 字体规则加载完成：发现 {LastDiscoveredFontSourceCount} 个字体来源，自动生成 {LastGeneratedJsonCount} 个 json，加载 {LastLoadedJsonCount} 个规则文件，共 {ReplacementRules.Count} 条规则。"
            );
            _isInitialized = true;
        }

        private static Dictionary<string, List<string>> DiscoverLocalFontSources(string fontsDir)
        {
            Dictionary<string, List<string>> sources = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
            string[] files = Directory.GetFiles(fontsDir, "*", SearchOption.TopDirectoryOnly);
            Array.Sort(files, StringComparer.OrdinalIgnoreCase);

            foreach (string filePath in files)
            {
                string extension = Path.GetExtension(filePath);
                if (extension.Equals(".json", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (!LocalSourceExtensions.Contains(extension))
                {
                    Logger.LogInfo($"[REL] 跳过不支持的字体目录文件：{Path.GetFileName(filePath)}");
                    continue;
                }

                string baseName = GetFontSourceBaseName(filePath);
                if (string.IsNullOrWhiteSpace(baseName))
                {
                    Logger.LogWarning($"[REL] 字体来源文件名无效，已跳过：{filePath}");
                    continue;
                }

                if (!sources.TryGetValue(baseName, out List<string>? candidates))
                {
                    candidates = new List<string>();
                    sources[baseName] = candidates;
                }

                candidates.Add(filePath);
                Logger.LogInfo($"[REL] 发现字体来源：{Path.GetFileName(filePath)} -> {baseName}");
            }

            return sources;
        }

        private static int EnsureDefaultRuleJsons(
            string fontsDir,
            Dictionary<string, List<string>> localSources,
            List<string> currentRuntimeFonts
        )
        {
            int generatedCount = 0;

            foreach (string baseName in localSources.Keys.OrderBy(item => item, StringComparer.OrdinalIgnoreCase))
            {
                string jsonPath = Path.Combine(fontsDir, $"{baseName}.json");
                if (File.Exists(jsonPath))
                {
                    Logger.LogInfo($"[REL] 字体来源 {baseName} 已存在规则文件：{Path.GetFileName(jsonPath)}");
                    continue;
                }

                if (!LocalizationConfig.EnableAutoGenerateFontJson.Value)
                {
                    Logger.LogInfo($"[REL] 字体来源 {baseName} 缺少同名 json，但自动生成开关关闭，已跳过。");
                    continue;
                }

                List<FontConfig> template = BuildDefaultRuleTemplate(baseName, localSources[baseName], currentRuntimeFonts);
                WriteDefaultRuleJson(jsonPath, template);
                generatedCount++;
                Logger.LogInfo($"[REL] 已为字体来源 {baseName} 自动生成默认规则文件：{Path.GetFileName(jsonPath)}");
            }

            return generatedCount;
        }

        private static List<FontConfig> BuildDefaultRuleTemplate(
            string baseName,
            List<string> sourceFiles,
            List<string> currentRuntimeFonts
        )
        {
            SortedSet<string> embeddedFontNames = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (string sourceFile in sourceFiles.OrderBy(item => item, StringComparer.OrdinalIgnoreCase))
            {
                if (!AssetBundleExtensions.Contains(Path.GetExtension(sourceFile)))
                {
                    continue;
                }

                IReadOnlyList<string> fontNames = InspectAssetBundleFontNames(sourceFile);
                if (fontNames.Count == 0)
                {
                    Logger.LogInfo($"[REL] 自动生成 {baseName}.json 时，字体包 {Path.GetFileName(sourceFile)} 内未发现 Font 资源。");
                    continue;
                }

                Logger.LogInfo(
                    $"[REL] 自动生成 {baseName}.json 时，扫描字体包 {Path.GetFileName(sourceFile)} 得到 {fontNames.Count} 个字体：{string.Join(", ", fontNames)}"
                );
                foreach (string fontName in fontNames)
                {
                    embeddedFontNames.Add(fontName);
                }
            }

            List<FontConfig> templates = new List<FontConfig>();

            string primaryTargetFont = currentRuntimeFonts.Count > 0 ? currentRuntimeFonts[0] : DefaultTargetFontPlaceholder;
            List<string> additionalTargetFonts = currentRuntimeFonts.Count > 1
                ? currentRuntimeFonts.Skip(1).ToList()
                : new List<string>();

            if (embeddedFontNames.Count == 0)
            {
                templates.Add(new FontConfig
                {
                    TargetFont = primaryTargetFont,
                    TargetFonts = additionalTargetFonts,
                    FontStyleStr = "Normal",
                });
                return templates;
            }

            string[] embeddedFonts = embeddedFontNames.ToArray();
            templates.Add(new FontConfig
            {
                TargetFont = primaryTargetFont,
                TargetFonts = additionalTargetFonts,
                CustomFont = embeddedFonts[0],
                FontStyleStr = "Normal",
            });

            for (int index = 1; index < embeddedFonts.Length; index++)
            {
                string embeddedFontName = embeddedFonts[index];
                templates.Add(
                    new FontConfig
                    {
                        TargetFont = primaryTargetFont,
                        TargetFonts = new List<string>(additionalTargetFonts),
                        CustomFont = embeddedFontName,
                        FontStyleStr = "Normal",
                    }
                );
            }

            return templates;
        }

        private static void WriteDefaultRuleJson(string jsonPath, List<FontConfig> template)
        {
            string json = JsonConvert.SerializeObject(template, Formatting.Indented);
            File.WriteAllText(jsonPath, json, new UTF8Encoding(false));
        }

        private static List<string> DetectCurrentUiFontNames()
        {
            Dictionary<string, int> fontUsage = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

            foreach (Text text in Resources.FindObjectsOfTypeAll<Text>())
            {
                if (text == null || text.font == null)
                {
                    continue;
                }

                string fontName = NormalizeFontName(text.font.name);
                if (string.IsNullOrWhiteSpace(fontName))
                {
                    continue;
                }

                fontUsage.TryGetValue(fontName, out int count);
                fontUsage[fontName] = count + 1;
            }

            if (fontUsage.Count == 0)
            {
                Logger.LogInfo("[REL] 当前未检测到 UI.Text 使用中的字体，自动生成 json 时将继续使用占位 target_font。");
                return new List<string>();
            }

            List<string> orderedFonts = fontUsage
                .OrderByDescending(pair => pair.Value)
                .ThenBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
                .Select(pair => pair.Key)
                .ToList();

            Logger.LogInfo(
                $"[REL] 当前检测到 UI.Text 使用中的字体：{string.Join(", ", orderedFonts.Select(name => $"{name} x{fontUsage[name]}"))}"
            );
            return orderedFonts;
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

        private static string GetFontSourceBaseName(string filePath)
        {
            string extension = Path.GetExtension(filePath);
            return string.IsNullOrEmpty(extension) ? Path.GetFileName(filePath) : Path.GetFileNameWithoutExtension(filePath);
        }

        private static FontSourceInfo ResolveFontSource(string baseName, Dictionary<string, List<string>> localSources)
        {
            if (localSources.TryGetValue(baseName, out List<string>? candidates))
            {
                foreach (string extension in LocalSourceExtensionsByPriority)
                {
                    string? match = candidates.FirstOrDefault(
                        candidate => string.Equals(Path.GetExtension(candidate), extension, StringComparison.OrdinalIgnoreCase)
                    );
                    if (match == null)
                    {
                        continue;
                    }

                    return new FontSourceInfo
                    {
                        BaseName = baseName,
                        FullPath = match,
                        CacheKey = match,
                        Label = Path.GetFileName(match),
                        TypeLabel = GetSourceTypeLabel(match),
                    };
                }
            }

            return new FontSourceInfo
            {
                BaseName = baseName,
                CacheKey = $"system::{baseName}",
                Label = $"系统字体 {baseName}",
                TypeLabel = "系统字体",
            };
        }

        private static string GetSourceTypeLabel(string filePath)
        {
            string extension = Path.GetExtension(filePath);
            if (extension.Equals(".ttf", StringComparison.OrdinalIgnoreCase))
            {
                return "TTF";
            }

            if (extension.Equals(".otf", StringComparison.OrdinalIgnoreCase))
            {
                return "OTF";
            }

            if (AssetBundleExtensions.Contains(extension))
            {
                return string.IsNullOrEmpty(extension) ? "无后缀 AssetBundle" : "AssetBundle";
            }

            return extension;
        }

        private static Font? GetOrLoadFont(Dictionary<string, Font?> cache, FontSourceInfo source, string preferredFontName)
        {
            string cacheKey = BuildFontCacheKey(source, preferredFontName);
            if (cache.TryGetValue(cacheKey, out Font? cachedFont))
            {
                Logger.LogInfo($"[REL] 复用已缓存的字体来源：{source.Label}，custom_font={preferredFontName}");
                return cachedFont;
            }

            Font? font = source.IsLocalFile
                ? LoadFontFromLocalSource(source, preferredFontName)
                : LoadFontFromSystemFont(source.BaseName);
            cache[cacheKey] = font;
            return font;
        }

        private static string BuildFontCacheKey(FontSourceInfo source, string preferredFontName)
        {
            string normalizedPreferred = NormalizeFontName(preferredFontName);
            if (string.IsNullOrWhiteSpace(normalizedPreferred))
            {
                return source.CacheKey;
            }

            return $"{source.CacheKey}::{normalizedPreferred}";
        }

        private static Font? LoadFontFromLocalSource(FontSourceInfo source, string preferredFontName)
        {
            string fullPath = source.FullPath ?? string.Empty;
            string extension = Path.GetExtension(fullPath);
            if (DynamicFontExtensions.Contains(extension))
            {
                return LoadDynamicFontFromFile(fullPath);
            }

            return LoadFontFromAssetBundle(fullPath, preferredFontName);
        }

        private static Font? LoadDynamicFontFromFile(string fullPath)
        {
            string baseName = Path.GetFileNameWithoutExtension(fullPath);
            string[] candidates = { fullPath, baseName, $"{baseName}-Regular", $"{baseName} Regular" };
            Logger.LogInfo($"[REL] 尝试动态加载字体文件 {Path.GetFileName(fullPath)}，候选：{string.Join(", ", candidates)}");

            foreach (string candidate in candidates)
            {
                try
                {
                    Font font = Font.CreateDynamicFontFromOSFont(candidate, DynamicFontSize);
                    if (font != null)
                    {
                        font.name = baseName;
                        Logger.LogInfo($"[REL] 动态字体加载成功：{Path.GetFileName(fullPath)} -> {candidate}");
                        return font;
                    }
                }
                catch (Exception ex)
                {
                    Logger.LogWarning($"[REL] 动态字体候选 {candidate} 加载失败：{ex.Message}");
                }
            }

            Logger.LogWarning($"[REL] 动态字体加载失败：{Path.GetFileName(fullPath)}");
            return null;
        }

        private static Font? LoadFontFromSystemFont(string baseName)
        {
            string[] candidates = { baseName, $"{baseName}-Regular", $"{baseName} Regular" };
            Logger.LogInfo($"[REL] 尝试加载同名系统字体：{string.Join(", ", candidates)}");

            foreach (string candidate in candidates)
            {
                try
                {
                    Font font = Font.CreateDynamicFontFromOSFont(candidate, DynamicFontSize);
                    if (font != null)
                    {
                        font.name = candidate;
                        Logger.LogInfo($"[REL] 系统字体加载成功：{candidate}");
                        return font;
                    }
                }
                catch (Exception ex)
                {
                    Logger.LogWarning($"[REL] 系统字体候选 {candidate} 加载失败：{ex.Message}");
                }
            }

            Logger.LogWarning($"[REL] 未找到同名系统字体：{baseName}");
            return null;
        }

        private static IReadOnlyList<string> InspectAssetBundleFontNames(string fullPath)
        {
            AssetBundle bundle = AssetBundle.LoadFromFile(fullPath);
            if (bundle == null)
            {
                Logger.LogWarning($"[REL] 扫描字体包失败，无法打开 AssetBundle：{fullPath}");
                return Array.Empty<string>();
            }

            try
            {
                List<Font> fonts = CollectFontsFromAssetBundle(bundle);
                return fonts
                    .Select(font => NormalizeFontName(font.name))
                    .Where(name => !string.IsNullOrWhiteSpace(name))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                    .ToArray();
            }
            catch (Exception ex)
            {
                Logger.LogWarning($"[REL] 扫描字体包中的 Font 资源失败 {Path.GetFileName(fullPath)}：{ex.Message}");
                return Array.Empty<string>();
            }
            finally
            {
                bundle.Unload(false);
            }
        }

        private static Font? LoadFontFromAssetBundle(string fullPath, string preferredFontName)
        {
            AssetBundle bundle = AssetBundle.LoadFromFile(fullPath);
            if (bundle == null)
            {
                Logger.LogWarning($"[REL] AssetBundle 打开失败：{fullPath}");
                return null;
            }

            try
            {
                List<Font> fonts = CollectFontsFromAssetBundle(bundle);
                if (fonts.Count == 0)
                {
                    Logger.LogWarning($"[REL] 字体包 {Path.GetFileName(fullPath)} 中未找到 Font 资源。");
                    return null;
                }

                string normalizedPreferred = NormalizeFontName(preferredFontName);
                if (!string.IsNullOrWhiteSpace(normalizedPreferred))
                {
                    Font? preferredFont = fonts.FirstOrDefault(
                        font => string.Equals(NormalizeFontName(font.name), normalizedPreferred, StringComparison.OrdinalIgnoreCase)
                    );
                    if (preferredFont != null)
                    {
                        Logger.LogInfo(
                            $"[REL] 从字体包 {Path.GetFileName(fullPath)} 的 {fonts.Count} 个字体中命中 custom_font={preferredFontName}。"
                        );
                        return preferredFont;
                    }

                    Logger.LogWarning(
                        $"[REL] 字体包 {Path.GetFileName(fullPath)} 中未找到 custom_font={preferredFontName}，将回退到第一个字体。"
                    );
                }

                Logger.LogInfo($"[REL] 从字体包 {Path.GetFileName(fullPath)} 中扫描到 {fonts.Count} 个字体，默认使用 {fonts[0].name}。");
                return fonts[0];
            }
            finally
            {
                bundle.Unload(false);
            }
        }

        private static List<Font> CollectFontsFromAssetBundle(AssetBundle bundle)
        {
            List<Font> fonts = new List<Font>();
            HashSet<int> seenIds = new HashSet<int>();

            foreach (Font font in bundle.LoadAllAssets<Font>())
            {
                if (font == null) continue;
                if (seenIds.Add(font.GetInstanceID()))
                {
                    fonts.Add(font);
                }
            }

            foreach (UnityEngine.Object asset in bundle.LoadAllAssets())
            {
                if (asset is not Font font) continue;
                if (seenIds.Add(font.GetInstanceID()))
                {
                    fonts.Add(font);
                }
            }

            return fonts;
        }
    }
}
