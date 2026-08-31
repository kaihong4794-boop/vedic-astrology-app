"""Claude-generated Vedic astrology interpretation.

Each of the five topics (personality/career/wealth/relationship/current_period)
is generated as two separate fields — an "insight" (the chart-based analysis,
always free) and "advice" (the concrete actionable suggestions, gated behind
payment). This split exists specifically so the free preview can show the
full analysis for every topic instead of a blind teaser, while the thing
users actually pay for is the "so what do I do about it" payoff.
"""
from __future__ import annotations

import json
import logging
import os
import time

import anthropic

logger = logging.getLogger("vedic_astrology.interpretation")

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")

_client: anthropic.Anthropic | None = None

TOPICS = ["personality", "career", "wealth", "relationship", "current_period"]
TOPIC_LABELS_ZH = {
    "personality": "性格",
    "career": "事业",
    "wealth": "财富",
    "relationship": "感情/人际",
    "current_period": "近况",
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _build_output_schema() -> dict:
    properties = {
        "tagline": {
            "type": "string",
            "description": "一句可独立摘出、适合截图分享的金句（不超过28个汉字），"
            "提炼命盘中最具辨识度的一点特质或当前运势的一个亮点，语气生动、不落俗套",
        },
    }
    required = ["tagline"]
    for topic in TOPICS:
        label = TOPIC_LABELS_ZH[topic]
        properties[f"{topic}_insight"] = {
            "type": "string",
            "description": f"{label}板块——命盘依据与分析，不含具体建议",
        }
        properties[f"{topic}_advice"] = {
            "type": "string",
            "description": f"{label}板块——具体可执行建议（可选附传统调整参考）",
        }
        required += [f"{topic}_insight", f"{topic}_advice"]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


OUTPUT_SCHEMA = _build_output_schema()


def _build_system_prompt(is_minor: bool) -> str:
    base = (
        "你是一位精通印度吠陀占星学(Jyotish)的资深占星解读师，正在为用户提供的这一张具体命盘"
        "（本命盘 D1 数据 + 当前维姆什塔利大运/小运 Vimshottari Dasha 数据）撰写中文解读。"
        "\n\n解读分五个主题：性格、事业、财富、感情/人际、近况。每个主题都要分别输出两段内容："
        "一段是'_insight'（命盘分析），一段是'_advice'（可执行建议）。这两段的分工必须严格区分：\n"
        "'_insight'只负责讲清楚命盘显示了什么、为什么——不能包含任何'你应该做什么'式的建议。\n"
        "'_advice'只负责给出接下来具体要做的事，不需要重复解释命盘依据（前面已经讲过了）。\n\n"
        "写作铁律，必须严格遵守：\n"
        "1. insight 部分要具体化，杜绝巴纳姆效应——必须明确点出至少2个具体的命盘依据"
        "（某行星+星座+宫位，或某行星+星宿），并说清楚这个依据具体是怎么导向你给出的结论的。"
        "绝不能写换成任何人的命盘都成立的空泛描述，比如'你外表冷静内心敏感''你渴望被理解和认可'"
        "'你是个复杂矛盾的人'这类不结合命盘细节、放之四海而皆准的套话——这类话读者只会觉得"
        "'说的好像是我又好像谁都是'，必须避免。insight 部分还必须结合命盘里真实存在的强项、"
        "有利配置或即将到来的机会点，明确写出至少一处'这是你的优势'或'接下来这段时间有什么"
        "值得期待的事'，不能通篇只谈问题和风险。current_period_insight 尤其要写清楚近期命盘里"
        "有支撑的、具体可以期待的机会，不能只谈辛苦。\n"
        "2. 说人话，别故弄玄虚——insight 和 advice 都要用日常、具体、口语化的中文表达，多用"
        "'比如'引出具体的生活场景（工作汇报、和伴侣吵架时、发工资那天、跟朋友借钱等），少用"
        "抽象的宇宙隐喻、哲学化措辞，以及'能量''频率''课题''疗愈''觉醒'这类玄学黑话堆砌。"
        "宁可写得直白甚至略显朴素，也不要写得像格言警句或心灵鸡汤，一个没学过占星的人也要能"
        "一读就懂。每句话尽量只讲一件事，避免用顿号、冒号或破折号把三四个信息硬塞进同一句话"
        "里——读起来应该像有人坐在你对面，一句一句慢慢跟你解释，不是在念一份压缩过的清单或"
        "报告摘要。句子偏短、偏口语，比又长又密的复合长句更好。\n"
        "3. advice 部分必须给1-2条具体、可操作的建议，写清楚'做什么'，而不是'要多沟通''要注意"
        "平衡'这种空话；建议要能落实成具体动作（比如具体的沟通方式、具体的记账/理财动作、具体"
        "可以调整的习惯或可以留意的信号），并且要和对应 insight 里引用的命盘依据挂钩，让人一看"
        "就懂'为什么建议是这个'。在财富、事业、近况这三个主题里，如果对应的命盘中能看出明显的"
        "行星弱势或不利配置，可以在可执行建议之外，额外补充一条传统吠陀占星的调整参考（比如"
        "适合的颜色、宝石、适合行动的星期几，或者一个简单的居家/随身调整），但必须清楚标注这是"
        "'传统习俗参考'，语气上是温和的可选建议，绝不能写成'不做就会怎样'这种制造焦虑、逼人"
        "行动的口吻，也不能暗示这能替代医疗、法律或财务专业建议。\n\n"
        "语言温和、有洞察力，呈现命盘的倾向与可能性，而不是绝对化的宿命论断言；"
        "不提供具体的医疗、法律或投资建议。"
    )
    if is_minor:
        base += (
            "\n\n重要：本命盘的主人是未成年人，你的解读对象是孩子的家长，而不是孩子本人。"
            "请使用'孩子'来指代命主，第三人称描述，语气客观、关怀、以家长视角提供建设性参考。"
            "内容聚焦：孩子的性格特质与天赋倾向、成长与理财观念的启蒙方向、"
            "孩子的人际相处与情感表达方式(不涉及婚恋、不做感情关系分析)、"
            "以及当前所处成长阶段可能出现的状态与家长可以关注的重点。"
            "感情/人际相关的两个字段请围绕孩子的人际交往与情绪特点撰写，而非爱情关系。"
            "事业相关的两个字段请围绕孩子的学业方向、学习特长、以及未来可能适合发展的领域来写，"
            "不谈'事业''跳槽''创业'这类成人语境的内容。"
            "给家长的建议同样要具体可执行（比如可以怎么跟孩子聊、可以给孩子安排什么样的小任务或"
            "环境，而不是'多陪伴孩子'这种空话）。"
        )
    else:
        base += "\n\n解读对象是本命盘的主人本人，请使用第二人称'你'来称呼命主。"
    return base


def _build_user_prompt(chart_summary: str, dasha_summary: str, name: str | None) -> str:
    who = f"命主称呼：{name}\n\n" if name else ""
    return (
        f"{who}"
        f"本命盘数据：\n{chart_summary}\n\n"
        f"当前大运/小运数据：\n{dasha_summary}\n\n"
        "请生成：一句话金句(tagline)，以及五个主题各自的 insight 和 advice 两段内容——"
        "性格(personality)、事业(career，需结合第10宫及相关行星配置说明适合的发展方向、天赋"
        "优势，以及近期是否有适合主动争取、调整或留意的信号；命主是未成年人时改为学业方向与"
        "学习特长)、财富(wealth)、感情或人际(relationship)、近况(current_period，insight 部分"
        "需结合当前大运/小运说明近期整体运势走向)。每个主题的 insight 正文约200-300字，包含"
        "至少2个具体命盘依据（点名某行星+星座+宫位，或某行星+星宿）、依据如何导向结论的说明、"
        "以及至少一处基于命盘依据的真实优势或值得期待的机会点——insight 里不要出现具体的"
        "行动建议。每个主题的 advice 正文约80-150字，给出1-2条与对应 insight 依据挂钩的具体"
        "可执行建议。current_period 的 advice 要结合当前大运/小运的星体特质来给，并且要明确"
        "指出近期具体可以主动把握的机会，不只是要规避的风险。全程用日常口语化的中文，不要写成"
        "格言或空泛的哲学感悟。"
    )


# Minimum acceptable length per field (chars). tagline and *_advice are
# intentionally shorter than *_insight, which always runs a couple hundred
# characters by design.
_MIN_FIELD_LENGTH: dict[str, int] = {"tagline": 5}
for _topic in TOPICS:
    _MIN_FIELD_LENGTH[f"{_topic}_insight"] = 120
    _MIN_FIELD_LENGTH[f"{_topic}_advice"] = 30


def _call_claude(
    chart_summary: str,
    dasha_summary: str,
    is_minor: bool,
    name: str | None,
) -> dict:
    client = _get_client()
    try:
        response = client.messages.create(
            # max_tokens covers thinking + the JSON response together (thinking
            # may be on by default depending on the model), so this needs real
            # headroom — too tight a budget silently truncates the JSON
            # mid-field, and the API doesn't always report that as
            # stop_reason=="max_tokens" (see _is_incomplete below).
            model=MODEL,
            max_tokens=16000,
            system=_build_system_prompt(is_minor),
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": _build_user_prompt(chart_summary, dasha_summary, name),
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        cause = exc.__cause__ or exc.__context__
        logger.error(
            "Claude API call failed: %s: %s | cause: %s: %s",
            type(exc).__name__,
            exc,
            type(cause).__name__ if cause else None,
            cause,
        )
        raise
    if response.stop_reason == "max_tokens":
        raise RuntimeError("生成的内容被截断（超出 max_tokens）")
    text = next(b.text for b in response.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回的内容不是合法 JSON: {exc}") from exc


# Transient Claude API failures worth a quick automatic retry: rate limits
# and momentary server-side overload/5xx (529 is Anthropic's "overloaded_error").
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_API_RETRY_BACKOFF_SECONDS = 3


def _call_claude_with_retry(
    chart_summary: str,
    dasha_summary: str,
    is_minor: bool,
    name: str | None,
) -> dict:
    """Wrap _call_claude with one short retry for transient API errors, so a
    momentary "servers are busy" blip doesn't get dumped on the user as raw
    API error JSON — they see a plain-language message only if it's still
    failing after the retry.
    """
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            return _call_claude(chart_summary, dasha_summary, is_minor, name)
        except anthropic.APIConnectionError as exc:
            last_exc = exc
        except anthropic.APIStatusError as exc:
            if exc.status_code not in _RETRYABLE_STATUS_CODES:
                raise RuntimeError("生成解读失败，请稍后重试") from exc
            last_exc = exc
        if attempt == 0:
            logger.warning(
                "Claude API call hit a transient error, retrying in %ds: %s",
                _API_RETRY_BACKOFF_SECONDS,
                last_exc,
            )
            time.sleep(_API_RETRY_BACKOFF_SECONDS)
    raise RuntimeError("AI 服务器当前繁忙，请稍等几秒后重试") from last_exc


def _is_incomplete(reading: dict) -> bool:
    return any(
        len(reading.get(field) or "") < min_len for field, min_len in _MIN_FIELD_LENGTH.items()
    )


def generate_interpretation(
    chart_summary: str,
    dasha_summary: str,
    is_minor: bool,
    name: str | None = None,
) -> dict:
    for attempt in range(2):
        reading = _call_claude_with_retry(chart_summary, dasha_summary, is_minor, name)
        if not _is_incomplete(reading):
            return reading
        logger.warning(
            "interpretation looked truncated on attempt %d (lengths: %s), retrying",
            attempt + 1,
            {k: len(reading.get(k) or "") for k in _MIN_FIELD_LENGTH},
        )
    raise RuntimeError("生成的内容多次不完整，请重试")
