# -*- coding: utf-8 -*-
"""
hallucination_guard.py - 幻觉检测与阻断模块
============================================

核心设计：宁可保守不答，绝不编造。

流水线：
  1. 用 NER 提取回复中的实体（人名、地点、事件、专有名词）
  2. 与 RAG 检索到的真实记录 + 聊天全文索引做交叉验证
  3. 未验证通过的实体 → 触发阻断
  4. 阻断时：替换为保守回复（带用户提示）

关键策略：
  - 只拦截「具体事实」：人名、地名、时间、专有名词、特定事件
  - 不拦截「风格化表达」：语气词、情感描述、口语化用词
  - 置信度分级：高（实体在记录中）/ 中（近似匹配）/ 低（无记录）→ 低就阻断

用法：
  from hallucination_guard import verify_reply, guard_reply
  result = guard_reply(reply_text, rag_chunks, full_chat_text)
  # result: {"status": "ok"|"blocked", "reply": str, "reason": str, "entities": [...]}
"""
import json
import re
from pathlib import Path
from typing import Optional


# ---------- 配置 ----------
# 项目根目录（hallucination_guard.py 在 core/ 下）
ROOT = Path(__file__).resolve().parent.parent
CHAT_TXT = ROOT / "data" / "chat_extracted.txt"

# 实体类型：只拦截这些（越具体越危险）
RISKY_ENTITY_TYPES = {
    "人名", "地名", "组织", "品牌", "事件", "时间", "专有名词",
    "PERSON", "ORG", "GPE", "LOC", "PRODUCT", "EVENT", "WORK_OF_ART",
}

# 安全词：这些词就算没在记录中出现，也不算编造（通用概念）
SAFE_WORDS = {
    "你", "我", "他", "她", "它", "我们", "你们", "他们",
    "今天", "明天", "昨天", "现在", "以前", "后来", "之前", "之后",
    "这里", "那里", "家里", "学校", "公司", "医院", "超市", "公园",
    "北京", "上海", "广州", "深圳", "中国", "世界", "网上", "外面",
    "爸爸", "妈妈", "爷爷", "奶奶", "哥哥", "姐姐", "弟弟", "妹妹",
    "朋友", "同事", "同学", "老师", "医生", "律师", "警察",
    "好吃", "好玩", "好看", "开心", "难过", "生气", "害怕", "紧张",
    "高兴", "快乐", "难过", "伤心", "悲伤", "痛苦", "幸福",
    "温暖", "感动", "温柔", "亲切", "美好", "终于", "希望",
    "吃饭", "睡觉", "上班", "下班", "回家", "出门", "逛街", "散步",
    "手机", "电脑", "电视", "车", "房子", "钱", "工作", "学习",
    "微信", "QQ", "抖音", "淘宝", "京东", "支付宝", "美团",
    "嗯", "啊", "哦", "呢", "吧", "吗", "嘛", "哈", "啦",
    "行了", "得了", "好吧", "算了", "随便", "还行",
    "真的", "确实", "其实", "反正", "可能", "也许", "一定",
    "每次", "有时", "经常", "好久", "一直", "一起",
    "上海", "深圳", "广州", "北京", "成都", "杭州", "武汉", "南京",
    "地铁", "公交", "打车", "开车", "走路", "骑车",
    "小时候", "以前", "后来", "最后", "结果", "后来", "最近",
    "还记得", "忘记了", "想起来", "不知道", "不清楚",
    "聊天", "说话", "听", "说", "看", "想", "知道",
}

# 阻断时的保守回复模板（风格化，不机械）
CONSERVATIVE_REPLIES = [
    "这个我不太记得了。",
    "我好像没印象了。",
    "这事我有点模糊了。",
    "不太记得这个了。",
    "这个我真想不起来了。",
    "嗯……这个我不太确定。",
]

