using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using BepInEx;
using Mono.Cecil;
using Mono.Cecil.Cil;
using Newtonsoft.Json;
using ReaperEmporiumLocalization.Shared;
using ReaperEmporiumLocalization.Shared.Models;

namespace ReaperEmporiumLocalization.Preload
{
    public static class Patcher
    {
        public static IEnumerable<string> TargetDLLs { get; } = new[] { "Assembly-CSharp.dll" };
        private static readonly Regex JapaneseRegex = new Regex(@"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]");

        public static void Patch(AssemblyDefinition assembly)
        {
            LocalizationConfig.Init();
            bool enableDump = LocalizationConfig.EnableDllDump.Value;

            string rootPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "localization");
            string translationPath = Path.Combine(rootPath, "dll_strings", "dll_strings.json");
            string dumpPath = Path.Combine(rootPath, "dump", "dll_strings.json");

            int translationCount = TranslationManager.LoadTranslations(translationPath, true);
            bool hasTranslations = translationCount > 0;
            
            TranslationCategory dllCategory = null;
            if (hasTranslations)
            {
                TranslationManager.Data.TryGetCategory("dll_strings", out dllCategory);
            }
            List<ParatranzData> extractedData = new List<ParatranzData>();
            Dictionary<string, int> methodStringIndexes = new Dictionary<string, int>();

            foreach (var module in assembly.Modules)
            {
                foreach (var type in GetAllTypes(module))
                {
                    foreach (var method in type.Methods)
                    {
                        if (!method.HasBody) continue;

                        foreach (var instruction in method.Body.Instructions)
                        {
                            if (instruction.OpCode == OpCodes.Ldstr)
                            {
                                string rawText = instruction.Operand as string;
                                if (string.IsNullOrEmpty(rawText) || !JapaneseRegex.IsMatch(rawText)) continue;

                                string cleanRawText = rawText.Replace("\r", "");
                                
                                // 🎯 调用类专属的方法
                                if (dllCategory != null && dllCategory.TryGetTranslation(cleanRawText, out string trans))
                                {
                                    instruction.Operand = trans;
                                }

                                // DLL 转储 key 使用 类名.方法名_索引，不再依赖易漂移的 IL 偏移。
                                if (enableDump)
                                {
                                    string methodKey = $"{type.FullName}.{method.Name}";
                                    int stringIndex = methodStringIndexes.TryGetValue(methodKey, out int currentIndex) ? currentIndex : 0;
                                    methodStringIndexes[methodKey] = stringIndex + 1;
                                    string entryKey = $"{methodKey}_{stringIndex}";
                                    string cleanText = rawText.Replace("\r\n", "\\n").Replace("\n", "\\n");
                                    extractedData.Add(new ParatranzData
                                    {
                                        Key = entryKey,
                                        Original = cleanText,
                                        Translation = "",
                                        Stage = StageEnum.未翻译,
                                        Context = ""
                                    });
                                }
                            }
                        }
                    }
                }
            }

            if (enableDump)
            {
                // 只有真的提取到了数据，才生成文件和 dump 文件夹
                if (extractedData.Count > 0)
                {
                    // 获取文件即将被写入的目录 (localization/dump)
                    string dumpDirectory = Path.GetDirectoryName(dumpPath);
                    
                    // 临门一脚：如果目录不存在，才瞬间创建它
                    if (!Directory.Exists(dumpDirectory))
                    {
                        Directory.CreateDirectory(dumpDirectory);
                    }
                    
                    File.WriteAllText(dumpPath, JsonConvert.SerializeObject(extractedData, Formatting.Indented), System.Text.Encoding.UTF8);
                }
            }
        }

        private static IEnumerable<TypeDefinition> GetAllTypes(ModuleDefinition module)
        {
            var types = new List<TypeDefinition>();
            foreach (var t in module.Types) { types.Add(t); AddNested(t, types); }
            return types;
        }

        private static void AddNested(TypeDefinition parent, List<TypeDefinition> types)
        {
            foreach (var n in parent.NestedTypes) { types.Add(n); AddNested(n, types); }
        }
    }
}
