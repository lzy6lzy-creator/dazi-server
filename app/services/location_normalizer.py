from __future__ import annotations

import re
from dataclasses import dataclass


ACTIVITY_STRICTNESS = {
    "吃饭": "strict",
    "喝茶": "strict",
    "咖啡": "strict",
    "喝咖啡": "strict",
    "酒吧": "strict",
    "看展": "strict",
    "健身": "strict",
    "运动": "strict",
    "看电影": "medium",
    "电影": "medium",
    "桌游": "medium",
    "city walk": "medium",
    "散步": "medium",
    "逛街": "medium",
    "公园": "medium",
    "露营": "loose",
    "徒步": "loose",
    "爬山": "loose",
    "自驾": "loose",
    "旅行": "loose",
    "周边游": "loose",
    "泡温泉": "loose",
    "线上聊天": "none",
    "闲聊": "none",
    "游戏": "none",
}

CITY_CATALOG = {
    "上海": {"aliases": ["上海市", "魔都", "沪上"], "region": "长三角"},
    "北京": {"aliases": ["北京市", "帝都"], "region": "京津冀"},
    "广州": {"aliases": ["广州市", "羊城", "花城"], "region": "珠三角"},
    "深圳": {"aliases": ["深圳市", "鹏城"], "region": "珠三角"},
    "成都": {"aliases": ["成都市", "蓉城"], "region": "四川"},
    "杭州": {"aliases": ["杭州市"], "region": "长三角"},
    "南京": {"aliases": ["南京市", "金陵"], "region": "长三角"},
    "苏州": {"aliases": ["苏州市", "姑苏"], "region": "长三角"},
    "天津": {"aliases": ["天津市"], "region": "京津冀"},
    "厦门": {"aliases": ["厦门市", "鹭岛"], "region": "福建"},
    "香港": {"aliases": ["香港特别行政区", "港岛"], "region": "港澳"},
    "澳门": {"aliases": ["澳门特别行政区"], "region": "港澳"},
    "台北": {"aliases": ["台北市"], "region": "台湾"},
    "新加坡": {"aliases": ["坡县", "狮城"], "region": "新加坡"},
    "东京": {"aliases": ["东京市"], "region": "关东"},
    "京都": {"aliases": ["京都市"], "region": "关西"},
    "大阪": {"aliases": ["大阪市"], "region": "关西"},
    "神户": {"aliases": ["神户市"], "region": "关西"},
    "奈良": {"aliases": ["奈良市"], "region": "关西"},
    "横滨": {"aliases": ["横滨市"], "region": "关东"},
    "大理": {"aliases": ["大理市"], "region": "云南"},
    "丽江": {"aliases": ["丽江市"], "region": "云南"},
    "昆明": {"aliases": ["昆明市", "春城"], "region": "云南"},
    "佛山": {"aliases": ["佛山市"], "region": "珠三角"},
    "珠海": {"aliases": ["珠海市"], "region": "珠三角"},
    "东莞": {"aliases": ["东莞市"], "region": "珠三角"},
    "惠州": {"aliases": ["惠州市"], "region": "珠三角"},
    "中山": {"aliases": ["中山市"], "region": "珠三角"},
    "武汉": {"aliases": ["武汉市", "江城"], "region": "华中"},
    "重庆": {"aliases": ["重庆市", "山城"], "region": "成渝"},
    "西安": {"aliases": ["西安市", "长安"], "region": "关中"},
    "长沙": {"aliases": ["长沙市", "星城"], "region": "湖南"},
    "青岛": {"aliases": ["青岛市"], "region": "山东"},
    "大连": {"aliases": ["大连市"], "region": "辽宁"},
    "郑州": {"aliases": ["郑州市"], "region": "河南"},
    "济南": {"aliases": ["济南市", "泉城"], "region": "山东"},
    "沈阳": {"aliases": ["沈阳市"], "region": "辽宁"},
    "宁波": {"aliases": ["宁波市"], "region": "长三角"},
    "无锡": {"aliases": ["无锡市"], "region": "长三角"},
    "合肥": {"aliases": ["合肥市"], "region": "长三角"},
    "福州": {"aliases": ["福州市"], "region": "福建"},
    "泉州": {"aliases": ["泉州市"], "region": "福建"},
    "绍兴": {"aliases": ["绍兴市"], "region": "长三角"},
    "嘉兴": {"aliases": ["嘉兴市"], "region": "长三角"},
    "湖州": {"aliases": ["湖州市"], "region": "长三角"},
    "温州": {"aliases": ["温州市"], "region": "浙江"},
    "三亚": {"aliases": ["三亚市"], "region": "海南"},
    "海口": {"aliases": ["海口市"], "region": "海南"},
    "拉萨": {"aliases": ["拉萨市"], "region": "西藏"},
    "乌鲁木齐": {"aliases": ["乌市"], "region": "新疆"},
    "哈尔滨": {"aliases": ["哈尔滨市", "冰城"], "region": "黑龙江"},
    "长春": {"aliases": ["长春市"], "region": "吉林"},
    "贵阳": {"aliases": ["贵阳市"], "region": "贵州"},
    "南宁": {"aliases": ["南宁市"], "region": "广西"},
    "石家庄": {"aliases": ["石家庄市"], "region": "京津冀"},
    "太原": {"aliases": ["太原市"], "region": "山西"},
    "呼和浩特": {"aliases": ["呼市"], "region": "内蒙古"},
    "银川": {"aliases": ["银川市"], "region": "宁夏"},
    "兰州": {"aliases": ["兰州市"], "region": "甘肃"},
    "西宁": {"aliases": ["西宁市"], "region": "青海"},
    "首尔": {"aliases": ["首尔市", "汉城"], "region": "韩国"},
    "曼谷": {"aliases": ["曼谷市"], "region": "泰国"},
    "清迈": {"aliases": ["清迈市"], "region": "泰国"},
    "吉隆坡": {"aliases": ["KL"], "region": "马来西亚"},
    "槟城": {"aliases": ["槟城州"], "region": "马来西亚"},
    "伦敦": {"aliases": ["London"], "region": "英国"},
    "巴黎": {"aliases": ["Paris"], "region": "法国"},
    "纽约": {"aliases": ["纽约市", "New York"], "region": "美国东岸"},
    "洛杉矶": {"aliases": ["LA", "Los Angeles"], "region": "美国西岸"},
    "旧金山": {"aliases": ["SF", "San Francisco"], "region": "美国西岸"},
    "西雅图": {"aliases": ["Seattle"], "region": "美国西岸"},
    "悉尼": {"aliases": ["Sydney"], "region": "澳洲"},
    "墨尔本": {"aliases": ["Melbourne"], "region": "澳洲"},
    "温哥华": {"aliases": ["Vancouver"], "region": "加拿大"},
    "多伦多": {"aliases": ["Toronto"], "region": "加拿大"},
}

