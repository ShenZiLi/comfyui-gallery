/* ArtMirror 画镜 — 原型 mock 数据（后续由 API 替换为真实数据） */
(function () {
  // 用内置 text_to_image 生成示例图，保证不是占位符
  function imgUrl(scene, size) {
    return "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=" +
      encodeURIComponent(scene) + "&image_size=" + (size || "portrait_4_3");
  }

  var folders = [
    { id: 1, parentId: null, name: "根目录", path: "", count: 8 },
    { id: 2, parentId: 1, name: "角色 2026-08", path: "/角色 2026-08", count: 3 },
    { id: 3, parentId: 1, name: "风景/光效", path: "/风景 光效", count: 3 },
    { id: 4, parentId: 1, name: "实验/废图", path: "/实验 废图", count: 2 },
  ];

  // 共享提示词以体现“同提示词聚合”
  var promptA = "cyberpunk ninja in neon alley, rain reflections, cinematic, ultra detailed";
  var promptB = "portrait of an astronaut, golden hour rim light, film grain, dreamy";

  var images = [
    {
      id: 1, folderId: 2, name: "ComfyUI_00001_.png", width: 1024, height: 1280,
      rating: 5, aiRating: 96, aiReason: "构图完整、光影层次丰富，符合商业质稿标准。",
      prompt: promptA,
      negative: "blurry, lowres, bad anatomy, extra fingers",
      reversePrompt: "photorealistic cyberpunk ninja wearing a dark coat standing in a rainy neon alley, wet road reflections, cinematic color grading, ultra detailed, 8k",
      translationZH: "赛博朋克忍者站在霓虹小巷中，雨夜、路面倒影，电影感调色，超高清。",
      tags: [
        { name: "dreamshaper_8.safetensors", category: "model" },
        { name: "suitsuitslora.safetensors", category: "lora" },
        { name: "vae-ft-mse.safetensors", category: "vae" },
        { name: "realistic", category: "style" },
      ],
      params: { steps: 28, cfg: 7, sampler: "euler", seed: 12345, scheduler: "normal", denoise: 1 },
      thumb: imgUrl("cyberpunk ninja in neon alley, cinematic, rainy reflections"), scene: "ninja-alley"
    },
    {
      id: 2, folderId: 2, name: "ComfyUI_00002_.png", width: 1024, height: 1280,
      rating: 4, aiRating: 91, aiReason: "主体稳定、氛围到位，存在轻微噪点。",
      prompt: promptA,
      negative: "blurry, lowres",
      tags: [
        { name: "dreamshaper_8.safetensors", category: "model" },
        { name: "suitsuitslora.safetensors", category: "lora" },
      ],
      params: { steps: 28, cfg: 7, sampler: "euler", seed: 12346, scheduler: "normal", denoise: 1 },
      thumb: imgUrl("cyberpunk ninja portrait neon alley, cinematic"), scene: "ninja-alley"
    },
    {
      id: 3, folderId: 2, name: "ComfyUI_00003_.png", width: 1024, height: 1280,
      rating: 3, aiRating: 84, aiReason: "构图略显杂乱，主体不够突出。",
      prompt: promptA,
      negative: "blurry, lowres, duplicate",
      reversePrompt: "cyberpunk street ninja mid-action, dynamic pose, neon signs, cinematic depth of field",
      tags: [
        { name: "dreamshaper_8.safetensors", category: "model" },
      ],
      params: { steps: 30, cfg: 6.5, sampler: "euler_ancestral", seed: 999, scheduler: "karras", denoise: 1 },
      thumb: imgUrl("cyberpunk ninja dynamic action neon alley, cinematic dof"), scene: "ninja-alley"
    },
    {
      id: 4, folderId: 3, name: "ComfyUI_00021_.png", width: 896, height: 1152,
      rating: 5, aiRating: 98, aiReason: "光影与人物情绪俱佳，高完成度作品。",
      prompt: promptB,
      negative: "lowres, bad hands, watermark",
      reversePrompt: "portrait of an astronaut with a reflective visor, backlit golden-hour glow, cinematic film still, shallow depth of field",
      translationZH: "宇航员肖像，反光面罩在黄昏逆光下泛金，电影质感，浅景深。",
      tags: [
        { name: "juggernautXL.safetensors", category: "model" },
        { name: "filmstyle.safetensors", category: "lora" },
        { name: "film", category: "style" },
      ],
      params: { steps: 26, cfg: 7.5, sampler: "dpmpp_2m", seed: 555, scheduler: "karras", denoise: 1 },
      thumb: imgUrl("portrait astronaut golden hour rim light, film grain, dreamy"), scene: "astronaut"
    },
    {
      id: 5, folderId: 3, name: "ComfyUI_00022_.png", width: 896, height: 1152,
      rating: 4, aiRating: 88, aiReason: "氛围佳，细节丰富。",
      prompt: promptB,
      negative: "lowres",
      tags: [
        { name: "juggernautXL.safetensors", category: "model" },
        { name: "film", category: "style" },
      ],
      params: { steps: 26, cfg: 7.5, sampler: "dpmpp_2m", seed: 556, scheduler: "karras", denoise: 1 },
      thumb: imgUrl("astronaut portrait backlit warm light, cinematic film still"), scene: "astronaut"
    },
    {
      id: 6, folderId: 3, name: "ComfyUI_00023_.png", width: 1024, height: 1024,
      rating: null, aiRating: 76, aiReason: "构图完整、辨识清晰。",
      prompt: "aurora over snowy mountains, long exposure, vibrant colors",
      negative: "blurry, oversaturated, lens flare",
      tags: [
        { name: "realisticVision.safetensors", category: "model" },
        { name: "landscape", category: "style" },
      ],
      params: { steps: 24, cfg: 6, sampler: "euler", seed: 707, scheduler: "normal", denoise: 1 },
      thumb: imgUrl("aurora borealis snowy mountains long exposure vibrant"), scene: "aurora"
    },
    {
      id: 7, folderId: 4, name: "ComfyUI_00099_.png", width: 832, height: 1120,
      rating: null, aiRating: 61, aiReason: "主体裁切过度，不建议直接使用。",
      prompt: promptA + ", closeup, heavily cropped face",
      negative: "blurry, cropped, deformed",
      tags: [
        { name: "dreamshaper_8.safetensors", category: "model" },
      ],
      params: { steps: 30, cfg: 7, sampler: "euler_ancestral", seed: 3100, scheduler: "karras", denoise: 1 },
      thumb: imgUrl("cyberpunk ninja face closeup heavy crop neon"), scene: "ninja-alley"
    },
    {
      id: 8, folderId: 4, name: "ComfyUI_00100_.png", width: 768, height: 1024,
      rating: 2, aiRating: 44, aiReason: "画面过曝且主体变形。",
      prompt: "abstract ink wash waves, monochrome, minimal",
      negative: "blurry, oversaturated, frame",
      tags: [
        { name: "animePastel.safetensors", category: "model" },
        { name: "minimal", category: "style" },
      ],
      params: { steps: 20, cfg: 5, sampler: "euler", seed: 8123, scheduler: "normal", denoise: 1 },
      thumb: imgUrl("abstract ink wash waves monochrome minimal"), scene: "ink"
    },
  ];

  window.Mock = {
    folders: folders,
    images: images,
    getFolders: function () { return folders; },
    getImages: function () { return images; },
    getImage: function (id) { return images.find(function (i) { return i.id === id; }); },
  };
})();