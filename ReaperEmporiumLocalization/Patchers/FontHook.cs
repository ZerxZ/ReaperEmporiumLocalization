using HarmonyLib;
using ReaperEmporiumLocalization.Core;
using UnityEngine;
using UnityEngine.UI;

namespace ReaperEmporiumLocalization.Patchers
{
    [HarmonyPatch(typeof(Text), "OnEnable")]
    public static class FontHook
    {
        [HarmonyPostfix]
        public static void Postfix(Text __instance)
        {
            Apply(__instance);
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
    }
}
