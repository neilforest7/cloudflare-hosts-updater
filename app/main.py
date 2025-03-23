#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CloudflareIP-Hosts更新器主程序
定时运行CloudflareSpeedTest获取最优IP，并更新容器hosts文件
"""

import os
import json
import time
import logging
import subprocess
import schedule
import toml
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/app/data/updater.log')
    ]
)
logger = logging.getLogger('cloudflare-hosts-updater')

# 配置文件路径
CONFIG_TOML = '/app/data/config.toml'
ENV_FILE = './.env'

# 默认配置
DEFAULT_CONFIG = {
    'UPDATE_INTERVAL': '12h',
    'TARGET_CONTAINERS': '',
    'CF_DOMAINS': '',
    'IP_COUNT': 3,
    'PREFERRED_IP': '',
    'SPEED_TEST_ARGS': '',
}

# 硬编码的标记，不允许用户修改
HOSTS_MARKER = '# CloudflareIP-HostsUpdater'

# 全局配置变量
CONFIG = {}

# 加载配置（优先从config.toml读取，然后从环境变量读取，最后使用默认值）
def load_config():
    global CONFIG
    
    # 1. 首先加载默认配置
    config = DEFAULT_CONFIG.copy()
    
    # 2. 尝试从环境变量加载配置
    config['UPDATE_INTERVAL'] = os.environ.get('UPDATE_INTERVAL', config['UPDATE_INTERVAL'])
    config['TARGET_CONTAINERS'] = os.environ.get('TARGET_CONTAINERS', config['TARGET_CONTAINERS'])
    config['CF_DOMAINS'] = os.environ.get('CF_DOMAINS', config['CF_DOMAINS'])
    config['IP_COUNT'] = int(os.environ.get('IP_COUNT', config['IP_COUNT']))
    config['PREFERRED_IP'] = os.environ.get('PREFERRED_IP', config['PREFERRED_IP'])
    config['SPEED_TEST_ARGS'] = os.environ.get('SPEED_TEST_ARGS', config['SPEED_TEST_ARGS'])
    
    # 3. 如果存在config.toml，则从其中加载配置（优先级最高）
    if os.path.exists(CONFIG_TOML) and os.path.getsize(CONFIG_TOML) > 0:
        try:
            toml_config = toml.load(CONFIG_TOML)
            if 'general' in toml_config:
                for key, value in toml_config['general'].items():
                    if key.upper() in config:
                        config[key.upper()] = value
            logger.info(f"从 {CONFIG_TOML} 加载了配置")
        except Exception as e:
            logger.error(f"加载 {CONFIG_TOML} 失败: {str(e)}")
    
    # 处理字符串类型的容器和域名列表
    if isinstance(config['TARGET_CONTAINERS'], str):
        config['TARGET_CONTAINERS'] = [c.strip() for c in config['TARGET_CONTAINERS'].split(',') if c.strip()]
    
    if isinstance(config['CF_DOMAINS'], str):
        config['CF_DOMAINS'] = [d.strip() for d in config['CF_DOMAINS'].split(',') if d.strip()]
    
    # 更新全局配置
    CONFIG = config
    
    logger.info("配置加载完成")
    return config

# 保存配置到config.toml
def save_config(config):
    try:
        # 确保数据目录存在
        os.makedirs(os.path.dirname(CONFIG_TOML), exist_ok=True)
        
        # 将列表转换为逗号分隔的字符串
        if isinstance(config['TARGET_CONTAINERS'], list):
            config['TARGET_CONTAINERS'] = ','.join(config['TARGET_CONTAINERS'])
        
        if isinstance(config['CF_DOMAINS'], list):
            config['CF_DOMAINS'] = ','.join(config['CF_DOMAINS'])
        
        # 准备TOML格式数据
        toml_data = {
            'general': {
                'update_interval': config['UPDATE_INTERVAL'],
                'target_containers': config['TARGET_CONTAINERS'],
                'cf_domains': config['CF_DOMAINS'],
                'ip_count': int(config['IP_COUNT']),
                'preferred_ip': config['PREFERRED_IP'],
                'speed_test_args': config['SPEED_TEST_ARGS'],
            }
        }
        
        # 写入TOML文件
        with open(CONFIG_TOML, 'w') as f:
            toml.dump(toml_data, f)
        
        logger.info(f"配置已保存到 {CONFIG_TOML}")
        
        # 重新加载配置
        load_config()
        
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")
        return False

# 初始加载配置
CONFIG = load_config()

# 从全局配置中获取变量
UPDATE_INTERVAL = CONFIG['UPDATE_INTERVAL']
TARGET_CONTAINERS = CONFIG['TARGET_CONTAINERS']
CF_DOMAINS = CONFIG['CF_DOMAINS']
IP_COUNT = CONFIG['IP_COUNT']
PREFERRED_IP = CONFIG['PREFERRED_IP']
SPEED_TEST_ARGS = CONFIG['SPEED_TEST_ARGS']

# 文件路径
SPEEDTEST_RESULT = '/app/data/result.csv'
HOSTS_TEMPLATE = '/app/data/template.hosts'
HOSTS_FILE = '/app/data/hosts'

def parse_time_interval(interval_str):
    """解析时间间隔字符串为秒数"""
    unit_map = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400
    }
    
    if not interval_str or interval_str.isdigit():
        # 如果只有数字，默认为小时
        return int(interval_str or '12') * 3600
    
    unit = interval_str[-1].lower()
    if unit in unit_map and interval_str[:-1].isdigit():
        return int(interval_str[:-1]) * unit_map[unit]
    else:
        logger.warning(f"无效的时间间隔格式: {interval_str}，使用默认值12小时")
        return 12 * 3600

def run_cloudflare_speedtest():
    """运行CloudflareSpeedTest获取最优IP"""
    # 如果设置了首选IP，则跳过测速
    if PREFERRED_IP:
        logger.info(f"检测到预设首选IP: {PREFERRED_IP}，跳过测速")
        return True
        
    logger.info("开始运行CloudflareSpeedTest...")
    
    try:
        cmd = ['/app/CloudflareST', '-o', SPEEDTEST_RESULT]
        if SPEED_TEST_ARGS:
            cmd.extend(SPEED_TEST_ARGS.split())
        
        process = subprocess.run(cmd, capture_output=True, text=True)
        if process.returncode != 0:
            logger.error(f"CloudflareSpeedTest运行失败: {process.stderr}")
            return False
        
        logger.info("CloudflareSpeedTest运行完成")
        return True
    except Exception as e:
        logger.error(f"运行CloudflareSpeedTest时出错: {str(e)}")
        return False

def get_preferred_ip_results():
    """获取预设首选IP的结果"""
    if not PREFERRED_IP:
        return []
        
    logger.info(f"使用预设首选IP: {PREFERRED_IP}")
    return [{'ip': PREFERRED_IP, 'speed': '0'}]  # 速度值设为0，表示预设值

def parse_speedtest_results():
    """解析CloudflareSpeedTest结果"""
    # 如果设置了首选IP，则直接返回首选IP
    if PREFERRED_IP:
        return get_preferred_ip_results()
        
    if not os.path.exists(SPEEDTEST_RESULT):
        logger.error(f"结果文件不存在: {SPEEDTEST_RESULT}")
        return []
    
    try:
        # 读取CSV结果文件
        with open(SPEEDTEST_RESULT, 'r') as f:
            lines = f.readlines()
        
        if len(lines) <= 1:  # 只有标题行或者空文件
            logger.warning("测速结果为空")
            return []
        
        # 解析CSV（简单实现，可以使用csv模块增强）
        header = lines[0].strip().split(',')
        ip_index = header.index('IP 地址')
        speed_index = header.index('平均延迟')
        
        results = []
        for i in range(1, min(len(lines), IP_COUNT + 1)):
            fields = lines[i].strip().split(',')
            if len(fields) > max(ip_index, speed_index):
                results.append({
                    'ip': fields[ip_index],
                    'speed': fields[speed_index],
                })
        
        return results
    except Exception as e:
        logger.error(f"解析结果时出错: {str(e)}")
        return []

def generate_hosts_content(ip_list, domains=None):
    """生成hosts文件内容
    
    Args:
        ip_list: IP地址列表
        domains: 可选的域名列表，如果提供则优先使用，否则使用全局CF_DOMAINS
    """
    if not ip_list:
        logger.error("无可用IP")
        return ""
    
    hosts_content = f"{HOSTS_MARKER} - 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    # 检查是否有自定义模板
    template_line = "{ip} {domain} # 速度:{speed}ms"
    if os.path.exists(HOSTS_TEMPLATE):
        with open(HOSTS_TEMPLATE, 'r') as f:
            template_content = f.read().strip()
            if template_content:
                template_line = template_content
    
    # 确定使用哪个域名列表
    domain_list = domains if domains is not None else CF_DOMAINS
    
    # 处理可能存在换行符的域名列表
    processed_domains = []
    for domain_entry in domain_list:
        if not domain_entry:
            continue
            
        # 处理域名字符串中的各种换行符（\r\n 和 \n）
        # 注意：config.toml中存储的域名可能包含\r\n或\n分隔符
        if '\r\n' in domain_entry or '\n' in domain_entry or ',' in domain_entry:
            # 首先按\r\n分割
            lines = domain_entry.replace('\r\n', '\n').split('\n')
            for line in lines:
                # 然后处理可能的逗号分隔
                domains = [d.strip() for d in line.split(',') if d.strip()]
                processed_domains.extend(domains)
        else:
            processed_domains.append(domain_entry.strip())
    
    logger.info(f"处理后的域名列表: {processed_domains}")
    
    # 为每个域名生成hosts条目
    for domain in processed_domains:
        if not domain:
            continue
        
        for ip_info in ip_list:
            line = template_line.format(
                ip=ip_info['ip'],
                domain=domain,
                speed=ip_info['speed']
            )
            hosts_content += line + "\n"
    
    hosts_content += f"{HOSTS_MARKER} - 结束\n"
    return hosts_content

def save_hosts_file(content):
    """保存hosts文件"""
    try:
        with open(HOSTS_FILE, 'w') as f:
            f.write(content)
        logger.info(f"hosts文件已保存至 {HOSTS_FILE}")
        return True
    except Exception as e:
        logger.error(f"保存hosts文件失败: {str(e)}")
        return False

def update_container_hosts(container_name, hosts_content):
    """更新容器的hosts文件"""
    logger.info(f"正在更新容器 {container_name} 的hosts文件")
    
    try:
        # 检查容器是否存在
        check_cmd = ["docker", "inspect", container_name]
        check_process = subprocess.run(check_cmd, capture_output=True)
        if check_process.returncode != 0:
            logger.error(f"容器 {container_name} 不存在")
            return False
        
        # 备份原hosts文件
        backup_cmd = f"docker exec {container_name} sh -c 'cp /etc/hosts /etc/hosts.bak'"
        subprocess.run(backup_cmd, shell=True, check=True)
        
        # 使用更可靠的方法更新hosts文件
        # 完全重写hosts文件，保持我们的Cloudflare IP在顶部，系统原始条目在底部
        
        # 使用硬编码标记，确保一致性
        escaped_marker = HOSTS_MARKER.replace('/', '\\/').replace('&', '\\&').replace('.', '\\.').replace('*', '\\*')
        
        update_cmd = f"""
        docker exec {container_name} sh -c "
        # 完全重写hosts文件的更可靠方法
        
        # 1. 备份原hosts文件（再次确保备份）
        cp /etc/hosts /etc/hosts.bak.$(date +%s)
        
        # 2. 提取系统默认hosts（过滤掉所有我们添加的标记行及其间的内容）
        # 使用awk进行精确过滤：不输出带有我们标记的行以及标记之间的所有行
        awk '
          BEGIN {{ in_section = 0; }}
          /^[ \\t]*{escaped_marker}/ {{ in_section = 1; next; }}
          /^[ \\t]*{escaped_marker} - 结束/ {{ in_section = 0; next; }}
          !in_section {{ print; }}
        ' /etc/hosts > /tmp/system_hosts.tmp
        
        # 3. 从系统hosts中进一步过滤：只过滤空行，保留系统注释
        grep -v '^$' /tmp/system_hosts.tmp > /tmp/system_hosts
        
        # 4. 如果系统hosts为空，则使用基本localhost配置
        if [ ! -s /tmp/system_hosts ]; then
            echo '127.0.0.1\tlocalhost' > /tmp/system_hosts
            echo '::1\tlocalhost ip6-localhost ip6-loopback' >> /tmp/system_hosts
            echo 'fe00::0\tip6-localnet' >> /tmp/system_hosts
            echo 'ff00::0\tip6-mcastprefix' >> /tmp/system_hosts
            echo 'ff02::1\tip6-allnodes' >> /tmp/system_hosts
            echo 'ff02::2\tip6-allrouters' >> /tmp/system_hosts
        fi
        
        # 5. 创建新的hosts文件：我们的内容 + 系统默认内容
        echo '{hosts_content}' > /tmp/hosts.new
        echo '' >> /tmp/hosts.new  # 添加空行分隔
        cat /tmp/system_hosts >> /tmp/hosts.new
        cat /tmp/hosts.new > /etc/hosts
        
        # 6. 清理临时文件
        rm -f /tmp/hosts.new /tmp/system_hosts /tmp/system_hosts.tmp
        
        # 7. 显示更新后的hosts文件内容（用于调试）
        echo '=== 更新后的hosts文件内容 ==='
        cat /etc/hosts
        echo '=== hosts文件内容结束 ==='
        "
        """
        process = subprocess.run(update_cmd, shell=True, capture_output=True, text=True)
        
        if process.returncode != 0:
            logger.error(f"更新容器 {container_name} 的hosts文件失败: {process.stderr}")
            return False
        
        logger.info(f"容器 {container_name} 的hosts文件已更新")
        return True
    except Exception as e:
        logger.error(f"更新容器 {container_name} 的hosts文件时出错: {str(e)}")
        return False

def update_all_hosts():
    """更新所有目标容器的hosts文件"""
    # 重新加载配置以确保使用最新配置
    global TARGET_CONTAINERS, CF_DOMAINS, IP_COUNT, PREFERRED_IP, SPEED_TEST_ARGS
    config = load_config()
    TARGET_CONTAINERS = config['TARGET_CONTAINERS']
    CF_DOMAINS = config['CF_DOMAINS']
    IP_COUNT = config['IP_COUNT']
    PREFERRED_IP = config['PREFERRED_IP']
    SPEED_TEST_ARGS = config['SPEED_TEST_ARGS']
    
    successful = run_cloudflare_speedtest()
    if not successful:
        logger.error("测速失败，跳过更新hosts")
        return
    
    ip_list = parse_speedtest_results()
    if not ip_list:
        logger.error("没有获取到有效IP，跳过更新hosts")
        return
    
    # 显式传递最新的CF_DOMAINS到generate_hosts_content函数
    hosts_content = generate_hosts_content(ip_list, domains=CF_DOMAINS)
    if not hosts_content:
        logger.error("生成hosts内容失败，跳过更新")
        return
    
    save_hosts_file(hosts_content)
    
    for container in TARGET_CONTAINERS:
        if container:
            update_container_hosts(container, hosts_content)

def main():
    """主函数"""
    logger.info("CloudflareIP-Hosts更新器启动")
    
    # 初次运行
    logger.info("初次运行更新")
    update_all_hosts()
    
    # 解析更新间隔并设置定时任务
    interval_seconds = parse_time_interval(UPDATE_INTERVAL)
    logger.info(f"设置定时任务，间隔: {interval_seconds}秒")
    
    # 使用schedule库设置定时任务
    schedule.every(interval_seconds).seconds.do(update_all_hosts)
    
    # 主循环
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常: {str(e)}")
    finally:
        logger.info("CloudflareIP-Hosts更新器已停止")

if __name__ == "__main__":
    # 启动Web服务（在新线程中运行）
    import threading
    from web import start_web_server
    
    # 创建并启动Web服务器线程
    web_thread = threading.Thread(target=start_web_server)
    web_thread.daemon = True  # 设置为守护线程，主程序退出时自动退出
    web_thread.start()
    logger.info("Web服务已启动")
    
    # 启动主程序
    main() 