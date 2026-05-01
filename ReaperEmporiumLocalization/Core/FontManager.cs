using System.Collections.Generic;
using System.IO;
using BepInEx;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared.Models;
using UnityEngine;

namespace ReaperEmporiumLocalization.Core
{
    public class FontReplacementRule
    {
        public Font CustomFont;
        public FontStyle Style; // 🎯 改为存储 Unity 原生的 FontStyle
    }

    public static class FontManager
    {
        public static Dictionary<string, FontReplacementRule> ReplacementRules = new Dictionary<string, FontReplacementRule>();
        private static bool _isInitialized = false;

        public static void InitFont()
        {
            if (_isInitialized) return;

            string fontsDir = Path.Combine(Paths.GameRootPath, "localization", "fonts");
            if (!Directory.Exists(fontsDir))
            {
                Directory.CreateDirectory(fontsDir);
                _isInitialized = true;
                return;
            }

            string[] jsonFiles = Directory.GetFiles(fontsDir, "*.json");
            Dictionary<string, Font> bundleCache = new Dictionary<string, Font>();

            foreach (string jsonPath in jsonFiles)
            {
                string bundleName = Path.GetFileNameWithoutExtension(jsonPath);
                string bundlePath = Path.Combine(fontsDir, bundleName);

                if (!File.Exists(bundlePath)) continue;

                string jsonContent = File.ReadAllText(jsonPath, System.Text.Encoding.UTF8);
                var configs = JsonConvert.DeserializeObject<List<FontConfig>>(jsonContent);
                if (configs == null || configs.Count == 0) continue;

                if (!bundleCache.ContainsKey(bundleName))
                {
                    bundleCache[bundleName] = LoadFontFromAssetBundle(bundlePath);
                }

                Font targetFont = bundleCache[bundleName];
                if (targetFont == null) continue;

                foreach (var config in configs)
                {
                    if (!string.IsNullOrEmpty(config.TargetFont))
                    {
                        // 🎯 核心逻辑：尝试将配置的字符串解析为 Unity 的 FontStyle
                        // 参数 true 代表忽略大小写，解析失败则回退到 Normal
                        if (!System.Enum.TryParse(config.FontStyleStr, true, out FontStyle parsedStyle))
                        {
                            parsedStyle = FontStyle.Normal;
                        }

                        ReplacementRules[config.TargetFont] = new FontReplacementRule
                        {
                            CustomFont = targetFont,
                            Style = parsedStyle // 存入解析好的样式
                        };
                    }
                }
            }

            _isInitialized = true;
        }

        private static Font LoadFontFromAssetBundle(string fullPath)
        {
            var allAssets = AssetBundle.LoadFromFile(fullPath);
            if (allAssets == null) return null;

            foreach (var asset in allAssets.LoadAllAssets())
            {
                if (asset is Font font) return font;
            }
            return null;
        }
    }
}