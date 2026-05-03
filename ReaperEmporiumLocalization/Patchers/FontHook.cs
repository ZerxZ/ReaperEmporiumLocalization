using HarmonyLib;
using BepInEx.Logging;
using ReaperEmporiumLocalization.Core;
using UnityEngine;
using UnityEngine.UI;
using Utage;
using System.Collections.Generic;

namespace ReaperEmporiumLocalization.Patchers
{
    [HarmonyPatch(typeof(UguiNovelText), "Awake")]
    public static class FontHook
    {
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.FontHook");
        private static readonly HashSet<string> LoggedAwakeFonts = new HashSet<string>();

        [HarmonyPostfix]
        public static void Postfix(Text __instance)
        {
            LogCurrentFont(__instance);
            bool changed = Apply(__instance);
            if (changed && __instance != null && __instance.font != null)
            {
                Logger.LogInfo(
                    $"[REL] Awake 字体替换：对象={__instance.name}，当前字体={__instance.font.name}，样式={__instance.fontStyle}"
                );
            }
        }

        public static bool Apply(Text target)
        {
            return FontManager.TryApply(target);
        }

        public static int RefreshAllTexts()
        {
            int changedCount = 0;
            Text[] texts = Resources.FindObjectsOfTypeAll<Text>();
            foreach (Text text in texts)
            {
                if (Apply(text))
                {
                    changedCount++;
                }
            }

            return changedCount;
        }

        private static void LogCurrentFont(Text target)
        {
            if (target == null)
            {
                return;
            }

            string fontName = target.font == null ? "<null>" : target.font.name;
            string logKey = $"{fontName}|{target.fontStyle}";
            if (LoggedAwakeFonts.Add(logKey))
            {
                Logger.LogInfo(
                    $"[REL] Awake 检测到本体字体：对象={target.name}，字体={fontName}，样式={target.fontStyle}"
                );
            }
        }
    }
}
