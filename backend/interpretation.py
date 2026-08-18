"""Claude-generated Vedic astrology interpretation, split into four sections."""
from __future__ import annotations

import json
import os

import anthropic

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
        "你是一位精通印度吠陀占星学(Jyotish)的资深占星解读师，"
        "会根据用户提供的本命盘(D1)数据和当前维姆什塔利大运/小运(Vimshottari Dasha)数据，"
        "生成中文占星解读。解读必须结合命盘中具体的行星、星座、宫位与星宿信息展开分析，"
        "避免使用套话或含糊其辞的通用描述。语言温和、有洞察力，呈现命盘的倾向与可能性，"
        "而不是绝对化的宿命论断言；不提供具体的医疗、法律或投资建议。"
    )
    if is_minor:
        base += (
            "\n\n重要：本命盘的主人是未成年人，你的解读对象是孩子的家长，而不是孩子本人。"
            "请使用'孩子'来指代命主，第三人称描述，语气客观、关怀、以家长视角提供建设性参考。"
            "内容聚焦：孩子的性格特质与天赋倾向、成长与理财观念的启蒙方向、"
            "孩子的人际相处与情感表达方式(不涉及婚恋、不做感情关系分析)、"
            "以及当前所处成长阶段可能出现的状态与家长可以关注的重点。"
            "'relationship'板块请围绕孩子的人际交往与情绪特点撰写，而非爱情关系。"
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
        "请生成：一句话金句(tagline)，以及四个板块——性格(personality)、财富(wealth)、"
        "感情或人际(relationship)、近况(current_period，需结合当前大运/小运说明近期整体运势"
        "走向与需要关注的重点)。每个板块正文约200-350字。"
    )


def generate_interpretation(
    chart_summary: str,
    dasha_summary: str,
    is_minor: bool,
    name: str | None = None,
) -> dict:
    client = _get_client()
    response = client.messages.create(
        # max_tokens covers thinking + the JSON response together (thinking is
        # on by default for claude-opus-5), so this needs real headroom —
        # too tight a budget silently truncates the JSON mid-field.
        model=MODEL,
        max_tokens=8192,
        system=_build_system_prompt(is_minor),
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        messages=[
            {"role": "user", "content": _build_user_prompt(chart_summary, dasha_summary, name)}
        ],
    )
    if response.stop_reason == "max_tokens":
        raise RuntimeError("生成的内容被截断（超出 max_tokens），请重试")
    text = next(b.text for b in response.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回的内容不是合法 JSON: {exc}") from exc
