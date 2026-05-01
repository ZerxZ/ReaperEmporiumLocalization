using HarmonyLib;
using ReaperEmporiumLocalization.Core;
using UnityEngine;
using UnityEngine.UI;
using Utage;

namespace ReaperEmporiumLocalization.Patchers
{
    [HarmonyPatch(typeof(UguiNovelText), "Awake")]
    public class FontHook
    {
        public static void Postfix(Text __instance)
        {
            if (__instance == null || __instance.font == null) return;

            FontManager.InitFont();

            string fontName = __instance.font.name;

            if (FontManager.ReplacementRules.TryGetValue(fontName, out FontReplacementRule rule))
            {
                if (rule.CustomFont != null)
                {
                    // 1. 替换自定义字体
                    __instance.font = rule.CustomFont;
                    
                    // 2. 🎯 直接应用我们在 JSON 中配置好的字体样式
                    __instance.fontStyle = rule.Style;
                }
            }
        }
    }
}