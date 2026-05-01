using System.Text;
using System.Text.RegularExpressions;
using ReaperEmporiumLocalization.Shared;
using UnityEngine;

namespace ReaperEmporiumLocalization.Core
{
    public static class TsvTranslator
    {
        private static readonly Regex JapaneseRegex = new Regex(@"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]");

        public static TextAsset TranslateTsv(string assetName, string originalText)
        {
            if (string.IsNullOrEmpty(originalText)) return null;

            string[] lines = originalText.Split(new[] { "\r\n", "\n" }, System.StringSplitOptions.None);
            StringBuilder newTsv = new StringBuilder();
            bool hasAnyTranslation = false;

            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i];
                if (string.IsNullOrEmpty(line))
                {
                    newTsv.Append("\n");
                    continue;
                }

                string[] cells = line.Split('\t');
                bool lineModified = false;

                for (int j = 0; j < cells.Length; j++)
                {
                    string cellText = cells[j];
                    if (!string.IsNullOrWhiteSpace(cellText) && JapaneseRegex.IsMatch(cellText))
                    {
                        // 容错：清洗 TSV 单元格中可能存在的隐形回车符
                        string cleanCellText = cellText.Replace("\r", "");

                        if (TranslationManager.Dictionary.TryGetValue(cleanCellText, out string trans))
                        {
                            cells[j] = trans;
                            lineModified = true;
                            hasAnyTranslation = true;
                        }
                    }
                }

                if (lineModified) newTsv.Append(string.Join("\t", cells));
                else newTsv.Append(line);

                if (i < lines.Length - 1) newTsv.Append("\n");
            }

            if (!hasAnyTranslation) return null;
            return new TextAsset(newTsv.ToString()) { name = assetName };
        }
    }
}