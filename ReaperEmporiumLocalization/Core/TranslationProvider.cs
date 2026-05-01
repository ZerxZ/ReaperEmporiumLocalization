using System.IO;
using System.Text;
using BepInEx;
using UnityEngine;

namespace ReaperEmporiumLocalization.Core
{
    public static class TranslationProvider
    {
        private static readonly string DbRoot = Path.Combine(Paths.GameRootPath, "localization", "database");

        public static TextAsset GetTranslatedTextAsset(string bundleName, string assetName)
        {
            string folder = Path.Combine(DbRoot, bundleName);
            if (!Directory.Exists(folder)) return null;

            string finalPath = null;
            string tsvPath   = Path.Combine(folder, assetName + ".tsv");
            string txtPath   = Path.Combine(folder, assetName + ".txt");

            if (File.Exists(tsvPath)) finalPath = tsvPath;
            else if (File.Exists(txtPath)) finalPath = txtPath;

            if (finalPath != null)
            {
                string text = File.ReadAllText(finalPath, Encoding.UTF8);
                return new TextAsset(text) { name = assetName };
            }
            return null;
        }
    }
}