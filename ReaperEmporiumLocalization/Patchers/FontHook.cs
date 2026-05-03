using System.Collections.Generic;
using BepInEx.Logging;
using HarmonyLib;
using ReaperEmporiumLocalization.Core;
using ReaperEmporiumLocalization.Shared;
using UnityEngine;
using UnityEngine.UI;
using Utage;

namespace ReaperEmporiumLocalization.Patchers
{
    [HarmonyPatch(typeof(UguiNovelText), "Awake")]
    public static class FontHook
    {
        private static readonly ManualLogSource Logger = BepInEx.Logging.Logger.CreateLogSource("REL.FontHook");
        private static readonly HashSet<string> LoggedAwakeFonts = new HashSet<string>();

        [HarmonyPostfix]
        public static void Postfix(UguiNovelText __instance)
        {
            Text targetText = ResolveTargetText(__instance);
            if (targetText == null)
            {
                Logger.LogWarning("[REL] UguiNovelText.Awake 未找到可处理的 Text 组件。");
                return;
            }

            LogCurrentFont(targetText);
            FontUsageRecorder.RecordText(targetText);
            SceneTextDumper.RecordAwakeText(targetText);

            bool translated = SceneTextTranslator.TryApplyToText(targetText);
            bool fontChanged = Apply(targetText);

            if (translated)
            {
                Logger.LogInfo($"[REL] Awake 场景文本替换：{SceneTextSupport.GetObjectDescriptor(targetText)}");
            }

            if (fontChanged && targetText.font != null)
            {
                Logger.LogInfo(
                    $"[REL] Awake 字体替换：对象={targetText.name}，当前字体={targetText.font.name}，样式={targetText.fontStyle}"
                );
            }
        }

        public static bool Apply(Text target)
        {
            if (!LocalizationConfig.EnableFontReplacement.Value)
            {
                return false;
            }

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

        private static Text ResolveTargetText(UguiNovelText novelText)
        {
            if (novelText == null)
            {
                return null;
            }

            if (novelText is Text selfText)
            {
                return selfText;
            }

            Text attachedText = novelText.GetComponent<Text>();
            if (attachedText != null)
            {
                return attachedText;
            }

            Text[] childTexts = novelText.GetComponentsInChildren<Text>(true);
            foreach (Text childText in childTexts)
            {
                if (childText != null)
                {
                    return childText;
                }
            }

            return null;
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
