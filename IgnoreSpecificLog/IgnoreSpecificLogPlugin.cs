using BepInEx;
using HarmonyLib;
using UnityEngine;
using BepInEx.Logging;

namespace IgnoreSpecificLog
{
    [BepInPlugin("com.zerxz.ignorespecificlog", "Ignore Specific Log", "1.0.0")]
    public class IgnoreSpecificLogPlugin : BaseUnityPlugin
    {
        private void Awake()
        {
            // 启动 Harmony 补丁
            Harmony.CreateAndPatchAll(typeof(IgnoreSpecificLogPlugin));
            Logger.LogInfo("日志过滤插件已加载！");
        }

        // 目标方法：UnityEngine.Debug.Log(object message)
        [HarmonyPatch(typeof(Debug), nameof(Debug.Log), typeof(object))]
        [HarmonyPrefix]
        static bool Prefix_DebugLog(object message)
        {
            if (message != null)
            {
                string msgStr = message.ToString();
                
                // 检查日志是否包含我们想要忽略的特定字符串
                if (msgStr.Contains("をアタッチしているGameObjectはありません"))
                {
                    // 返回 false，拦截原始的 Debug.Log 方法，这条日志就不会被打印出来了
                    return false;
                }
            }
            
            // 返回 true，允许其他正常的日志继续打印
            return true;
        }
    }
}