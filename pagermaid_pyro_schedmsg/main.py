import json
import os
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from pyrogram import Client

from pagermaid.dependence import scheduler
from pagermaid.enums import Message
from pagermaid.listener import listener
from pagermaid.services import bot
from pagermaid.utils import logs

PLUGIN_NAME = "schedmsg_plus"
PLUGIN_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(PLUGIN_DIR, "config.json")
LOCK_FILE = os.path.join(PLUGIN_DIR, ".schedmsg_plus.lock")

DEFAULT_CONFIG = {
    "utc_offset": 8,
    "jobs": []
}


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
    cfg["jobs"] = cfg.get("jobs", []) or []
    return cfg


def save_config(cfg):
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def now_with_offset(offset):
    return datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=offset))
    )


def find_job(cfg, name):
    for job in cfg.get("jobs", []):
        if job.get("name") == name:
            return job
    return None


@contextmanager
def process_lock():
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    fd = None
    try:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
        except FileExistsError:
            return
        yield True
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                os.remove(LOCK_FILE)
            except FileNotFoundError:
                pass


def parse_parts(raw):
    return [x.strip() for x in raw.split("|")]


def render_job(job):
    if job.get("type") == "daily":
        return "[{name}] daily {time} -> {target} :: {text} | enabled={enabled}".format(
            name=job.get("name"),
            time=job.get("time"),
            target=job.get("target"),
            text=job.get("message"),
            enabled=job.get("enabled"),
        )
    return "[{name}] once {run_at} -> {target} :: {text} | enabled={enabled}".format(
        name=job.get("name"),
        run_at=job.get("run_at"),
        target=job.get("target"),
        text=job.get("message"),
        enabled=job.get("enabled"),
    )


async def send_job(job):
    await bot.send_message(job.get("target"), job.get("message"))


