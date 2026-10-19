"""Render and replace only our managed block, preserving every other hosts line."""

from string import Formatter

MARKER = "# CloudflareIP-HostsUpdater"
END = f"{MARKER} - 结束"


def merge_hosts(original: str, managed: str) -> str:
    remaining = []
    inside = False
    for line in original.splitlines(keepends=True):
        stripped = line.strip()
        # Check the end marker first; the legacy implementation matched it as a start.
        if stripped == END:
            if not inside:
                raise ValueError("hosts 管理区块缺少开始标记，未修改原文件")
            inside = False
        elif stripped == f"{MARKER} - 开始" or stripped.startswith(f"{MARKER} - 更新时间:"):
            if inside:
                raise ValueError("hosts 管理区块标记嵌套，未修改原文件")
            inside = True
        elif not inside:
            remaining.append(line)
    if inside:
        raise ValueError("hosts 管理区块缺少结束标记，未修改原文件")
    return managed.rstrip("\n") + "\n" + "".join(remaining)


def render_hosts(
    results: list[dict], domains: tuple[str, ...], template: str, timestamp: str
) -> str:
    template = template.strip() or "{ip} {domain} # 延迟:{speed}ms"
    if "\n" in template or "\r" in template:
        raise ValueError("hosts 模板必须只有一行")
    for _, field, spec, conversion in Formatter().parse(template):
        if field is not None and (field not in {"ip", "domain", "speed"} or spec or conversion):
            raise ValueError("hosts 模板只支持 {ip}、{domain}、{speed}")
    lines = [f"{MARKER} - 更新时间: {timestamp}"]
    for domain in domains:
        for result in results:
            line = template.format(domain=domain, **result)
            if line.split("#", 1)[0].split() != [result["ip"], domain]:
                raise ValueError("hosts 模板应以 {ip} {domain} 开始，注释使用 # 分隔")
            lines.append(line)
    if len(lines) == 1:
        raise ValueError("请先配置域名，并确保存在有效的 IP")
    return "\n".join([*lines, END, ""])
