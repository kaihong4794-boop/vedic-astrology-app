"""Claude-generated Vedic astrology interpretation, split into four sections."""
from __future__ import annotations

import json
import logging
import os
import time

import anthropic

logger = logging.getLogger("vedic_astrology.interpretation")

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tagline": {
            "type": "string",
            "description": "一句可独立摘出、适合截图分享的金句（不超过28个汉字），"
            "提炼命盘中最具辨识度的一点特质或当前运势的一个亮点，语气生动、不落俗套",
        },
        "personality": {"type": "string", "description": "性格板块解读"},
        "wealth": {"type": "string", "description": "财富板块解读"},
        "relationship": {"type": "string", "description": "感情/人际板块解读"},
        "current_period": {"type": "string", "description": "近况/当前大运小运板块解读"},
    },
    "required": ["tagline", "personality", "wealth", "relationship", "current_period"],
    "additionalProperties": False,
}


def _build_system_prompt(is_minor: bool) -> str:
    base = (
        "你是一位精通印度吠陀占星学(Jyotish)的资深占星解读师，正在为用户提供的这一张具体命盘"
        "（本命盘 D1 数据 + 当前维姆什塔利大运/小运 Vimshottari Dasha 数据）撰写中文解读。"
        "\n\n写作铁律，三条都必须严格遵守：\n"
        "1. 具体化，杜绝巴纳姆效应——每个板块必须明确点出至少2个具体的命盘依据"
        "（某行星+星座+宫位，或某行星+星宿），并说清楚这个依据具体是怎么导向你给出的结论的。"
        "绝不能写换成任何人的命盘都成立的空泛描述，比如'你外表冷静内心敏感''你渴望被理解和认可'"
        "'你是个复杂矛盾的人'这类不结合命盘细节、放之四海而皆准的套话——这类话读者只会觉得"
        "'说的好像是我又好像谁都是'，必须避免。\n"
        "2. 说人话，别故弄玄虚——用日常、具体、口语化的中文表达，多用'比如'引出具体的生活场景"
        "（工作汇报、和伴侣吵架时、发工资那天、跟朋友借钱等），少用抽象的宇宙隐喻、哲学化措辞，"
        "以及'能量''频率''课题''疗愈''觉醒'这类玄学黑话堆砌。宁可写得直白甚至略显朴素，"
        "也不要写得像格言警句或心灵鸡汤，一个没学过占星的人也要能一读就懂。\n"
        "3. 一定要给可执行建议——每个板块结尾必须给1-2条具体、可操作的建议，写清楚'做什么'，"
        "而不是'要多沟通''要注意平衡'这种空话；建议要能落实成具体动作"
        "（比如具体的沟通方式、具体的记账/理财动作、具体可以调整的习惯或可以留意的信号），"
        "并且要和该板块前面引用的命盘依据挂钩，让人一看就懂'为什么建议是这个'。\n"
        "4. 别写成体检报告或问题诊断书——每个板块不能通篇都是'哪里有问题、要注意什么风险、"
        "要怎么纠正'，必须结合命盘里真实存在的强项、有利配置或即将到来的机会点，"
        "明确写出至少一处'这是你的优势，可以主动去用/去争取'或'接下来这段时间有什么具体"
        "值得期待、可以主动把握的事'，要让读的人读完除了知道要注意什么，也对自己和接下来"
        "有真实依据的盼头，而不是只剩下一堆要改的毛病。current_period 板块尤其要写清楚"
        "近期命盘里有支撑的、具体可以期待或主动争取的机会，不能只谈风险和辛苦。\n\n"
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
            "'relationship'板块请围绕孩子的人际交往与情绪特点撰写，而非爱情关系。"
            "给家长的建议同样要具体可执行（比如可以怎么跟孩子聊、可以给孩子安排什么样的小任务或"
            "环境，而不是'多陪伴孩子'这种空话）。"
        )
    else:
        base += "\n\n解读对象是本命盘的主人本人，请使用第二人称'你'来称呼命主。"
    return base


def _build_user_prompt(
    chart_summary: str, dasha_summary: str, name: str | None, focus: str | None = None
) -> str:
    who = f"命主称呼：{name}\n\n" if name else ""
    focus_block = ""
    if focus:
        focus_block = (
            f"命主自述近期最关心的现状/问题：{focus}\n\n"
            "请特别注意：以上是命主自己填写的真实近况，你必须结合命盘依据，让解读——尤其是"
            "current_period 板块，以及 wealth/relationship/personality 中与此相关的部分——"
            "直接呼应这个具体现状，给出针对这件事本身的、结合命盘的分析和建议，而不是泛泛而谈、"
            "答非所问。不要生硬地复述命主填写的内容，而是要让人感觉'这就是在讲我现在这件事'。\n\n"
        )
    return (
        f"{who}"
        f"本命盘数据：\n{chart_summary}\n\n"
        f"当前大运/小运数据：\n{dasha_summary}\n\n"
        f"{focus_block}"
        "请生成：一句话金句(tagline)，以及四个板块——性格(personality)、财富(wealth)、"
        "感情或人际(relationship)、近况(current_period，需结合当前大运/小运说明近期整体运势"
        "走向与需要关注的重点)。每个板块正文约250-400字，其中包含：至少2个具体命盘依据"
        "（点名某行星+星座+宫位，或某行星+星宿）、依据如何导向结论的说明、至少一处基于命盘"
        "依据的真实优势或值得期待的机会点、以及结尾1-2条与依据挂钩的具体可执行建议——不能"
        "写成清一色的问题诊断和风险提示。current_period 板块的建议要结合当前大运/小运的星体"
        "特质来给，并且要明确指出近期具体可以主动把握的机会，不只是要规避的风险。全程用日常"
        "口语化的中文，不要写成格言或空泛的哲学感悟。"
    )


# Minimum acceptable length per field (chars). tagline is intentionally short
# (<=28 Chinese characters by design) so it needs a much lower bar than the
# four long-form sections, which always run several hundred characters.
_MIN_FIELD_LENGTH = {
    "tagline": 5,
    "personality": 150,
    "wealth": 150,
    "relationship": 150,
    "current_period": 150,
}


def _call_claude(
    chart_summary: str,
    dasha_summary: str,
    is_minor: bool,
    name: str | None,
    focus: str | None = None,
) -> dict:
    client = _get_client()
    try:
        response = client.messages.create(
            # max_tokens covers thinking + the JSON response together (thinking
            # is on by default for claude-opus-5), so this needs real headroom
            # — too tight a budget silently truncates the JSON mid-field, and
            # the API doesn't always report that as stop_reason=="max_tokens"
            # (see _is_incomplete below).
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
                    "content": _build_user_prompt(chart_summary, dasha_summary, name, focus),
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
    focus: str | None = None,
) -> dict:
    """Wrap _call_claude with one short retry for transient API errors, so a
    momentary "servers are busy" blip doesn't get dumped on the user as raw
    API error JSON — they see a plain-language message only if it's still
    failing after the retry.
    """
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            return _call_claude(chart_summary, dasha_summary, is_minor, name, focus)
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
    focus: str | None = None,
) -> dict:
    for attempt in range(2):
        reading = _call_claude_with_retry(chart_summary, dasha_summary, is_minor, name, focus)
        if not _is_incomplete(reading):
            return reading
        logger.warning(
            "interpretation looked truncated on attempt %d (lengths: %s), retrying",
            attempt + 1,
            {k: len(reading.get(k) or "") for k in _MIN_FIELD_LENGTH},
        )
    raise RuntimeError("生成的内容多次不完整，请重试")