async def run_due_jobs():
    with process_lock() as locked:
        if not locked:
            return

        cfg = load_config()
        offset = int(cfg.get("utc_offset", 8))
        now = now_with_offset(offset)

        for job in cfg.get("jobs", []):
            if not job.get("enabled", True):
                continue

            if job.get("type") == "daily":
                hhmm = now.strftime("%H:%M")
                run_key = now.strftime("%Y-%m-%d")
                if hhmm == job.get("time") and job.get("last_run") != run_key:
                    job["last_run"] = run_key
                    save_config(cfg)
                    await send_job(job)

            elif job.get("type") == "once":
                if job.get("done"):
                    continue
                try:
                    run_at = datetime.strptime(job.get("run_at"), "%Y-%m-%d %H:%M")
                    run_at = run_at.replace(tzinfo=timezone(timedelta(hours=offset)))
                except Exception:
                    continue
                if now >= run_at:
                    job["done"] = True
                    job["enabled"] = False
                    job["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    save_config(cfg)
                    await send_job(job)


def help_text():
    return (
        "`定时发消息插件（PagerMaid-Pyro）`\n\n"
        "`命令：`\n"
        "`schedmsg adddaily <名称>|<目标>|<HH:MM>|<消息>`\n"
        "`schedmsg addonce <名称>|<目标>|<YYYY-MM-DD HH:MM>|<消息>`\n"
        "`schedmsg list` 查看任务\n"
        "`schedmsg del <名称>` 删除任务\n"
        "`schedmsg on <名称>` 启用任务\n"
        "`schedmsg off <名称>` 禁用任务\n"
        "`schedmsg run <名称>` 立即发送一次\n"
        "`schedmsg tz <UTC偏移>` 设置时区，比如 8、9、-5\n\n"
        "`目标可以是：`\n"
        "`用户名（如 @someone）`\n"
        "`数字 chat_id`\n"
        "`群组用户名`\n\n"
        "`示例：`\n"
        "`schedmsg adddaily morning|@testgroup|09:00|早上好`\n"
        "`schedmsg addonce note1|123456789|2026-04-21 08:30|记得开会`"
    )


@listener(command="schedmsg", description="定时向个人或群发送消息", parameters="[subcommand]")
async def schedmsg_handler(_: Client, message: Message):
    args = (message.arguments or "").strip()
    if not args:
        return await message.edit(help_text())

    parts = args.split(" ", 1)
    action = parts[0].lower()
    value = parts[1].strip() if len(parts) > 1 else ""
    cfg = load_config()

    if action == "list":
        jobs = cfg.get("jobs", [])
        if not jobs:
            return await message.edit("`当前没有定时任务。`")
        text = "`当前任务：`\n" + "\n".join(render_job(j) for j in jobs)
        return await message.edit(text)

    if action == "tz":
        if not value:
            return await message.edit("`请提供 UTC 偏移，例如：schedmsg tz 8`")
        try:
            offset = int(value)
        except ValueError:
            return await message.edit("`UTC 偏移必须是整数。`")
        if offset < -12 or offset > 14:
            return await message.edit("`UTC 偏移范围应在 -12 到 14 之间。`")
        cfg["utc_offset"] = offset
        save_config(cfg)
        return await message.edit("`已设置 UTC 偏移为 %s。`" % offset)

    if action == "adddaily":
        fields = parse_parts(value)
        if len(fields) != 4:
            return await message.edit("`格式错误。用法：schedmsg adddaily <名称>|<目标>|<HH:MM>|<消息>`")
        name, target, hhmm, text = fields
        if find_job(cfg, name):
            return await message.edit("`已存在同名任务，请换一个名称。`")
        try:
            datetime.strptime(hhmm, "%H:%M")
        except ValueError:
            return await message.edit("`时间格式错误，应为 HH:MM，例如 09:30`")
        cfg["jobs"].append({
            "name": name,
            "type": "daily",
            "target": target,
            "time": hhmm,
            "message": text,
            "enabled": True,
            "last_run": ""
        })
        save_config(cfg)
        return await message.edit("`已添加每日任务：%s`" % name)

    if action == "addonce":
        fields = parse_parts(value)
        if len(fields) != 4:
            return await message.edit("`格式错误。用法：schedmsg addonce <名称>|<目标>|<YYYY-MM-DD HH:MM>|<消息>`")
        name, target, run_at, text = fields
        if find_job(cfg, name):
            return await message.edit("`已存在同名任务，请换一个名称。`")
        try:
            datetime.strptime(run_at, "%Y-%m-%d %H:%M")
        except ValueError:
            return await message.edit("`时间格式错误，应为 YYYY-MM-DD HH:MM`")
        cfg["jobs"].append({
            "name": name,
            "type": "once",
            "target": target,
            "run_at": run_at,
            "message": text,
            "enabled": True,
            "done": False,
            "last_run": ""
        })
        save_config(cfg)
        return await message.edit("`已添加一次性任务：%s`" % name)

    if action == "del":
        if not value:
            return await message.edit("`请提供任务名称。`")
        before = len(cfg.get("jobs", []))
        cfg["jobs"] = [j for j in cfg.get("jobs", []) if j.get("name") != value]
        if len(cfg["jobs"]) == before:
            return await message.edit("`未找到该任务。`")
        save_config(cfg)
        return await message.edit("`已删除任务：%s`" % value)

    if action in ("on", "off", "run"):
        if not value:
            return await message.edit("`请提供任务名称。`")
        job = find_job(cfg, value)
        if not job:
            return await message.edit("`未找到该任务。`")
        if action == "on":
            job["enabled"] = True
            save_config(cfg)
            return await message.edit("`已启用任务：%s`" % value)
        if action == "off":
            job["enabled"] = False
            save_config(cfg)
            return await message.edit("`已禁用任务：%s`" % value)
        if action == "run":
            await send_job(job)
            return await message.edit("`已立即发送任务消息：%s`" % value)

    return await message.edit(help_text())


@scheduler.scheduled_job("interval", seconds=20, id="schedmsg_plus_tick")
async def schedmsg_job():
    try:
        await run_due_jobs()
    except Exception as e:
        await logs.info("schedmsg_plus 运行失败：%s" % e)
