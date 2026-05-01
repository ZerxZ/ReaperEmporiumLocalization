using System.Collections.Generic;
using UnityEngine;
using Utage;

namespace ReaperEmporiumLocalization.Core
{
    public static class AssetCache
    {
        // 缓存池：Key = "BundleName_AssetName"
        public static Dictionary<string, TextAsset> OriginalAssets   = new Dictionary<string, TextAsset>();
        public static Dictionary<string, TextAsset> TranslatedAssets = new Dictionary<string, TextAsset>();

        public static void ClearTranslations()
        {
            TranslatedAssets.Clear();
            //Debug.Log("[REL.Cache] 已清空翻译文本缓存池，准备重新加载！");
        }
    }
}