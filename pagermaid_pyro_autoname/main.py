import json
import os
from datetime import datetime, timedelta, timezone

from pyrogram import Client

from pagermaid.dependence import scheduler
from pagermaid.enums import Message
from pagermaid.listener import listener
from pagermaid.services import bot
from pagermaid.utils import logs

PLUGIN_NAME = "autoname_plus"
PLUGIN_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(PLUGIN_DIR, "config.json")

DEFAULT_CONFIG = {
    "enabled": False,
    "utc_offset": 8,
    "template": "{HH}:{mm} {ampm} {tz} {clock}",
    "last_applied": "",
}

CLOCK_EMOJI = [
    "🕛", "🕧", "🕐", "🕜", "🕑", "🕝", "🕒", "🕞",
    "🕓", "🕟", "🕔", "🕠", "🕕", "🕡", "🕖", "🕢",
    "🕗", "🕣", "🕘", "🕤", "🕙", "🕥", "🕚", "🕦",
]
WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def ensure_config():
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG.copy())


def load_config():
    ensure_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(data)
    return cfg


def save_config(cfg):
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def format_offset(offset):
    if offset >= 0:
        return "+%s" % offset
    return str(offset)


def current_clock_emoji(now):
    hour = now.hour % 12
    minute = now.minute
    shift = 1 if minute >= 30 else 0
    return CLOCK_EMOJI[hour * 2 + shift]


def render_name(cfg):
    offset = int(cfg.get("utc_offset", 8))
    now = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=offset))
    )
    ampm = "AM" if now.hour < 12 else "PM"
    values = SafeDict(
        YYYY=now.strftime("%Y"),
        YY=now.strftime("%y"),
        MM=now.strftime("%m"),
        DD=now.strftime("%d"),
        HH=now.strftime("%H"),
        hh=now.strftime("%I"),
        mm=now.strftime("%M"),
        ss=now.strftime("%S"),
        ampm=ampm,
        weekday=WEEKDAY_ZH[now.weekday()],
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M:%S"),
        tz="UTC%s" % format_offset(offset),
        offset=format_offset(offset),
        clock=current_clock_emoji(now),
    )
    template = cfg.get("template", DEFAULT_CONFIG["template"])
    return template.format_map(values)


async def apply_name(force=False):
    cfg = load_config()
    new_name = render_name(cfg)
    if not force and cfg.get("last_applied") == new_name:
        return new_name, False

    me = await bot.get_me()
    if not force and getattr(me, "last_name", None) == new_name:
        cfg["last_applied"] = new_name
        save_config(cfg)
        return new_name, False

    await bot.update_profile(last_name=new_name)
    cfg["last_applied"] = new_name
    save_config(cfg)
    return new_name, True


def help_text():
    return (
        "`自动改名插件（PagerMaid-Pyro）`\n\n"
        "`命令：`\n"
        "`autoname on`  启用自动改名\n"
        "`autoname off` 关闭自动改名\n"
        "`autoname status` 查看状态\n"
        "`autoname preview` 预览当前生成结果\n"
        "`autoname apply` 立即应用一次\n"
        "`autoname offset <UTC偏移>` 设置时区，如 8、9、-5\n"
        "`autoname set <模板>` 设置 last_name 模板\n\n"
        "`可用变量：`\n"
        "`{HH}` 24小时\n"
        "`{hh}` 12小时\n"
        "`{mm}` 分钟\n"
        "`{ss}` 秒\n"
        "`{ampm}` AM/PM\n"
        "`{weekday}` 周几\n"
        "`{date}` 日期\n"
        "`{time}` 时间\n"
        "`{tz}` 时区文本，如 UTC+8\n"
        "`{offset}` 偏移，如 +8\n"
        "`{clock}` 时钟 emoji`"
    )


@listener(command="autoname", description="自动修改 Telegram last_name", parameters="[on|off|status|preview|apply|offset|set]")
async def autoname_handler(_: Client, message: Message):
    args = (message.arguments or "").strip()
    if not args:
        return await message.edit(help_text())

    parts = args.split(" ", 1)
    action = parts[0].lower()
    value = parts[1].strip() if len(parts) > 1 else ""
    cfg = load_config()

    if action == "on":
        cfg["enabled"] = True
        save_config(cfg)
        name, changed = await apply_name(force=True)
        return await message.edit("`已启用自动改名。当前 last_name：%s`" % name)

    if action == "off":
        cfg["enabled"] = False
        save_config(cfg)
        return await message.edit("`已关闭自动改名。`")

    if action == "status":
        preview = render_name(cfg)
        text = (
            "`自动改名状态`\n"
            "`启用：%s`\n"
            "`UTC 偏移：%s`\n"
            "`模板：%s`\n"
            "`预览：%s`"
        ) % (
            "是" if cfg.get("enabled") else "否",
            cfg.get("utc_offset", 8),
            cfg.get("template", DEFAULT_CONFIG["template"]),
            preview,
        )
        return await message.edit(text)

    if action == "preview":
        return await message.edit("`预览：%s`" % render_name(cfg))

    if action == "apply":
        name, changed = await apply_name(force=True)
        return await message.edit("`已应用：%s`" % name)

    if action == "offset":
        if not value:
            return await message.edit("`请提供 UTC 偏移，例如：autoname offset 8`")
        try:
            offset = int(value)
        except ValueError:
            return await message.edit("`UTC 偏移必须是整数，例如 8、9、-5`")
        if offset < -12 or offset > 14:
            return await message.edit("`UTC 偏移范围应在 -12 到 14 之间。`")
        cfg["utc_offset"] = offset
        save_config(cfg)
        return await message.edit("`已设置 UTC 偏移为 %s，预览：%s`" % (offset, render_name(cfg)))

    if action == "set":
        if not value:
            return await message.edit("`请提供模板，例如：autoname set {HH}:{mm} {tz} {clock}`")
        cfg["template"] = value
        save_config(cfg)
        return await message.edit("`模板已更新。预览：%s`" % render_name(cfg))

    return await message.edit(help_text())


@scheduler.scheduled_job("interval", seconds=30, id="autoname_plus_tick")
async def autoname_job():
    try:
        cfg = load_config()
        if not cfg.get("enabled"):
            return
        await apply_name(force=False)
    except Exception as e:
        await logs.info("autoname_plus 运行失败：%s" % e)