# 日志目录
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_guard_event(status: str, original: str, reason: str, entities: list, unverified: list):
    """记录 Guard 事件到按天日志文件。"""
    from datetime import datetime
    log_file = LOG_DIR / f"guard_{datetime.now().strftime('%Y-%m-%d')}.txt"
    ts = datetime.now().strftime("%H:%M:%S")
    log_text = f"[{ts}] {status.upper()}\n"
    log_text += f"  reason: {reason}\n"
    log_text += f"  original: {original[:200]}\n"
    log_text += f"  entities ({len(entities)}): {', '.join(str(e.get('entity', e.get('text', ''))) for e in entities[:10])}\n"
    if unverified:
        log_text += f"  unverified ({len(unverified)}): {', '.join(str(u.get('entity', u.get('text', ''))) for u in unverified)}\n"
    log_text += "\n"
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_text)
    except Exception:
        pass


# ---------- 简易 NER（无外部依赖，纯规则 + 词典） ----------
# 之所以不用 spaCy/jieba：避免引入额外依赖，frozen 模式下更稳

def _extract_entities(text: str) -> list[dict]:
    """从文本中提取潜在实体（人名、地点、专有名词等）。

    策略：
      1. 中文姓名模式（2-4 字，常见姓氏开头）
      2. 专有名词（大写字母、数字组合、品牌名）
      3. 特定事件（带时间、地点的描述性短语）
      4. 已知的命名实体（从聊天记录中预先提取的词典匹配）
    """
    entities = []
    seen = set()

    # 1) 中文姓名：2-4 字，常见姓氏开头
    # 常见姓氏（覆盖 90%+）
    common_surnames = (
        "李王张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧"
        "程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田"
        "任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万"
        "段雷钱汤尹黎易常武乔贺赖文龚贝翟牛樊葛柳邢路岳齐严聂鲁"
    )
    name_pat = re.compile(rf"[{common_surnames}][\u4e00-\u9fff]{{1,3}}")
    for m in name_pat.finditer(text):
        ent = m.group()
        if ent not in seen and len(ent) >= 2:
            entities.append({"text": ent, "type": "人名", "start": m.start(), "end": m.end()})
            seen.add(ent)

    # 2) 专有名词/品牌：含英文字母 + 可选中文的组合（如 iPhone、QQ音乐、B站）
    # 注意：只匹配"纯数字+中文"的组合（如"30个人"），它们不是实体
    brand_pat = re.compile(r"[A-Za-z]+[\u4e00-\u9fff]{0,4}|[\u4e00-\u9fff]{1,3}[A-Za-z]+")
    for m in brand_pat.finditer(text):
        ent = m.group()
        if ent not in seen and len(ent) >= 2:
            entities.append({"text": ent, "type": "专有名词", "start": m.start(), "end": m.end()})
            seen.add(ent)

    # 2b) 补充：纯大写缩写（如 QQ、AI、B站 等 2-4 字符）
    abbr_pat = re.compile(r"[A-Z]{2,4}|[A-Z][a-z]{1,3}")
    for m in abbr_pat.finditer(text):
        ent = m.group()
        if ent not in seen:
            entities.append({"text": ent, "type": "专有名词", "start": m.start(), "end": m.end()})
            seen.add(ent)

    # 3) 地点词：以"省/市/县/区/街/镇/乡/村"结尾的 2-6 字词
    # 注意：不包含"路""店""园""楼"等，它们在中文对话中大量误报（如"走路""睡觉"）
    loc_pat = re.compile(rf"[\u4e00-\u9fff]{{1,5}}(?:省|市|县|区|街|镇|乡|村|山|河|湖|海)")
    for m in loc_pat.finditer(text):
        ent = m.group()
        if ent not in seen and len(ent) >= 2:
            entities.append({"text": ent, "type": "地名", "start": m.start(), "end": m.end()})
            seen.add(ent)

    # 4) 时间/日期：具体日期格式
    time_pat = re.compile(r"\d{4}年\d{1,2}月(?:\d{1,2}日)?|\d{1,2}月\d{1,2}日|(?:去年|前年|明年)\d{1,2}月")
    for m in time_pat.finditer(text):
        ent = m.group()
        if ent not in seen:
            entities.append({"text": ent, "type": "时间", "start": m.start(), "end": m.end()})
            seen.add(ent)

    # 5) 事件/活动：以"节/会/赛/展/考/游/ trip"结尾
    event_pat = re.compile(rf"[\u4e00-\u9fff]{{2,6}}(?:节|会|赛|展|考|游|比赛|活动|聚会|旅行| Trip)")
    for m in event_pat.finditer(text):
        ent = m.group()
        if ent not in seen and len(ent) >= 3:
            entities.append({"text": ent, "type": "事件", "start": m.start(), "end": m.end()})
            seen.add(ent)

    # 6) 过滤掉明显的对话碎片（非真实实体）
    CONVERSATION_FRAGMENTS = {
        "的了", "的事儿", "的时候", "的地方", "的人", "的结果", "的话",
        "还是", "就是", "都是", "的是", "的是", "这个", "那个", "哪个",
        "什么", "怎么", "为什么", "因为", "所以", "虽然", "但是",
        "一样", "一起", "一边", "一直", "一点儿", "一下儿",
    }
    filtered = []
    for ent in entities:
        if ent["text"] in CONVERSATION_FRAGMENTS:
            continue
        # 过滤纯语气/助词组成的实体
        if len(ent["text"]) <= 3 and all(c in "的了着过吧吗啊呢啦呀哦嗯" for c in ent["text"]):
            continue
        filtered.append(ent)
    entities = filtered

    return entities


