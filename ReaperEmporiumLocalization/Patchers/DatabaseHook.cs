using System;
using HarmonyLib;
using ReaperEmporiumLocalization.Core;
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

            // 切除 -CAB- 哈希尾巴
            string cleanAssetName = name;
            int cabIndex = cleanAssetName.IndexOf("-CAB-");
            if (cabIndex > 0) cleanAssetName = cleanAssetName.Substring(0, cabIndex);

            string cacheKey = $"{bundleName}_{cleanAssetName}";

            // 存入原始缓存
            if (!AssetCache.OriginalAssets.ContainsKey(cacheKey))
            {
                AssetCache.OriginalAssets[cacheKey] = originalAsset;
                // 如果需要Dump，在这里调用 DatabaseDumper.DumpTsvToJson 即可
            }

            // 尝试读取翻译缓存
            if (AssetCache.TranslatedAssets.TryGetValue(cacheKey, out TextAsset cachedTransAsset))
            {
                __result = cachedTransAsset;
                return;
            }

            // 执行翻译替换
            TextAsset newTransAsset = TsvTranslator.TranslateTsv(cleanAssetName, originalAsset.text);
            if (newTransAsset != null)
            {
                AssetCache.TranslatedAssets[cacheKey] = newTransAsset;
                __result = newTransAsset; 
                
                // 🎯 打印日志：如果你在控制台看到了这条，说明 Hook 成功拦截并替换了！
                Debug.Log($"[REL.Database] 成功拦截并替换表格: {cleanAssetName}");
            }
        }
    }
}