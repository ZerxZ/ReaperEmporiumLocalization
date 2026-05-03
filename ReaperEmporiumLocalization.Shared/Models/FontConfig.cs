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

        [JsonProperty("font_style")]
        public string FontStyleStr { get; set; } = "Normal";

        [JsonProperty("source_mode", NullValueHandling = NullValueHandling.Ignore)]
        public string? SourceMode { get; set; }

        [JsonProperty("source_file", NullValueHandling = NullValueHandling.Ignore)]
        public string? SourceFile { get; set; }

        [JsonProperty("source_font", NullValueHandling = NullValueHandling.Ignore)]
        public string? SourceFont { get; set; }

        [JsonProperty("dynamic_font_names", NullValueHandling = NullValueHandling.Ignore)]
        public List<string> DynamicFontNames { get; set; } = new List<string>();

        [JsonProperty("custom_font", NullValueHandling = NullValueHandling.Ignore)]
        public string? CustomFont { get; set; }

        public bool ShouldSerializeTargetFont() => !string.IsNullOrWhiteSpace(TargetFont) && TargetFonts.Count == 0;

        public bool ShouldSerializeTargetFonts() => TargetFonts.Count > 0;

        public bool ShouldSerializeSourceMode() => !string.IsNullOrWhiteSpace(SourceMode);

        public bool ShouldSerializeSourceFile() => !string.IsNullOrWhiteSpace(SourceFile);

        public bool ShouldSerializeSourceFont() => !string.IsNullOrWhiteSpace(SourceFont);

        public bool ShouldSerializeDynamicFontNames() => DynamicFontNames.Count > 0;

        public bool ShouldSerializeCustomFont() => !string.IsNullOrWhiteSpace(CustomFont);
    }
}