# ---------- 聊天记录全文索引（用于实体验证） ----------
_chat_index_cache: Optional[set] = None

def _build_chat_index() -> set[str]:
    """从 chat_extracted.txt 构建全文 token 索引（所有出现过的词）。

    返回一个 set，包含所有聊天中出现过的连续 2-4 字片段。
    用于快速判断一个实体是否在聊天记录中出现过。
    """
    global _chat_index_cache
    if _chat_index_cache is not None:
        return _chat_index_cache

    if not CHAT_TXT.exists():
        _chat_index_cache = set()
        return _chat_index_cache

    index = set()
    text = CHAT_TXT.read_text(encoding="utf-8", errors="ignore")
    # 去掉 role 标记，只保留内容
    clean_lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[对方]") or line.startswith("[本人]"):
            clean_lines.append(line[4:].strip())
        elif line and not line.startswith("#"):
            clean_lines.append(line)

    full_text = " ".join(clean_lines)

    # 提取所有 2-4 字连续片段
    for length in (2, 3, 4):
        for i in range(len(full_text) - length + 1):
            substr = full_text[i:i + length]
            if _is_meaningful_substr(substr):
                index.add(substr)

    # 也加入整句（用于精确匹配）
    for line in clean_lines:
        index.add(line)

    _chat_index_cache = index
    print(f"[hallucination_guard] chat index built: {len(index)} tokens", flush=True)
    return _chat_index_cache


def _is_meaningful_substr(s: str) -> bool:
    """判断一个子串是否值得放入索引（过滤纯标点、纯空格）。"""
    if not s:
        return False
    if re.match(r"^[\s\W\d]+$", s):
        return False
    if len(s) >= 2 and not re.search(r"[\u4e00-\u9fff]", s):
        # 纯英文/数字 2 字以上也算
        return True
    return bool(re.search(r"[\u4e00-\u9fff]", s))


def reset_chat_index():
    """chat_extracted.txt 更新后调用，清缓存让下次重新建。"""
    global _chat_index_cache
    _chat_index_cache = None


