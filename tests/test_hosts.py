import pytest

from app.hosts import END, MARKER, merge_hosts, render_hosts


def block(ip="1.1.1.1"):
    return render_hosts([{"ip": ip, "speed": "10"}], ("example.com",), "", "2026-10-20")


def test_replace_legacy_block_preserves_every_other_line():
    before = "127.0.0.1\tlocalhost\n# user note\n"
    after = "172.18.0.2 my-container\n::1 localhost\n10.0.0.5 custom-alias"
    original = before + block("8.8.8.8") + after
    merged = merge_hosts(original, block())
    assert merged == block() + before + after
    assert merge_hosts(merged, block()) == merged
    assert "8.8.8.8" not in merged


@pytest.mark.parametrize(
    "original",
    [f"{MARKER} - 开始\nvalue\n", END + "\n", f"{MARKER} - 开始\n{MARKER} - 开始\n{END}\n"],
)
def test_malformed_block_is_rejected(original):
    with pytest.raises(ValueError):
        merge_hosts(original, block())


def test_multiple_legacy_blocks_and_similar_comments():
    original = (
        block() + "# CloudflareIP-HostsUpdater user note\n" + block() + "127.0.0.1 localhost\n"
    )
    result = merge_hosts(original, block())
    assert result.count(END) == 1
    assert "# CloudflareIP-HostsUpdater user note\n127.0.0.1 localhost\n" in result


def test_multi_ip_template_and_ipv6():
    content = render_hosts(
        [{"ip": "1.1.1.1", "speed": "2"}, {"ip": "2606:4700::1111", "speed": "3"}],
        ("one.test", "two.test"),
        "{ip} {domain} # 速度:{speed}ms",
        "now",
    )
    assert content.count("one.test") == 2
    assert content.count("two.test") == 2
    assert "2606:4700::1111 two.test" in content


@pytest.mark.parametrize(
    "template",
    [
        "{ip} {domain}\n127.0.0.1 other",
        "{ip.__class__} {domain}",
        "{ip} {domain!r}",
        "{ip} {domain} evil.test",
        "{ip} {unknown}",
    ],
)
def test_invalid_template_cannot_inject_hosts(template):
    with pytest.raises(ValueError):
        render_hosts([{"ip": "1.1.1.1", "speed": "10"}], ("example.com",), template, "now")
