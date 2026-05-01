using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
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
            Dictionary<string, ParatranzData> extractedData = new Dictionary<string, ParatranzData>();

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

                                // 导出的逻辑保持不变，依然需要给 Paratranz 生成一个唯一 Key
                                if (enableDump)
                                {
                                    string ilKey = $"{type.FullName}.{method.Name}_IL_{instruction.Offset:X4}";
                                    if (!extractedData.ContainsKey(ilKey))
                                    {
                                        string cleanText = rawText.Replace("\r\n", "\\n").Replace("\n", "\\n");
                                        extractedData[ilKey] = new ParatranzData
                                        {
                                            Key = ilKey,
                                            Original = cleanText,
                                            Translation = "",
                                            Stage = StageEnum.未翻译,
                                            Context = "" 
                                        };
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if (enableDump)
            {
                var list = extractedData.Values.OrderBy(d => d.Key).ToList();
                
                // 只有真的提取到了数据，才生成文件和 dump 文件夹
                if (list.Count > 0)
                {
                    // 获取文件即将被写入的目录 (localization/dump)
                    string dumpDirectory = Path.GetDirectoryName(dumpPath);
                    
                    // 临门一脚：如果目录不存在，才瞬间创建它
                    if (!Directory.Exists(dumpDirectory))
                    {
                        Directory.CreateDirectory(dumpDirectory);
                    }
                    
                    File.WriteAllText(dumpPath, JsonConvert.SerializeObject(list, Formatting.Indented), System.Text.Encoding.UTF8);
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