using System;
using HarmonyLib;
using ReaperEmporiumLocalization.Core;
using ReaperEmporiumLocalization.Shared;
using UnityEngine;

namespace ReaperEmporiumLocalization.Patchers
{
    [HarmonyPatch(typeof(AssetBundle))]
    public static class DatabaseHook
    {
        [HarmonyPatch(nameof(AssetBundle.LoadAsset), new Type[] { typeof(string), typeof(Type) })]
        [HarmonyPostfix]
        public static void PostfixLoadAsset(AssetBundle __instance, string name, Type type, ref UnityEngine.Object __result)
        {
            if (__result == null || (type != typeof(TextAsset) && type != typeof(UnityEngine.Object))) return;
            
            TextAsset originalAsset = __result as TextAsset;
            if (originalAsset == null) return;

            string bundleName = __instance.name;
            if (string.IsNullOrEmpty(bundleName)) return;

            // 净化文件名，切除 -CAB-
            string cleanAssetName = name;
            int cabIndex = cleanAssetName.IndexOf("-CAB-");
            if (cabIndex > 0) cleanAssetName = cleanAssetName.Substring(0, cabIndex);

            string cacheKey = $"{bundleName}_{cleanAssetName}";

            // 存入原始缓存，并触发 Dump 提取
            if (!AssetCache.OriginalAssets.ContainsKey(cacheKey))
            {
                AssetCache.OriginalAssets[cacheKey] = originalAsset;
                
                // 🎯 完美恢复 Database 提取功能！
                if (LocalizationConfig.EnableDatabaseDump.Value)
                {
                    DatabaseDumper.DumpTsvToJson(bundleName, cleanAssetName, originalAsset.text);
                }
            }

            // 尝试翻译替换
            if (AssetCache.TranslatedAssets.TryGetValue(cacheKey, out TextAsset cachedTransAsset))
            {
                __result = cachedTransAsset;
                return;
            }

            TextAsset newTransAsset = TsvTranslator.TranslateTsv(cleanAssetName, originalAsset.text);
            if (newTransAsset != null)
            {
                AssetCache.TranslatedAssets[cacheKey] = newTransAsset;
                __result = newTransAsset; 
            }
        }
    }
}