# ---------- 实体验证 ----------
def _verify_entity(entity: dict, chat_index: set[str], rag_chunks: list[dict]) -> dict:
    """验证单个实体是否可信。

    返回：{"entity": str, "type": str, "verified": bool, "match": str, "method": str}
    """
    text = entity["text"]
    ent_type = entity["type"]

    # 1) 安全词直接放行
    if text in SAFE_WORDS:
        return {"entity": text, "type": ent_type, "verified": True, "match": text, "method": "safe_word"}

    # 2) 在 RAG chunks 中精确出现 → 高可信
    for chunk in rag_chunks:
        chunk_text = chunk.get("text", "")
        if text in chunk_text:
            return {"entity": text, "type": ent_type, "verified": True, "match": chunk_text, "method": "rag_exact"}

    # 3) 在聊天记录全文索引中精确出现 → 可信
    if text in chat_index:
        return {"entity": text, "type": ent_type, "verified": True, "match": text, "method": "chat_exact"}

    # 4) 子串匹配（实体较长，取前 2-3 字匹配）
    for sub_len in (min(4, len(text)), min(3, len(text)), min(2, len(text))):
        if sub_len < 2:
            continue
        sub = text[:sub_len]
        if sub in chat_index:
            return {"entity": text, "type": ent_type, "verified": True, "match": sub, "method": "chat_substring"}

    # 5) 都没有 → 未验证（风险）
    return {"entity": text, "type": ent_type, "verified": False, "match": None, "method": "none"}


def verify_reply(reply: str, rag_chunks: list[dict], chat_index: Optional[set[str]] = None) -> dict:
    """验证一条回复的可信度。

    返回：
    {
        "status": "ok" | "warning" | "blocked",
        "reply": str,              # 如果是 blocked，这里已经是保守回复
        "original_reply": str,     # 原始回复（blocked 时保留）
        "entities": [...],         # 所有检测到的实体及其验证结果
        "unverified": [...],       # 未验证的实体（风险点）
        "reason": str,             # 状态说明
    }
    """
    if not chat_index:
        chat_index = _build_chat_index()

    # 提取实体
    entities = _extract_entities(reply)

    # 逐个验证
    verified_results = []
    unverified = []
    for ent in entities:
        result = _verify_entity(ent, chat_index, rag_chunks)
        verified_results.append(result)
        if not result["verified"]:
            unverified.append(result)

    # 判断状态
    if not unverified:
        status = "ok"
        reason = f"所有 {len(entities)} 个实体均已验证通过"
    elif len(unverified) <= 1 and len(entities) >= 3:
        status = "warning"
        reason = f"{len(unverified)} 个实体未在记录中验证（共 {len(entities)} 个）"
    elif all(u.get("type") == "专有名词" for u in unverified):
        # 所有未验证的都是"专有名词"类型（NER 置信度低）→ 降级为 warning
        status = "warning"
        reason = f"{len(unverified)} 个专有名词未验证（共 {len(entities)} 个实体），置信度较低，不阻断"
    else:
        status = "blocked"
        reason = f"检测到 {len(unverified)} 个未验证实体，可能存在编造：{', '.join(u['entity'] for u in unverified)}"

    # 构造返回
    import random
    if status == "blocked":
        conservative = random.choice(CONSERVATIVE_REPLIES)
        _log_guard_event("blocked", reply, reason, verified_results, unverified)
        return {
            "status": "blocked",
            "reply": conservative,
            "original_reply": reply,
            "entities": verified_results,
            "unverified": unverified,
            "reason": reason,
        }
    else:
        if unverified:
            _log_guard_event(status, reply, reason, verified_results, unverified)
        return {
            "status": status,
            "reply": reply,
            "original_reply": reply,
            "entities": verified_results,
            "unverified": unverified,
            "reason": reason,
        }


def guard_reply(reply: str, rag_chunks: list[dict], chat_index: Optional[set[str]] = None) -> dict:
    """便捷函数：一键验证 + 阻断。返回结果直接可用。"""
    return verify_reply(reply, rag_chunks, chat_index)
