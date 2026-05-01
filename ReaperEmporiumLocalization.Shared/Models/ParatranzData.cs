using Newtonsoft.Json;
namespace ReaperEmporiumLocalization.Shared.Models;

public class ParatranzData
{
    [JsonProperty("key")]
    public string Key { get; set; } = "";

    [JsonProperty("original")]
    public string Original { get; set; } = "";

    [JsonProperty("translation")]
    public string Translation { get; set; } = "";

    [JsonProperty("stage")]
    public StageEnum Stage { get; set; } = StageEnum.未翻译;

    [JsonProperty("context")]
    public string Context { get; set; } = "";
}