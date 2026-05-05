class LocalizationToolError(Exception):
    """汉化辅助工具的基础异常。"""


class ConfigurationError(LocalizationToolError):
    """缺少必要本地配置时抛出，例如未设置游戏目录或 ParaTranz token。"""


class SafePathError(LocalizationToolError):
    """文件操作可能越过预期根目录时抛出，用于避免误删或误写。"""


__all__ = ["ConfigurationError", "LocalizationToolError", "SafePathError"]
