using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
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

    internal enum FontSourceMode
    {
        BundleAsset,
        FontPath,
        OsDynamic,
    }

    internal enum FontLoadOutcome
    {
        BundleAsset,
        FontPathAccepted,
        FontPathDynamicFallback,
        OsDynamic,
    }

    internal sealed class FontRuleSource
    {
        public FontSourceMode Mode { get; set; }
        public string CacheKey { get; set; } = "";
        public string Label { get; set; } = "";
        public string? FullPath { get; set; }
        public string? SourceFile { get; set; }
        public string? SourceFont { get; set; }
        public IReadOnlyList<string> DynamicFontNames { get; set; } = Array.Empty<string>();
    }

    internal sealed class FontLoadResult
    {
        public Font? Font { get; set; }
        public FontLoadOutcome Outcome { get; set; }
    }

    internal sealed class FontNameRecord
    {
        public ushort PlatformId { get; set; }
        public ushort EncodingId { get; set; }
        public ushort LanguageId { get; set; }
        public ushort NameId { get; set; }
        public ushort Length { get; set; }
        public ushort Offset { get; set; }
    }

    internal sealed class FontConfigFileState
    {
        public List<FontConfig> Configs { get; } = new List<FontConfig>();
        public bool NeedsWriteBack { get; set; }
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
        private static readonly HashSet<string> FontPathExtensions =
            new HashSet<string>(new[] { ".ttf", ".otf" }, StringComparer.OrdinalIgnoreCase);
        private static readonly string[] DefaultDynamicFallbackFontNames =
        {
            "Noto Sans SC",
            "Microsoft YaHei",
            "SimHei",
            "Arial",
        };
        private static readonly HashSet<string> RegisteredPrivateFontFiles =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static readonly HashSet<string> LoggedWarningKeys =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static readonly HashSet<string> LoggedApplyDebugKeys =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static readonly Dictionary<int, string> OriginalFontNamesByTextId =
            new Dictionary<int, string>();

        private const string BundleAssetModeName = "bundle_asset";
        private const string FontPathModeName = "font_path";
        private const string OsDynamicModeName = "os_dynamic";
        private const string DefaultTargetFontPlaceholder = "请改成需要替换的原字体名";
        private const int DynamicFontSize = 16;
        private const uint FrPrivate = 0x10;

        private static bool _isInitialized;

        public static int LastDiscoveredFontSourceCount { get; private set; }
        public static int LastGeneratedJsonCount { get; private set; }
        public static int LastLoadedJsonCount { get; private set; }

        [DllImport("gdi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int AddFontResourceEx(string lpszFilename, uint fl, IntPtr pdv);

        public static void InitFont()
        {
            if (_isInitialized)
            {
                return;
            }

            LoadRules();
        }

        public static void Reload()
        {
            LoadRules();
        }

        public static bool TryApply(Text target)
        {
            if (target == null || target.font == null)
            {
                return false;
            }

            InitFont();

            int textId = target.GetInstanceID();
            string currentFontName = target.font.name;
            string lookupFontName = GetRuleLookupFontName(textId, currentFontName);

            if (!TryGetRule(lookupFontName, out FontReplacementRule? rule) || rule?.CustomFont == null)
            {
                return false;
            }

            RememberOriginalFontName(textId, currentFontName, lookupFontName, rule);

            Font originalFont = target.font;
            FontStyle originalStyle = target.fontStyle;
            int originalFontSize = target.fontSize;
            bool changed = false;
            bool fontChanged = false;
            bool styleChanged = false;
            bool sizeChanged = false;

            if (target.font != rule.CustomFont)
            {
                target.font = rule.CustomFont;
                changed = true;
                fontChanged = true;
            }

            if (target.fontStyle != rule.Style)
            {
                target.fontStyle = rule.Style;
                changed = true;
                styleChanged = true;
            }

            int debugSizeOffset = LocalizationConfig.FontDebugSizeOffset.Value;
            if (debugSizeOffset != 0 && fontChanged)
            {
                int adjustedFontSize = Math.Max(1, target.fontSize + debugSizeOffset);
                if (adjustedFontSize != target.fontSize)
                {
                    target.fontSize = adjustedFontSize;
                    changed = true;
                    sizeChanged = target.fontSize != originalFontSize;
                }
            }

            if (changed)
            {
                target.SetAllDirty();
                if (target.transform is RectTransform rectTransform)
                {
                    LayoutRebuilder.MarkLayoutForRebuild(rectTransform);
                }
            }

            if (LocalizationConfig.EnableFontDebugLogging.Value)
            {
                LogApplyDebugInfo(target, originalFont, originalStyle, originalFontSize, fontChanged, styleChanged, sizeChanged);
            }

            return changed;
        }

        private static string GetRuleLookupFontName(int textId, string currentFontName)
        {
            if (OriginalFontNamesByTextId.TryGetValue(textId, out string? originalFontName) &&
                !string.IsNullOrWhiteSpace(originalFontName))
            {
                return originalFontName;
            }

            return currentFontName;
        }

        private static void RememberOriginalFontName(
            int textId,
            string currentFontName,
            string lookupFontName,
            FontReplacementRule rule
        )
        {
            if (OriginalFontNamesByTextId.ContainsKey(textId))
            {
                return;
            }

            if (string.Equals(currentFontName, rule.CustomFont.name, StringComparison.OrdinalIgnoreCase) &&
                string.Equals(lookupFontName, currentFontName, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            OriginalFontNamesByTextId[textId] = lookupFontName;
        }

        private static void LogApplyDebugInfo(
            Text target,
            Font originalFont,
            FontStyle originalStyle,
            int originalFontSize,
            bool fontChanged,
            bool styleChanged,
            bool sizeChanged
        )
        {
            string currentFontName = target.font == null ? "<null>" : target.font.name;
            string originalFontName = originalFont == null ? "<null>" : originalFont.name;
            Rect rect = target.rectTransform == null ? default : target.rectTransform.rect;
            string debugKey =
                $"{target.GetInstanceID()}|{originalFontName}|{currentFontName}|{originalStyle}|{target.fontStyle}|{originalFontSize}|{target.fontSize}|{target.resizeTextForBestFit}|{rect.width:0.##}|{rect.height:0.##}";

            if (!LoggedApplyDebugKeys.Add(debugKey))
            {
                return;
            }

            Logger.LogInfo(
                "[REL] FontDebug " +
                $"object={target.name}, " +
                $"font={originalFontName} -> {currentFontName}, " +
                $"style={originalStyle} -> {target.fontStyle}, " +
                $"fontSize={originalFontSize} -> {target.fontSize}, " +
                $"bestFit={target.resizeTextForBestFit}, " +
                $"bestFitRange={target.resizeTextMinSize}-{target.resizeTextMaxSize}, " +
                $"lineSpacing={target.lineSpacing:0.##}, " +
                $"changed={fontChanged || styleChanged || sizeChanged}, " +
                $"horizontalOverflow={target.horizontalOverflow}, " +
                $"verticalOverflow={target.verticalOverflow}, " +
                $"align={target.alignment}, " +
                $"rect={rect.width:0.##}x{rect.height:0.##}"
            );
        }

        private static void LoadRules()
        {
            ReplacementRules.Clear();
            LoggedWarningKeys.Clear();
            LoggedApplyDebugKeys.Clear();
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
            LastDiscoveredFontSourceCount = CountLocalSourceFiles(localSources);
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

            Dictionary<string, FontLoadResult> fontCache = new Dictionary<string, FontLoadResult>(StringComparer.OrdinalIgnoreCase);
            HashSet<string> countedSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int bundleAssetCount = 0;
            int fontPathAcceptedCount = 0;
            int fontPathFallbackCount = 0;
            int osDynamicCount = 0;

            foreach (string jsonPath in jsonFiles)
            {
                FontConfigFileState fileState;
                try
                {
                    fileState = LoadAndNormalizeConfigFile(jsonPath, fontsDir, localSources);
                }
                catch (Exception ex)
                {
                    Logger.LogError($"[REL] 读取字体规则失败 {jsonPath}: {ex.Message}");
                    continue;
                }

                if (fileState.Configs.Count == 0)
                {
                    Logger.LogWarning($"[REL] 字体规则 {Path.GetFileName(jsonPath)} 为空，已跳过。");
                    continue;
                }

                int rulesBefore = ReplacementRules.Count;
                foreach (FontConfig config in fileState.Configs)
                {
                    FontRuleSource? source = ResolveRuleSource(config, jsonPath, fontsDir, localSources);
                    if (source == null)
                    {
                        continue;
                    }

                    FontLoadResult loadResult = GetOrLoadFont(fontCache, source);
                    if (loadResult.Font == null)
                    {
                        WarnOnce(
                            $"load-failed::{source.CacheKey}",
                            $"[REL] 字体规则 {Path.GetFileName(jsonPath)} 的字体来源加载失败：{source.Label}"
                        );
                        continue;
                    }

                    if (countedSources.Add(source.CacheKey))
                    {
                        switch (loadResult.Outcome)
                        {
                            case FontLoadOutcome.BundleAsset:
                                bundleAssetCount++;
                                break;
                            case FontLoadOutcome.FontPathAccepted:
                                fontPathAcceptedCount++;
                                break;
                            case FontLoadOutcome.FontPathDynamicFallback:
                                fontPathFallbackCount++;
                                break;
                            case FontLoadOutcome.OsDynamic:
                                osDynamicCount++;
                                break;
                        }
                    }

                    if (!Enum.TryParse(config.FontStyleStr, true, out FontStyle parsedStyle))
                    {
                        WarnOnce(
                            $"font-style::{jsonPath}::{config.FontStyleStr}",
                            $"[REL] 字体样式 {config.FontStyleStr} 无效，已回退为 Normal。"
                        );
                        parsedStyle = FontStyle.Normal;
                    }

                    foreach (string targetName in EnumerateTargetFontNames(config))
                    {
                        ReplacementRules[targetName] = new FontReplacementRule
                        {
                            CustomFont = loadResult.Font,
                            Style = parsedStyle,
                        };
                    }
                }

                int addedRules = ReplacementRules.Count - rulesBefore;
                LastLoadedJsonCount++;
                Logger.LogInfo(
                    $"[REL] 已加载字体规则 {Path.GetFileName(jsonPath)}，新增 {addedRules} 条规则。"
                );
            }

            Logger.LogInfo(
                $"[REL] 字体规则加载完成：发现 {LastDiscoveredFontSourceCount} 个字体来源，自动生成 {LastGeneratedJsonCount} 个 json，加载 {LastLoadedJsonCount} 个规则文件，共 {ReplacementRules.Count} 条规则。来源统计：bundle_asset={bundleAssetCount}，font_path accepted={fontPathAcceptedCount}，font_path -> os_dynamic fallback={fontPathFallbackCount}，os_dynamic={osDynamicCount}。"
            );
            _isInitialized = true;
        }

        private static FontConfigFileState LoadAndNormalizeConfigFile(
            string jsonPath,
            string fontsDir,
            Dictionary<string, List<string>> localSources
        )
        {
            string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
            List<FontConfig>? rawConfigs = JsonConvert.DeserializeObject<List<FontConfig>>(jsonContent);
            FontConfigFileState state = new FontConfigFileState();
            if (rawConfigs == null)
            {
                return state;
            }

            foreach (FontConfig rawConfig in rawConfigs)
            {
                bool isExplicit = HasExplicitSourceMode(rawConfig);
                FontConfig normalized = isExplicit
                    ? NormalizeExplicitConfig(rawConfig, jsonPath, fontsDir, localSources)
                    : MigrateLegacyConfig(rawConfig, jsonPath, localSources);
                state.Configs.Add(normalized);
                state.NeedsWriteBack |= !isExplicit;
            }

            if (state.NeedsWriteBack)
            {
                TryBackupAndWriteNormalizedConfig(jsonPath, state.Configs);
            }

            return state;
        }

        private static bool HasExplicitSourceMode(FontConfig config)
        {
            return ParseSourceMode(config.SourceMode).HasValue;
        }

        private static FontConfig NormalizeExplicitConfig(
            FontConfig config,
            string jsonPath,
            string fontsDir,
            Dictionary<string, List<string>> localSources
        )
        {
            string baseName = Path.GetFileNameWithoutExtension(jsonPath);
            FontConfig normalized = CopyCommonFields(config);
            FontSourceMode? sourceMode = ParseSourceMode(config.SourceMode);
            if (!sourceMode.HasValue)
            {
                normalized.SourceMode = config.SourceMode?.Trim();
                return normalized;
            }

            normalized.SourceMode = GetSourceModeName(sourceMode.Value);

            switch (sourceMode.Value)
            {
                case FontSourceMode.BundleAsset:
                {
                    string? sourcePath = ResolveConfiguredSourcePath(
                        config.SourceFile,
                        baseName,
                        fontsDir,
                        localSources,
                        AssetBundleExtensions
                    );
                    normalized.SourceFile = sourcePath == null ? null : Path.GetFileName(sourcePath);
                    normalized.SourceFont = NormalizeOptionalFontName(config.SourceFont);
                    break;
                }
                case FontSourceMode.FontPath:
                {
                    string? sourcePath = ResolveConfiguredSourcePath(
                        config.SourceFile,
                        baseName,
                        fontsDir,
                        localSources,
                        FontPathExtensions
                    );
                    normalized.SourceFile = sourcePath == null ? null : Path.GetFileName(sourcePath);
                    if (sourcePath != null)
                    {
                        normalized.DynamicFontNames = BuildDynamicFontCandidates(
                            sourcePath,
                            Path.GetFileNameWithoutExtension(sourcePath),
                            config.SourceFont,
                            config.CustomFont,
                            config.DynamicFontNames
                        );
                    }
                    else
                    {
                        normalized.DynamicFontNames = BuildSystemFontCandidateNames(
                            baseName,
                            config.SourceFont,
                            config.CustomFont,
                            config.DynamicFontNames
                        );
                    }

                    break;
                }
                case FontSourceMode.OsDynamic:
                    normalized.DynamicFontNames = BuildSystemFontCandidateNames(
                        baseName,
                        config.SourceFont,
                        config.CustomFont,
                        config.DynamicFontNames
                    );
                    break;
            }

            return normalized;
        }

        private static FontConfig MigrateLegacyConfig(
            FontConfig config,
            string jsonPath,
            Dictionary<string, List<string>> localSources
        )
        {
            string baseName = Path.GetFileNameWithoutExtension(jsonPath);
            FontConfig migrated = CopyCommonFields(config);

            string? bundleSource = FindPreferredSourceFile(baseName, localSources, AssetBundleExtensions);
            if (bundleSource != null)
            {
                migrated.SourceMode = BundleAssetModeName;
                migrated.SourceFile = Path.GetFileName(bundleSource);
                migrated.SourceFont = NormalizeOptionalFontName(config.CustomFont);
                return migrated;
            }

            string? fontPathSource = FindPreferredSourceFile(baseName, localSources, FontPathExtensions);
            if (fontPathSource != null)
            {
                migrated.SourceMode = FontPathModeName;
                migrated.SourceFile = Path.GetFileName(fontPathSource);
                migrated.DynamicFontNames = BuildDynamicFontCandidates(fontPathSource, baseName, config.CustomFont);
                return migrated;
            }

            migrated.SourceMode = OsDynamicModeName;
            migrated.DynamicFontNames = BuildSystemFontCandidateNames(baseName, config.CustomFont);
            return migrated;
        }

        private static FontConfig CopyCommonFields(FontConfig config)
        {
            return new FontConfig
            {
                TargetFont = "",
                TargetFonts = NormalizeTargetFontNames(config),
                FontStyleStr = string.IsNullOrWhiteSpace(config.FontStyleStr) ? "Normal" : config.FontStyleStr.Trim(),
            };
        }

        private static List<string> NormalizeTargetFontNames(FontConfig config)
        {
            List<string> normalizedValues = new List<string>();
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (string fontName in EnumerateTargetFontNames(config))
            {
                string normalized = NormalizeFontName(fontName);
                if (string.IsNullOrWhiteSpace(normalized) || !seen.Add(normalized))
                {
                    continue;
                }

                normalizedValues.Add(normalized);
            }

            return normalizedValues;
        }

        private static List<string> NormalizeNameList(IEnumerable<string>? values)
        {
            List<string> normalizedValues = new List<string>();
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (values == null)
            {
                return normalizedValues;
            }

            foreach (string? value in values)
            {
                string normalized = NormalizeFontName(value ?? string.Empty);
                if (string.IsNullOrWhiteSpace(normalized) || !seen.Add(normalized))
                {
                    continue;
                }

                normalizedValues.Add(normalized);
            }

            return normalizedValues;
        }

        private static void TryBackupAndWriteNormalizedConfig(string jsonPath, IReadOnlyList<FontConfig> configs)
        {
            try
            {
                string backupPath = $"{jsonPath}.bak";
                if (!File.Exists(backupPath))
                {
                    File.Copy(jsonPath, backupPath, overwrite: false);
                    Logger.LogInfo($"[REL] 已为旧版字体规则创建备份：{Path.GetFileName(backupPath)}");
                }

                WriteJsonFile(jsonPath, configs);
                Logger.LogInfo($"[REL] 已将旧版字体规则迁移为显式来源格式：{Path.GetFileName(jsonPath)}");
            }
            catch (Exception ex)
            {
                WarnOnce(
                    $"migrate-write::{jsonPath}",
                    $"[REL] 旧版字体规则写回失败 {Path.GetFileName(jsonPath)}：{ex.Message}。将继续使用内存中的迁移结果。"
                );
            }
        }

        private static Dictionary<string, List<string>> DiscoverLocalFontSources(string fontsDir)
        {
            Dictionary<string, List<string>> sources = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
            string[] files = Directory.GetFiles(fontsDir, "*", SearchOption.TopDirectoryOnly);
            Array.Sort(files, StringComparer.OrdinalIgnoreCase);

            foreach (string filePath in files)
            {
                string extension = Path.GetExtension(filePath);
                if (extension.Equals(".json", StringComparison.OrdinalIgnoreCase) ||
                    extension.Equals(".bak", StringComparison.OrdinalIgnoreCase))
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
                    WarnOnce($"invalid-source::{filePath}", $"[REL] 字体来源文件名无效，已跳过：{filePath}");
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

        private static int CountLocalSourceFiles(Dictionary<string, List<string>> localSources)
        {
            return localSources.Values.Sum(values => values.Count);
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
                WriteJsonFile(jsonPath, template);
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
            List<string> targetFonts = currentRuntimeFonts.Count > 0
                ? new List<string>(currentRuntimeFonts)
                : new List<string> { DefaultTargetFontPlaceholder };

            string? bundleSource = FindPreferredSourceFile(sourceFiles, AssetBundleExtensions);
            if (bundleSource != null)
            {
                IReadOnlyList<string> bundleFonts = InspectAssetBundleFontNames(bundleSource);
                if (bundleFonts.Count > 0)
                {
                    return bundleFonts
                        .Select(fontName => new FontConfig
                        {
                            TargetFonts = new List<string>(targetFonts),
                            FontStyleStr = "Normal",
                            SourceMode = BundleAssetModeName,
                            SourceFile = Path.GetFileName(bundleSource),
                            SourceFont = fontName,
                        })
                        .ToList();
                }
            }

            string? fontPathSource = FindPreferredSourceFile(sourceFiles, FontPathExtensions);
            if (fontPathSource != null)
            {
                return new List<FontConfig>
                {
                    new FontConfig
                    {
                        TargetFonts = new List<string>(targetFonts),
                        FontStyleStr = "Normal",
                        SourceMode = FontPathModeName,
                        SourceFile = Path.GetFileName(fontPathSource),
                        DynamicFontNames = BuildDynamicFontCandidates(fontPathSource, baseName),
                    },
                };
            }

            return new List<FontConfig>
            {
                new FontConfig
                {
                    TargetFonts = new List<string>(targetFonts),
                    FontStyleStr = "Normal",
                    SourceMode = OsDynamicModeName,
                    DynamicFontNames = BuildSystemFontCandidateNames(baseName),
                },
            };
        }

        private static void WriteJsonFile(string jsonPath, IReadOnlyList<FontConfig> configs)
        {
            string json = JsonConvert.SerializeObject(configs, Formatting.Indented);
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
                Logger.LogInfo("[REL] 当前未检测到 UI.Text 使用中的字体，自动生成 json 时将继续使用占位 target_fonts。");
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
            if (string.IsNullOrWhiteSpace(rawNames))
            {
                yield break;
            }

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
            if (string.IsNullOrWhiteSpace(fontName))
            {
                return string.Empty;
            }

            string normalized = fontName.Trim();
            const string cloneSuffix = " (Clone)";
            if (normalized.EndsWith(cloneSuffix, StringComparison.OrdinalIgnoreCase))
            {
                normalized = normalized.Substring(0, normalized.Length - cloneSuffix.Length);
            }

            return normalized.Trim();
        }

        private static string? NormalizeOptionalFontName(string? fontName)
        {
            string normalized = NormalizeFontName(fontName ?? string.Empty);
            return string.IsNullOrWhiteSpace(normalized) ? null : normalized;
        }

        private static string GetFontSourceBaseName(string filePath)
        {
            string extension = Path.GetExtension(filePath);
            return string.IsNullOrEmpty(extension) ? Path.GetFileName(filePath) : Path.GetFileNameWithoutExtension(filePath);
        }

        private static FontRuleSource? ResolveRuleSource(
            FontConfig config,
            string jsonPath,
            string fontsDir,
            Dictionary<string, List<string>> localSources
        )
        {
            string baseName = Path.GetFileNameWithoutExtension(jsonPath);
            FontSourceMode? sourceMode = ParseSourceMode(config.SourceMode);
            if (!sourceMode.HasValue)
            {
                WarnOnce(
                    $"invalid-source-mode::{jsonPath}::{config.SourceMode}",
                    $"[REL] 字体规则 {Path.GetFileName(jsonPath)} 的 source_mode 无效：{config.SourceMode}"
                );
                return null;
            }

            switch (sourceMode.Value)
            {
                case FontSourceMode.BundleAsset:
                {
                    string? fullPath = ResolveConfiguredSourcePath(
                        config.SourceFile,
                        baseName,
                        fontsDir,
                        localSources,
                        AssetBundleExtensions
                    );
                    if (fullPath == null)
                    {
                        WarnOnce(
                            $"bundle-missing::{jsonPath}",
                            $"[REL] 字体规则 {Path.GetFileName(jsonPath)} 未找到 bundle 来源：{config.SourceFile ?? baseName}"
                        );
                        return null;
                    }

                    string? sourceFont = NormalizeOptionalFontName(config.SourceFont);
                    return new FontRuleSource
                    {
                        Mode = FontSourceMode.BundleAsset,
                        FullPath = fullPath,
                        SourceFile = Path.GetFileName(fullPath),
                        SourceFont = sourceFont,
                        Label = $"{Path.GetFileName(fullPath)} -> {(sourceFont ?? "<first>")}",
                        CacheKey = $"bundle_asset::{fullPath}::{sourceFont ?? "<first>"}",
                    };
                }
                case FontSourceMode.FontPath:
                {
                    string? fullPath = ResolveConfiguredSourcePath(
                        config.SourceFile,
                        baseName,
                        fontsDir,
                        localSources,
                        FontPathExtensions
                    );
                    if (fullPath == null)
                    {
                        WarnOnce(
                            $"font-path-missing::{jsonPath}",
                            $"[REL] 字体规则 {Path.GetFileName(jsonPath)} 未找到字体文件来源：{config.SourceFile ?? baseName}"
                        );
                        return null;
                    }

                    List<string> dynamicFontNames = NormalizeDynamicFontNames(config.DynamicFontNames);
                    if (dynamicFontNames.Count == 0)
                    {
                        dynamicFontNames = BuildDynamicFontCandidates(fullPath, Path.GetFileNameWithoutExtension(fullPath));
                    }

                    return new FontRuleSource
                    {
                        Mode = FontSourceMode.FontPath,
                        FullPath = fullPath,
                        SourceFile = Path.GetFileName(fullPath),
                        DynamicFontNames = dynamicFontNames,
                        Label = Path.GetFileName(fullPath),
                        CacheKey = $"font_path::{fullPath}::{string.Join("|", dynamicFontNames)}",
                    };
                }
                case FontSourceMode.OsDynamic:
                {
                    List<string> dynamicFontNames = BuildSystemFontCandidateNames(baseName, config.DynamicFontNames);
                    if (dynamicFontNames.Count == 0)
                    {
                        WarnOnce(
                            $"os-dynamic-empty::{jsonPath}",
                            $"[REL] 字体规则 {Path.GetFileName(jsonPath)} 的 dynamic_font_names 为空，已跳过。"
                        );
                        return null;
                    }

                    return new FontRuleSource
                    {
                        Mode = FontSourceMode.OsDynamic,
                        DynamicFontNames = dynamicFontNames,
                        Label = string.Join(", ", dynamicFontNames),
                        CacheKey = $"os_dynamic::{string.Join("|", dynamicFontNames)}",
                    };
                }
                default:
                    return null;
            }
        }

        private static string? ResolveConfiguredSourcePath(
            string? sourceFile,
            string baseName,
            string fontsDir,
            Dictionary<string, List<string>> localSources,
            HashSet<string> allowedExtensions
        )
        {
            if (!string.IsNullOrWhiteSpace(sourceFile))
            {
                string rawSourceFile = sourceFile.Trim();
                string[] candidatePaths = Path.IsPathRooted(rawSourceFile)
                    ? new[] { rawSourceFile }
                    : new[]
                    {
                        Path.Combine(fontsDir, rawSourceFile),
                        Path.Combine(fontsDir, Path.GetFileName(rawSourceFile)),
                    };

                foreach (string candidatePath in candidatePaths.Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    if (!File.Exists(candidatePath))
                    {
                        continue;
                    }

                    string extension = Path.GetExtension(candidatePath);
                    if (!allowedExtensions.Contains(extension))
                    {
                        continue;
                    }

                    return Path.GetFullPath(candidatePath);
                }
            }

            return FindPreferredSourceFile(baseName, localSources, allowedExtensions);
        }

        private static string? FindPreferredSourceFile(
            string baseName,
            Dictionary<string, List<string>> localSources,
            HashSet<string> allowedExtensions
        )
        {
            return localSources.TryGetValue(baseName, out List<string>? candidates)
                ? FindPreferredSourceFile(candidates, allowedExtensions)
                : null;
        }

        private static string? FindPreferredSourceFile(
            IEnumerable<string> candidates,
            HashSet<string> allowedExtensions
        )
        {
            List<string> candidateList = candidates.ToList();
            foreach (string extension in LocalSourceExtensionsByPriority)
            {
                if (!allowedExtensions.Contains(extension))
                {
                    continue;
                }

                string? match = candidateList.FirstOrDefault(
                    candidate => string.Equals(Path.GetExtension(candidate), extension, StringComparison.OrdinalIgnoreCase)
                );
                if (match != null)
                {
                    return match;
                }
            }

            return null;
        }

        private static FontLoadResult GetOrLoadFont(Dictionary<string, FontLoadResult> cache, FontRuleSource source)
        {
            if (cache.TryGetValue(source.CacheKey, out FontLoadResult? cachedResult))
            {
                Logger.LogInfo($"[REL] 复用已缓存的字体来源：{source.Label}");
                return cachedResult;
            }

            FontLoadResult loadedResult = LoadFont(source);
            cache[source.CacheKey] = loadedResult;
            return loadedResult;
        }

        private static FontLoadResult LoadFont(FontRuleSource source)
        {
            switch (source.Mode)
            {
                case FontSourceMode.BundleAsset:
                {
                    Font? bundleFont = LoadFontFromAssetBundle(source.FullPath ?? string.Empty, source.SourceFont);
                    if (bundleFont != null)
                    {
                        Logger.LogInfo($"[REL] bundle_asset 加载成功：{source.Label}");
                    }

                    return new FontLoadResult
                    {
                        Font = bundleFont,
                        Outcome = FontLoadOutcome.BundleAsset,
                    };
                }
                case FontSourceMode.FontPath:
                {
                    Font? pathFont = TryLoadFontFromPath(source.FullPath ?? string.Empty);
                    if (pathFont != null)
                    {
                        Logger.LogInfo(
                            $"[REL] font_path 直接加载成功：{source.Label} -> Unity 字体 {pathFont.name}，dynamic={pathFont.dynamic}，fontSize={pathFont.fontSize}"
                        );
                        return new FontLoadResult
                        {
                            Font = pathFont,
                            Outcome = FontLoadOutcome.FontPathAccepted,
                        };
                    }

                    TryRegisterPrivateFont(source.FullPath ?? string.Empty);
                    Font? fallbackFont = TryCreateDynamicFontFromNames(
                        source.DynamicFontNames,
                        source.Label,
                        $"font-path-fallback::{source.CacheKey}"
                    );
                    if (fallbackFont != null)
                    {
                        Logger.LogInfo($"[REL] font_path -> os_dynamic 回退成功：{source.Label} -> Unity 字体 {fallbackFont.name}");
                    }

                    return new FontLoadResult
                    {
                        Font = fallbackFont,
                        Outcome = FontLoadOutcome.FontPathDynamicFallback,
                    };
                }
                case FontSourceMode.OsDynamic:
                {
                    Font? osDynamicFont = TryCreateDynamicFontFromNames(
                        source.DynamicFontNames,
                        source.Label,
                        $"os-dynamic::{source.CacheKey}"
                    );
                    if (osDynamicFont != null)
                    {
                        Logger.LogInfo($"[REL] os_dynamic 加载成功：{source.Label} -> Unity 字体 {osDynamicFont.name}");
                    }

                    return new FontLoadResult
                    {
                        Font = osDynamicFont,
                        Outcome = FontLoadOutcome.OsDynamic,
                    };
                }
                default:
                    return new FontLoadResult();
            }
        }

        private static Font? TryLoadFontFromPath(string fullPath)
        {
            try
            {
                Font font = new Font(fullPath);
                if (font == null)
                {
                    WarnOnce(
                        $"font-path-null::{fullPath}",
                        $"[REL] font_path 加载失败：{Path.GetFileName(fullPath)} 返回了 null。"
                    );
                    return null;
                }

                string loadedName = NormalizeFontName(font.name);
                if (string.IsNullOrWhiteSpace(loadedName))
                {
                    WarnOnce(
                        $"font-path-empty-name::{fullPath}",
                        $"[REL] font_path 加载失败：{Path.GetFileName(fullPath)} 返回了空字体名。"
                    );
                    return null;
                }

                if (!font.dynamic && font.fontSize <= 0)
                {
                    WarnOnce(
                        $"font-path-invalid::{fullPath}",
                        $"[REL] font_path 加载失败：{Path.GetFileName(fullPath)} 返回的字体不可用，dynamic={font.dynamic}，fontSize={font.fontSize}。"
                    );
                    return null;
                }

                return font;
            }
            catch (Exception ex)
            {
                WarnOnce(
                    $"font-path-exception::{fullPath}",
                    $"[REL] font_path 加载失败：{Path.GetFileName(fullPath)} 抛出异常：{ex.Message}"
                );
                return null;
            }
        }

        private static Font? TryCreateDynamicFontFromNames(
            IReadOnlyList<string> fontNames,
            string label,
            string warningKeyPrefix
        )
        {
            if (fontNames.Count == 0)
            {
                WarnOnce(
                    $"{warningKeyPrefix}::empty",
                    $"[REL] os_dynamic 加载失败：{label} 没有可用的 dynamic_font_names。"
                );
                return null;
            }

            try
            {
                Font font = Font.CreateDynamicFontFromOSFont(fontNames.ToArray(), DynamicFontSize);
                if (font == null)
                {
                    WarnOnce(
                        $"{warningKeyPrefix}::null",
                        $"[REL] os_dynamic 加载失败：{label} 返回了 null。"
                    );
                    return null;
                }

                if (!font.dynamic)
                {
                    WarnOnce(
                        $"{warningKeyPrefix}::non-dynamic",
                        $"[REL] os_dynamic 加载失败：{label} 返回了非动态字体。"
                    );
                    return null;
                }

                string loadedName = NormalizeFontName(font.name);
                if (string.IsNullOrWhiteSpace(loadedName))
                {
                    WarnOnce(
                        $"{warningKeyPrefix}::empty-name",
                        $"[REL] os_dynamic 加载失败：{label} 返回了空字体名。"
                    );
                    return null;
                }

                return font;
            }
            catch (Exception ex)
            {
                WarnOnce(
                    $"{warningKeyPrefix}::exception",
                    $"[REL] os_dynamic 加载失败：{label} 抛出异常：{ex.Message}"
                );
                return null;
            }
        }

        private static List<string> BuildDynamicFontCandidates(string fullPath, string baseName, params object?[] extraSources)
        {
            List<string> candidates = new List<string>();
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (string familyName in ReadFontFamilyNamesFromFile(fullPath))
            {
                AddDynamicFontCandidate(candidates, seen, familyName);
            }

            AddDynamicFontCandidate(candidates, seen, baseName);
            AddDynamicFontCandidate(candidates, seen, $"{baseName}-Regular");
            AddDynamicFontCandidate(candidates, seen, $"{baseName} Regular");
            AddDynamicFontCandidates(candidates, seen, extraSources);
            AddDynamicFontCandidates(candidates, seen, DefaultDynamicFallbackFontNames);
            return candidates;
        }

        private static List<string> BuildSystemFontCandidateNames(string baseName, params object?[] extraSources)
        {
            List<string> candidates = new List<string>();
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            AddDynamicFontCandidates(candidates, seen, extraSources);
            AddDynamicFontCandidate(candidates, seen, baseName);
            AddDynamicFontCandidate(candidates, seen, $"{baseName}-Regular");
            AddDynamicFontCandidate(candidates, seen, $"{baseName} Regular");
            AddDynamicFontCandidates(candidates, seen, DefaultDynamicFallbackFontNames);
            return candidates;
        }

        private static void AddDynamicFontCandidates(List<string> candidates, HashSet<string> seen, params object?[] extraSources)
        {
            foreach (object? extraSource in extraSources)
            {
                switch (extraSource)
                {
                    case null:
                        continue;
                    case string singleName:
                        AddDynamicFontCandidate(candidates, seen, singleName);
                        break;
                    case IEnumerable<string> multipleNames:
                        foreach (string name in multipleNames)
                        {
                            AddDynamicFontCandidate(candidates, seen, name);
                        }

                        break;
                }
            }
        }

        private static List<string> NormalizeDynamicFontNames(IEnumerable<string>? rawNames)
        {
            List<string> normalizedNames = new List<string>();
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (rawNames == null)
            {
                return normalizedNames;
            }

            foreach (string rawName in rawNames)
            {
                AddDynamicFontCandidate(normalizedNames, seen, rawName);
            }

            return normalizedNames;
        }

        private static void AddDynamicFontCandidate(List<string> candidates, HashSet<string> seen, string? name)
        {
            string normalized = NormalizeFontName(name ?? string.Empty);
            if (string.IsNullOrWhiteSpace(normalized) ||
                LooksLikePathValue(normalized) ||
                !seen.Add(normalized))
            {
                return;
            }

            candidates.Add(normalized);
        }

        private static bool LooksLikePathValue(string value)
        {
            return value.IndexOf('\\') >= 0 ||
                   value.IndexOf('/') >= 0 ||
                   value.IndexOf(':') >= 0 ||
                   value.EndsWith(".ttf", StringComparison.OrdinalIgnoreCase) ||
                   value.EndsWith(".otf", StringComparison.OrdinalIgnoreCase);
        }

        private static FontSourceMode? ParseSourceMode(string? sourceMode)
        {
            if (string.IsNullOrWhiteSpace(sourceMode))
            {
                return null;
            }

            return NormalizeFontName(sourceMode).ToLowerInvariant() switch
            {
                BundleAssetModeName => FontSourceMode.BundleAsset,
                FontPathModeName => FontSourceMode.FontPath,
                OsDynamicModeName => FontSourceMode.OsDynamic,
                _ => null,
            };
        }

        private static string GetSourceModeName(FontSourceMode sourceMode)
        {
            return sourceMode switch
            {
                FontSourceMode.BundleAsset => BundleAssetModeName,
                FontSourceMode.FontPath => FontPathModeName,
                FontSourceMode.OsDynamic => OsDynamicModeName,
                _ => throw new ArgumentOutOfRangeException(nameof(sourceMode), sourceMode, null),
            };
        }

        private static void WarnOnce(string key, string message)
        {
            if (!LoggedWarningKeys.Add(key))
            {
                return;
            }

            Logger.LogWarning(message);
        }

        private static bool TryRegisterPrivateFont(string fullPath)
        {
            if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows) || string.IsNullOrWhiteSpace(fullPath))
            {
                return false;
            }

            if (RegisteredPrivateFontFiles.Contains(fullPath))
            {
                return true;
            }

            try
            {
                int addedCount = AddFontResourceEx(fullPath, FrPrivate, IntPtr.Zero);
                if (addedCount > 0)
                {
                    RegisteredPrivateFontFiles.Add(fullPath);
                    Logger.LogInfo($"[REL] 已将外部字体注册为当前进程私有字体：{Path.GetFileName(fullPath)}");
                    return true;
                }

                int errorCode = Marshal.GetLastWin32Error();
                WarnOnce(
                    $"private-font-register::{fullPath}",
                    $"[REL] 外部字体私有注册未返回成功：{Path.GetFileName(fullPath)}，Win32={errorCode}。若字体已安装在系统中，后续仍会继续尝试按字体家族名加载。"
                );
            }
            catch (Exception ex)
            {
                WarnOnce(
                    $"private-font-register-ex::{fullPath}",
                    $"[REL] 外部字体私有注册失败 {Path.GetFileName(fullPath)}：{ex.Message}"
                );
            }

            return false;
        }

        private static IReadOnlyList<string> ReadFontFamilyNamesFromFile(string fullPath)
        {
            try
            {
                using FileStream stream = File.OpenRead(fullPath);
                using BinaryReader reader = new BinaryReader(stream);

                uint signature = ReadUInt32BigEndian(reader);
                if (signature == 0x74746366)
                {
                    WarnOnce(
                        $"ttc-unsupported::{fullPath}",
                        $"[REL] 暂不支持直接解析 TTC 字体家族名：{Path.GetFileName(fullPath)}"
                    );
                    return Array.Empty<string>();
                }

                ushort numTables = ReadUInt16BigEndian(reader);
                reader.ReadUInt16();
                reader.ReadUInt16();
                reader.ReadUInt16();

                uint nameTableOffset = 0;
                uint nameTableLength = 0;
                for (int index = 0; index < numTables; index++)
                {
                    string tag = Encoding.ASCII.GetString(reader.ReadBytes(4));
                    _ = ReadUInt32BigEndian(reader);
                    uint offset = ReadUInt32BigEndian(reader);
                    uint length = ReadUInt32BigEndian(reader);
                    if (tag == "name")
                    {
                        nameTableOffset = offset;
                        nameTableLength = length;
                    }
                }

                if (nameTableOffset == 0 || nameTableLength == 0)
                {
                    return Array.Empty<string>();
                }

                stream.Position = nameTableOffset;
                _ = ReadUInt16BigEndian(reader);
                ushort recordCount = ReadUInt16BigEndian(reader);
                ushort stringOffset = ReadUInt16BigEndian(reader);

                List<FontNameRecord> records = new List<FontNameRecord>();
                for (int index = 0; index < recordCount; index++)
                {
                    records.Add(
                        new FontNameRecord
                        {
                            PlatformId = ReadUInt16BigEndian(reader),
                            EncodingId = ReadUInt16BigEndian(reader),
                            LanguageId = ReadUInt16BigEndian(reader),
                            NameId = ReadUInt16BigEndian(reader),
                            Length = ReadUInt16BigEndian(reader),
                            Offset = ReadUInt16BigEndian(reader),
                        }
                    );
                }

                long stringBaseOffset = nameTableOffset + stringOffset;
                List<string> families = new List<string>();
                HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

                foreach (FontNameRecord record in records.OrderByDescending(GetFontNamePriority))
                {
                    if (record.NameId != 16 && record.NameId != 1)
                    {
                        continue;
                    }

                    stream.Position = stringBaseOffset + record.Offset;
                    byte[] data = reader.ReadBytes(record.Length);
                    string decoded = DecodeFontName(record.PlatformId, data);
                    string normalized = NormalizeFontName(decoded);
                    if (string.IsNullOrWhiteSpace(normalized) || !seen.Add(normalized))
                    {
                        continue;
                    }

                    families.Add(normalized);
                }

                if (families.Count > 0)
                {
                    Logger.LogInfo($"[REL] 从字体文件 {Path.GetFileName(fullPath)} 解析到字体家族：{string.Join(", ", families)}");
                }

                return families;
            }
            catch (Exception ex)
            {
                WarnOnce(
                    $"read-font-family::{fullPath}",
                    $"[REL] 解析字体文件家族名失败 {Path.GetFileName(fullPath)}：{ex.Message}"
                );
                return Array.Empty<string>();
            }
        }

        private static int GetFontNamePriority(FontNameRecord record)
        {
            int score = 0;
            if (record.NameId == 16)
            {
                score += 100;
            }
            else if (record.NameId == 1)
            {
                score += 50;
            }

            if (record.PlatformId == 3)
            {
                score += 20;
            }
            else if (record.PlatformId == 0)
            {
                score += 10;
            }

            if (record.LanguageId == 0x0409 || record.LanguageId == 0)
            {
                score += 5;
            }

            return score;
        }

        private static string DecodeFontName(ushort platformId, byte[] data)
        {
            if (data.Length == 0)
            {
                return string.Empty;
            }

            string decoded = platformId == 0 || platformId == 3
                ? Encoding.BigEndianUnicode.GetString(data)
                : Encoding.UTF8.GetString(data);
            return decoded.Replace("\0", string.Empty).Trim();
        }

        private static ushort ReadUInt16BigEndian(BinaryReader reader)
        {
            byte[] bytes = reader.ReadBytes(2);
            if (bytes.Length < 2)
            {
                throw new EndOfStreamException();
            }

            return (ushort)((bytes[0] << 8) | bytes[1]);
        }

        private static uint ReadUInt32BigEndian(BinaryReader reader)
        {
            byte[] bytes = reader.ReadBytes(4);
            if (bytes.Length < 4)
            {
                throw new EndOfStreamException();
            }

            return ((uint)bytes[0] << 24) |
                   ((uint)bytes[1] << 16) |
                   ((uint)bytes[2] << 8) |
                   bytes[3];
        }

        private static IReadOnlyList<string> InspectAssetBundleFontNames(string fullPath)
        {
            AssetBundle bundle = AssetBundle.LoadFromFile(fullPath);
            if (bundle == null)
            {
                WarnOnce(
                    $"inspect-bundle::{fullPath}",
                    $"[REL] 扫描字体包失败，无法打开 AssetBundle：{fullPath}"
                );
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
                WarnOnce(
                    $"inspect-bundle-fonts::{fullPath}",
                    $"[REL] 扫描字体包中的 Font 资源失败 {Path.GetFileName(fullPath)}：{ex.Message}"
                );
                return Array.Empty<string>();
            }
            finally
            {
                bundle.Unload(false);
            }
        }

        private static Font? LoadFontFromAssetBundle(string fullPath, string? preferredFontName)
        {
            AssetBundle bundle = AssetBundle.LoadFromFile(fullPath);
            if (bundle == null)
            {
                WarnOnce(
                    $"load-bundle::{fullPath}",
                    $"[REL] AssetBundle 打开失败：{fullPath}"
                );
                return null;
            }

            try
            {
                List<Font> fonts = CollectFontsFromAssetBundle(bundle);
                if (fonts.Count == 0)
                {
                    WarnOnce(
                        $"bundle-no-font::{fullPath}",
                        $"[REL] 字体包 {Path.GetFileName(fullPath)} 中未找到 Font 资源。"
                    );
                    return null;
                }

                string normalizedPreferred = NormalizeFontName(preferredFontName ?? string.Empty);
                if (!string.IsNullOrWhiteSpace(normalizedPreferred))
                {
                    Font? preferredFont = fonts.FirstOrDefault(
                        font => string.Equals(NormalizeFontName(font.name), normalizedPreferred, StringComparison.OrdinalIgnoreCase)
                    );
                    if (preferredFont != null)
                    {
                        Logger.LogInfo(
                            $"[REL] 从字体包 {Path.GetFileName(fullPath)} 的 {fonts.Count} 个字体中命中 source_font={normalizedPreferred}。"
                        );
                        return preferredFont;
                    }

                    WarnOnce(
                        $"bundle-font-miss::{fullPath}::{normalizedPreferred}",
                        $"[REL] 字体包 {Path.GetFileName(fullPath)} 中未找到 source_font={normalizedPreferred}，将回退到第一个字体。"
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
                if (font == null)
                {
                    continue;
                }

                if (seenIds.Add(font.GetInstanceID()))
                {
                    fonts.Add(font);
                }
            }

            foreach (UnityEngine.Object asset in bundle.LoadAllAssets())
            {
                if (asset is not Font font)
                {
                    continue;
                }

                if (seenIds.Add(font.GetInstanceID()))
                {
                    fonts.Add(font);
                }
            }

            return fonts;
        }
    }
}
