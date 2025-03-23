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

# 从环境变量读取配置
UPDATE_INTERVAL = os.environ.get('UPDATE_INTERVAL', '12h')
TARGET_CONTAINERS = os.environ.get('TARGET_CONTAINERS', '').split(',')
CF_DOMAINS = os.environ.get('CF_DOMAINS', '').split(',')
IP_COUNT = int(os.environ.get('IP_COUNT', '3'))
SPEED_TEST_ARGS = os.environ.get('SPEED_TEST_ARGS', '')
HOSTS_MARKER = os.environ.get('HOSTS_MARKER', '# CloudflareIP-Hosts更新器')
PREFERRED_IP = os.environ.get('PREFERRED_IP', '')

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
        ip_index = header.index('IP')
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

def generate_hosts_content(ip_list):
    """生成hosts文件内容"""
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
    
    # 为每个域名生成hosts条目
    for domain in CF_DOMAINS:
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
        
        # 检查原hosts文件中是否已有标记行，如果有则删除这些行之间的内容
        update_cmd = f"""
        docker exec {container_name} sh -c "
        grep -v -F '{HOSTS_MARKER}' /etc/hosts > /tmp/hosts.new && 
        echo '{hosts_content}' >> /tmp/hosts.new && 
        cat /tmp/hosts.new > /etc/hosts && 
        rm /tmp/hosts.new
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
    successful = run_cloudflare_speedtest()
    if not successful:
        logger.error("测速失败，跳过更新hosts")
        return
    
    ip_list = parse_speedtest_results()
    if not ip_list:
        logger.error("没有获取到有效IP，跳过更新hosts")
        return
    
    hosts_content = generate_hosts_content(ip_list)
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
    main() 