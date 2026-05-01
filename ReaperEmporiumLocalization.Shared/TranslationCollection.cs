using System.Collections.Generic;

namespace ReaperEmporiumLocalization.Shared
{
    /// <summary>
    /// 单个分类（单个 JSON 文件/表格）的专属翻译抽屉
    /// </summary>
    public class TranslationCategory
    {
        public string CategoryName { get; }
        private readonly Dictionary<string, string> _translations;

        public TranslationCategory(string name)
        {
            CategoryName = name;
            _translations = new Dictionary<string, string>();
        }

        /// <summary>
        /// 尝试添加翻译，如果已存在则跳过并返回 false
        /// </summary>
        public bool AddTranslation(string original, string translation)
        {
            if (!_translations.ContainsKey(original))
            {
                _translations[original] = translation;
                return true;
            }
            return false;
        }

        /// <summary>
        /// 尝试获取翻译文本
        /// </summary>
        public bool TryGetTranslation(string original, out string translation)
        {
            return _translations.TryGetValue(original, out translation);
        }
    }

    /// <summary>
    /// 全局翻译集合管理器（存放所有抽屉的柜子）
    /// </summary>
    public class TranslationCollection
    {
        private readonly Dictionary<string, TranslationCategory> _categories = new Dictionary<string, TranslationCategory>();

        public void Clear()
        {
            _categories.Clear();
        }

        /// <summary>
        /// 向指定的分类中添加翻译记录。如果分类不存在，会自动创建新分类。
        /// </summary>
        public bool AddTranslation(string categoryName, string original, string translation)
        {
            if (!_categories.TryGetValue(categoryName, out TranslationCategory category))
            {
                category = new TranslationCategory(categoryName);
                _categories[categoryName] = category;
            }
            
            return category.AddTranslation(original, translation);
        }

        /// <summary>
        /// 尝试获取指定分类的翻译抽屉
        /// </summary>
        public bool TryGetCategory(string categoryName, out TranslationCategory category)
        {
            return _categories.TryGetValue(categoryName, out category);
        }
    }
}