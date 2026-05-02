using System.Collections.Generic;
using Newtonsoft.Json;

namespace ReaperEmporiumLocalization.Shared.Models
{
    public class FontConfig
    {
        [JsonProperty("target_font")]
        public string TargetFont { get; set; } = "";

        [JsonProperty("target_fonts")]
        public List<string> TargetFonts { get; set; } = new List<string>();

        // 接收 JSON 里的字符串配置，默认给 "Normal"
        [JsonProperty("font_style")]
        public string FontStyleStr { get; set; } = "Normal";
    }
}
