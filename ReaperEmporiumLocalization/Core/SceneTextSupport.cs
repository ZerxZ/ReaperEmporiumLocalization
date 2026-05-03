using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using Utage;

namespace ReaperEmporiumLocalization.Core
{
    public static class SceneTextSupport
    {
        private static readonly Regex JapaneseRegex = new Regex(@"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]");

        public static IEnumerable<Text> EnumerateSceneTexts(Scene scene)
        {
            if (!scene.IsValid() || !scene.isLoaded)
            {
                yield break;
            }

            HashSet<int> seenIds = new HashSet<int>();
            foreach (GameObject root in scene.GetRootGameObjects())
            {
                if (root == null)
                {
                    continue;
                }

                foreach (Text text in root.GetComponentsInChildren<Text>(true))
                {
                    if (text == null)
                    {
                        continue;
                    }

                    if (seenIds.Add(text.GetInstanceID()))
                    {
                        yield return text;
                    }
                }
            }
        }

        public static bool IsNovelText(Text text)
        {
            return text is UguiNovelText;
        }

        public static string GetComponentLabel(Text text)
        {
            return IsNovelText(text) ? "UguiNovelText" : "Text";
        }

        public static bool ContainsJapanese(string text)
        {
            return !string.IsNullOrWhiteSpace(text) && JapaneseRegex.IsMatch(text);
        }

        public static string NormalizeRuntimeText(string text)
        {
            return (text ?? string.Empty).Replace("\r", "");
        }

        public static string EscapeForStorage(string text)
        {
            return NormalizeRuntimeText(text).Replace("\n", "\\n");
        }

        public static string UnescapeStoredText(string text)
        {
            return (text ?? string.Empty).Replace("\\n", "\n").Replace("\r", "");
        }

        public static string NormalizeFontName(string fontName)
        {
            string normalized = (fontName ?? string.Empty).Trim();
            const string cloneSuffix = " (Clone)";
            if (normalized.EndsWith(cloneSuffix))
            {
                normalized = normalized.Substring(0, normalized.Length - cloneSuffix.Length);
            }

            return normalized.Trim();
        }

        public static string GetObjectDescriptor(Text text)
        {
            if (text == null)
            {
                return "<UnknownScene> | Text | <null>";
            }

            Text safeText = text;
            Scene scene = safeText.gameObject.scene;
            string sceneName = scene.IsValid() ? scene.name : "<UnknownScene>";
            return $"{sceneName} | {GetComponentLabel(safeText)} | {GetTransformPath(safeText.transform)}";
        }

        public static string GetTransformPath(Transform transform)
        {
            if (transform == null)
            {
                return "<null>";
            }

            Stack<string> segments = new Stack<string>();
            Transform cursor = transform;
            while (cursor != null)
            {
                segments.Push(cursor.name);
                cursor = cursor.parent;
            }

            return string.Join("/", segments.ToArray());
        }
    }
}