CITY_ALIASES = {
    alias: city
    for city, data in CITY_CATALOG.items()
    for alias in [city, *data["aliases"]]
}

CITY_REGION = {
    city: str(data["region"])
    for city, data in CITY_CATALOG.items()
}

REGIONS = {
    "川西": {
        "aliases": ["川西", "川西线", "川西小环线", "川西大环线", "甘孜", "阿坝", "康定", "理塘"],
        "cities": ["成都"],
        "anchor_city": None,
        "admin_region": "四川",
        "geo_scope": "travel",
        "places": ["四姑娘山", "稻城亚丁", "色达", "新都桥", "海螺沟", "毕棚沟", "九寨沟", "黄龙"],
    },
    "成都周边": {
        "aliases": ["成都周边", "成都周边山里", "成都附近", "蓉城周边"],
        "cities": ["成都"],
        "anchor_city": "成都",
        "admin_region": "四川",
        "geo_scope": "travel",
        "places": ["都江堰", "青城山", "彭州", "崇州", "川西", "四姑娘山"],
    },
    "江浙沪": {
        "aliases": ["江浙沪", "包邮区", "苏杭沪"],
        "cities": ["上海", "杭州", "南京", "苏州", "无锡", "宁波", "绍兴", "嘉兴", "湖州"],
        "anchor_city": None,
        "admin_region": "江浙沪",
        "geo_scope": "cross_city",
        "places": ["西湖", "苏州园林", "金鸡湖", "平江路", "乌镇", "西塘", "莫干山", "千岛湖"],
    },
    "长三角": {
        "aliases": ["长三角", "江浙沪皖"],
        "cities": ["上海", "杭州", "南京", "苏州", "无锡", "宁波", "合肥", "绍兴", "嘉兴", "湖州"],
        "anchor_city": None,
        "admin_region": "长三角",
        "geo_scope": "cross_city",
        "places": ["西湖", "苏州园林", "金鸡湖", "平江路", "乌镇", "西塘", "莫干山", "千岛湖"],
    },
    "上海周边": {
        "aliases": ["上海周边", "上海附近", "沪周边", "苏杭方向"],
        "cities": ["上海", "杭州", "苏州", "南京", "无锡", "嘉兴", "湖州"],
        "anchor_city": "上海",
        "admin_region": "长三角",
        "geo_scope": "cross_city",
        "places": ["苏州园林", "西湖", "金鸡湖", "平江路", "乌镇", "西塘", "莫干山"],
    },
    "杭州周边": {
        "aliases": ["杭州周边", "杭州附近"],
        "cities": ["杭州", "绍兴", "嘉兴", "湖州", "宁波"],
        "anchor_city": "杭州",
        "admin_region": "长三角",
        "geo_scope": "cross_city",
        "places": ["西湖", "千岛湖", "莫干山", "乌镇", "西塘"],
    },
    "珠三角": {
        "aliases": ["珠三角", "广深佛莞", "广深周边"],
        "cities": ["广州", "深圳", "佛山", "东莞", "珠海", "惠州", "中山", "香港", "澳门"],
        "anchor_city": None,
        "admin_region": "珠三角",
        "geo_scope": "cross_city",
        "places": ["大鹏", "岭南天地", "长隆", "珠江新城", "前海", "南澳", "港珠澳大桥"],
    },
    "粤港澳大湾区": {
        "aliases": ["粤港澳大湾区", "大湾区", "湾区"],
        "cities": ["广州", "深圳", "佛山", "东莞", "珠海", "惠州", "中山", "香港", "澳门"],
        "anchor_city": None,
        "admin_region": "珠三角",
        "geo_scope": "cross_city",
        "places": ["大鹏", "岭南天地", "长隆", "珠江新城", "前海", "南澳", "港珠澳大桥"],
    },
    "京津冀": {
        "aliases": ["京津冀", "北京天津河北"],
        "cities": ["北京", "天津", "石家庄"],
        "anchor_city": None,
        "admin_region": "京津冀",
        "geo_scope": "cross_city",
        "places": ["蓟州", "滨海", "北戴河", "阿那亚", "古北水镇"],
    },
    "北京周边": {
        "aliases": ["北京周边", "北京附近", "京郊", "北京郊区"],
        "cities": ["北京", "天津", "石家庄"],
        "anchor_city": "北京",
        "admin_region": "京津冀",
        "geo_scope": "cross_city",
        "places": ["通州", "怀柔", "密云", "延庆", "蓟州", "古北水镇", "北戴河", "阿那亚"],
    },
    "成渝": {
        "aliases": ["成渝", "成渝地区", "成都重庆", "重庆成都"],
        "cities": ["成都", "重庆"],
        "anchor_city": None,
        "admin_region": "成渝",
        "geo_scope": "cross_city",
        "places": ["太古里", "春熙路", "解放碑", "洪崖洞"],
    },
    "云南": {
        "aliases": ["云南", "滇西", "大理丽江", "昆大丽"],
        "cities": ["昆明", "大理", "丽江"],
        "anchor_city": None,
        "admin_region": "云南",
        "geo_scope": "travel",
        "places": ["洱海", "古城", "玉龙雪山", "香格里拉", "西双版纳"],
    },
    "厦漳泉": {
        "aliases": ["厦漳泉", "福建沿海", "闽南"],
        "cities": ["厦门", "福州", "泉州"],
        "anchor_city": None,
        "admin_region": "福建",
        "geo_scope": "cross_city",
        "places": ["鼓浪屿", "曾厝垵", "西街"],
    },
    "港澳": {
        "aliases": ["港澳", "香港澳门"],
        "cities": ["香港", "澳门"],
        "anchor_city": None,
        "admin_region": "港澳",
        "geo_scope": "cross_city",
        "places": ["中环", "铜锣湾", "尖沙咀", "旺角", "威尼斯人"],
    },
    "东京周边": {
        "aliases": ["东京周边", "东京附近", "关东"],
        "cities": ["东京", "横滨"],
        "anchor_city": "东京",
        "admin_region": "关东",
        "geo_scope": "travel",
        "places": ["箱根", "镰仓", "横滨", "富士山", "河口湖"],
    },
    "关西": {
        "aliases": ["关西", "大阪京都", "京阪神"],
        "cities": ["京都", "大阪", "神户", "奈良"],
        "anchor_city": None,
        "admin_region": "关西",
        "geo_scope": "travel",
        "places": ["岚山", "伏见稻荷", "心斋桥", "梅田", "奈良公园"],
    },
    "东南亚": {
        "aliases": ["东南亚", "新马泰"],
        "cities": ["新加坡", "曼谷", "清迈", "吉隆坡", "槟城"],
        "anchor_city": None,
        "admin_region": "东南亚",
        "geo_scope": "travel",
        "places": ["牛车水", "乌节路", "滨海湾", "圣淘沙"],
    },
}

PLACES = {
    "浦东": {"aliases": ["浦东", "浦东新区", "陆家嘴"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "武康路": {"aliases": ["武康路"], "kind": "landmark", "city": "上海", "region": "长三角"},
    "静安": {"aliases": ["静安", "静安区"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "外滩": {"aliases": ["外滩", "The Bund"], "kind": "landmark", "city": "上海", "region": "长三角"},
    "新天地": {"aliases": ["新天地"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "人民广场": {"aliases": ["人民广场", "人广"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "徐家汇": {"aliases": ["徐家汇"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "五角场": {"aliases": ["五角场"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "南京西路": {"aliases": ["南京西路", "南西"], "kind": "neighborhood", "city": "上海", "region": "长三角"},
    "朝阳": {"aliases": ["朝阳", "朝阳区"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "北京环球影城": {"aliases": ["环球影城", "北京环球影城"], "kind": "venue", "city": "北京", "region": "京津冀"},
    "通州": {"aliases": ["通州", "通州区"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "三里屯": {"aliases": ["三里屯"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "国贸": {"aliases": ["国贸", "CBD"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "望京": {"aliases": ["望京"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "五道口": {"aliases": ["五道口"], "kind": "neighborhood", "city": "北京", "region": "京津冀"},
    "798": {"aliases": ["798", "798艺术区"], "kind": "landmark", "city": "北京", "region": "京津冀"},
    "颐和园": {"aliases": ["颐和园"], "kind": "landmark", "city": "北京", "region": "京津冀"},
    "西湖": {"aliases": ["西湖"], "kind": "landmark", "city": "杭州", "region": "长三角"},
    "滨江": {"aliases": ["滨江", "滨江区"], "kind": "neighborhood", "city": "杭州", "region": "长三角"},
    "钱江新城": {"aliases": ["钱江新城"], "kind": "neighborhood", "city": "杭州", "region": "长三角"},
    "武林": {"aliases": ["武林", "武林广场"], "kind": "neighborhood", "city": "杭州", "region": "长三角"},
    "新街口": {"aliases": ["新街口"], "kind": "neighborhood", "city": "南京", "region": "长三角"},
    "夫子庙": {"aliases": ["夫子庙"], "kind": "landmark", "city": "南京", "region": "长三角"},
    "玄武湖": {"aliases": ["玄武湖"], "kind": "landmark", "city": "南京", "region": "长三角"},
    "苏州园林": {"aliases": ["苏州园林"], "kind": "landmark", "city": "苏州", "region": "长三角"},
    "金鸡湖": {"aliases": ["金鸡湖"], "kind": "landmark", "city": "苏州", "region": "长三角"},
    "平江路": {"aliases": ["平江路"], "kind": "landmark", "city": "苏州", "region": "长三角"},
    "南山": {"aliases": ["南山", "南山区"], "kind": "neighborhood", "city": "深圳", "region": "珠三角"},
    "科技园": {"aliases": ["科技园", "深圳科技园"], "kind": "neighborhood", "city": "深圳", "region": "珠三角"},
    "福田": {"aliases": ["福田", "福田区"], "kind": "neighborhood", "city": "深圳", "region": "珠三角"},
    "蛇口": {"aliases": ["蛇口"], "kind": "neighborhood", "city": "深圳", "region": "珠三角"},
    "宝安": {"aliases": ["宝安", "宝安区"], "kind": "neighborhood", "city": "深圳", "region": "珠三角"},
    "天河": {"aliases": ["天河", "天河区"], "kind": "neighborhood", "city": "广州", "region": "珠三角"},
    "珠江新城": {"aliases": ["珠江新城"], "kind": "neighborhood", "city": "广州", "region": "珠三角"},
    "越秀": {"aliases": ["越秀", "越秀区"], "kind": "neighborhood", "city": "广州", "region": "珠三角"},
    "北京路": {"aliases": ["北京路"], "kind": "neighborhood", "city": "广州", "region": "珠三角"},
    "长隆": {"aliases": ["长隆", "广州长隆", "珠海长隆"], "kind": "venue", "city": "广州", "region": "珠三角"},
    "岭南天地": {"aliases": ["岭南天地"], "kind": "landmark", "city": "佛山", "region": "珠三角"},
    "大鹏": {"aliases": ["大鹏"], "kind": "landmark", "city": "深圳", "region": "珠三角"},
    "中环": {"aliases": ["中环"], "kind": "neighborhood", "city": "香港", "region": "港澳"},
    "铜锣湾": {"aliases": ["铜锣湾"], "kind": "neighborhood", "city": "香港", "region": "港澳"},
    "尖沙咀": {"aliases": ["尖沙咀", "TST"], "kind": "neighborhood", "city": "香港", "region": "港澳"},
    "旺角": {"aliases": ["旺角"], "kind": "neighborhood", "city": "香港", "region": "港澳"},
    "牛车水": {"aliases": ["牛车水"], "kind": "neighborhood", "city": "新加坡", "region": "新加坡"},
    "乌节路": {"aliases": ["乌节路"], "kind": "neighborhood", "city": "新加坡", "region": "新加坡"},
    "滨海湾": {"aliases": ["滨海湾", "Marina Bay"], "kind": "landmark", "city": "新加坡", "region": "新加坡"},
    "圣淘沙": {"aliases": ["圣淘沙"], "kind": "landmark", "city": "新加坡", "region": "新加坡"},
    "鼓浪屿": {"aliases": ["鼓浪屿"], "kind": "landmark", "city": "厦门", "region": "福建"},
    "曾厝垵": {"aliases": ["曾厝垵"], "kind": "neighborhood", "city": "厦门", "region": "福建"},
    "太古里": {"aliases": ["太古里"], "kind": "neighborhood", "city": "成都", "region": "四川"},
    "春熙路": {"aliases": ["春熙路"], "kind": "neighborhood", "city": "成都", "region": "四川"},
    "宽窄巷子": {"aliases": ["宽窄巷子"], "kind": "landmark", "city": "成都", "region": "四川"},
    "天府广场": {"aliases": ["天府广场"], "kind": "neighborhood", "city": "成都", "region": "四川"},
    "四姑娘山": {"aliases": ["四姑娘山"], "kind": "landmark", "city": None, "region": "四川"},
    "稻城亚丁": {"aliases": ["稻城亚丁"], "kind": "landmark", "city": None, "region": "四川"},
    "九寨沟": {"aliases": ["九寨沟"], "kind": "landmark", "city": None, "region": "四川"},
    "青城山": {"aliases": ["青城山"], "kind": "landmark", "city": "成都", "region": "四川"},
    "都江堰": {"aliases": ["都江堰"], "kind": "landmark", "city": "成都", "region": "四川"},
    "箱根": {"aliases": ["箱根"], "kind": "landmark", "city": None, "region": "关东"},
    "新宿": {"aliases": ["新宿"], "kind": "neighborhood", "city": "东京", "region": "关东"},
    "涩谷": {"aliases": ["涩谷", "渋谷"], "kind": "neighborhood", "city": "东京", "region": "关东"},
    "银座": {"aliases": ["银座"], "kind": "neighborhood", "city": "东京", "region": "关东"},
    "池袋": {"aliases": ["池袋"], "kind": "neighborhood", "city": "东京", "region": "关东"},
    "镰仓": {"aliases": ["镰仓"], "kind": "landmark", "city": None, "region": "关东"},
    "河口湖": {"aliases": ["河口湖"], "kind": "landmark", "city": None, "region": "关东"},
    "岚山": {"aliases": ["岚山"], "kind": "landmark", "city": "京都", "region": "关西"},
    "伏见稻荷": {"aliases": ["伏见稻荷", "伏见稻荷大社"], "kind": "landmark", "city": "京都", "region": "关西"},
    "心斋桥": {"aliases": ["心斋桥"], "kind": "neighborhood", "city": "大阪", "region": "关西"},
    "梅田": {"aliases": ["梅田"], "kind": "neighborhood", "city": "大阪", "region": "关西"},
    "奈良公园": {"aliases": ["奈良公园"], "kind": "landmark", "city": "奈良", "region": "关西"},
    "洱海": {"aliases": ["洱海", "大理洱海"], "kind": "landmark", "city": "大理", "region": "云南"},
    "丽江古城": {"aliases": ["丽江古城", "古城"], "kind": "landmark", "city": "丽江", "region": "云南"},
    "玉龙雪山": {"aliases": ["玉龙雪山"], "kind": "landmark", "city": "丽江", "region": "云南"},
    "蓟州": {"aliases": ["蓟州"], "kind": "landmark", "city": "天津", "region": "京津冀"},
    "滨海": {"aliases": ["滨海", "滨海新区"], "kind": "neighborhood", "city": "天津", "region": "京津冀"},
    "解放碑": {"aliases": ["解放碑"], "kind": "neighborhood", "city": "重庆", "region": "成渝"},
    "洪崖洞": {"aliases": ["洪崖洞"], "kind": "landmark", "city": "重庆", "region": "成渝"},
}


@dataclass(frozen=True)
class PlaceProfile:
    place_raw: str
    place_kind: str
    place_normalized: str | None
    admin_city: str | None
    admin_region: str | None
    geo_scope: str
    aliases: tuple[str, ...] = ()
    confidence: float = 0.0


def compact_text(*values: str | None) -> str:
    return " ".join(str(value).strip() for value in values if value and str(value).strip())


def normalize_suffix(text: str) -> str:
    value = text.strip()
    for suffix in ["新区", "市", "区", "县"]:
        if value.endswith(suffix) and len(value) > len(suffix) + 1:
            value = value[: -len(suffix)]
    return value


def activity_strictness(activity_type: str | None) -> str:
    raw = (activity_type or "").strip().lower()
    for key, strictness in ACTIVITY_STRICTNESS.items():
        if key.lower() in raw:
            return strictness
    return "medium"


def find_city(text: str | None) -> str | None:
    if not text:
        return None
    normalized = normalize_suffix(text)
    for alias, city in sorted(CITY_ALIASES.items(), key=lambda item: (-len(item[0]), item[0])):
        if alias in text or alias == normalized:
            return city
    return None


def canonical_region_name(region_name: str | None) -> str | None:
    if not region_name:
        return None
    normalized = normalize_suffix(region_name)
    if normalized in REGIONS:
        return normalized
    for name, data in sorted(REGIONS.items(), key=lambda item: (-max(len(a) for a in item[1]["aliases"]), item[0])):
        aliases = [name, *data["aliases"]]
        if any(alias in region_name or alias == normalized for alias in aliases):
            return name
    return None


def find_region(text: str) -> str | None:
    for name, data in sorted(REGIONS.items(), key=lambda item: (-max(len(a) for a in item[1]["aliases"]), item[0])):
        if any(alias in text for alias in data["aliases"]):
            return name
    return None


def find_place(text: str) -> str | None:
    for name, data in sorted(PLACES.items(), key=lambda item: (-max(len(a) for a in item[1]["aliases"]), item[0])):
        if any(alias in text for alias in data["aliases"]):
            return name
    return None


def region_aliases(region_name: str) -> tuple[str, ...]:
    canonical = canonical_region_name(region_name)
    if not canonical:
        return ()
    region = REGIONS[canonical]
    return tuple(dict.fromkeys(region["aliases"] + region["cities"] + region["places"]))


def cities_for_region(region_name: str | None) -> tuple[str, ...]:
    canonical = canonical_region_name(region_name)
    if not canonical:
        return ()
    return tuple(REGIONS[canonical]["cities"])


def region_contains_city(city: str | None, region_name: str | None) -> bool:
    city_name = find_city(city) or normalize_suffix(city or "")
    if not city_name:
        return False
    return city_name in cities_for_region(region_name)


def align_city_from_catalog(city_raw: str | None) -> str | None:
    if not city_raw or not city_raw.strip():
        return None
    text = city_raw.strip()
    city_name = find_city(text)
    if city_name:
        return city_name
    place_name = find_place(text)
    if place_name:
        return PLACES[place_name]["city"] or None
    region_name = find_region(text)
    if region_name:
        region = REGIONS[region_name]
        anchor_city = region.get("anchor_city")
        if anchor_city:
            return str(anchor_city)
        cities = list(region.get("cities") or [])
        if len(cities) == 1:
            return str(cities[0])
    return None


def standard_city_names() -> tuple[str, ...]:
    return tuple(CITY_CATALOG.keys())


def normalize_place(
    *,
    activity_type: str | None,
    city: str | None,
    location: str | None,
) -> PlaceProfile:
    raw = compact_text(city, location)
    if not raw:
        return PlaceProfile("", "unknown", None, None, None, "unknown", confidence=0.0)

    if any(token in raw for token in ["线上", "远程", "视频"]):
        return PlaceProfile(raw, "online", "线上", None, None, "none", ("线上", "远程"), 1.0)
    if any(token in raw for token in ["不限地点", "不限", "都可以", "随意"]):
        return PlaceProfile(raw, "flexible", "不限地点", None, None, "none", ("不限地点",), 0.95)

    region_name = find_region(raw)
    if region_name:
        region = REGIONS[region_name]
        admin_city = region.get("anchor_city") or None
        return PlaceProfile(
            raw,
            "region",
            region_name,
            admin_city,
            str(region["admin_region"]),
            str(region["geo_scope"]),
            region_aliases(region_name),
            0.95,
        )

    place_name = find_place(raw)
    if place_name:
        place = PLACES[place_name]
        admin_city = place["city"] or find_city(city)
        return PlaceProfile(
            raw,
            str(place["kind"]),
            place_name,
            admin_city,
            str(place["region"]),
            "travel" if place["city"] is None or (activity_strictness(activity_type) == "loose" and not find_city(city)) else "local",
            tuple(place["aliases"]),
            0.9,
        )

    city_name = find_city(raw)
    if city_name:
        return PlaceProfile(
            raw,
            "city",
            city_name,
            city_name,
            CITY_REGION.get(city_name),
            "city",
            (city_name,),
            0.85,
        )

    normalized = normalize_suffix(location or city or raw)
    normalized = re.sub(r"\s+", "", normalized)
    return PlaceProfile(raw, "unknown", normalized or None, None, None, "unknown", (normalized,) if normalized else (), 0.25)
