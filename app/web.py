#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CloudflareIP-Hosts更新器Web界面
提供简单的Web界面来查看状态和控制更新器
"""

import os
import time
import json
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify

# 导入主程序中的配置和函数
from main import (
    logger, 
    CONFIG,
    TIMEZONE,
    VERSION,
    load_config,
    save_config,
    HOSTS_FILE,
    UPDATE_HISTORY_FILE,
    SPEEDTEST_RESULT,
    update_all_hosts,
    run_cloudflare_speedtest,
    parse_speedtest_results,
    generate_hosts_content,
    save_hosts_file,
    update_container_hosts,
    HOSTS_MARKER,
    CF_DOMAINS,
    save_update_history
)

app = Flask(__name__)

# 配置
WEB_PORT = int(os.environ.get('WEB_PORT', '8080'))

# 读取环境变量并返回字典
def get_config():
    # 获取最新配置
    config = load_config()
    
    # 将列表类型转换为逗号分隔的字符串，方便前端显示
    result = {
        'UPDATE_INTERVAL': config['UPDATE_INTERVAL'],
        'TARGET_CONTAINERS': ','.join(config['TARGET_CONTAINERS']) if isinstance(config['TARGET_CONTAINERS'], list) else config['TARGET_CONTAINERS'],
        'CF_DOMAINS': ','.join(config['CF_DOMAINS']) if isinstance(config['CF_DOMAINS'], list) else config['CF_DOMAINS'],
        'IP_COUNT': config['IP_COUNT'],
        'PREFERRED_IP': config['PREFERRED_IP'],
        'SPEED_TEST_ARGS': config['SPEED_TEST_ARGS']
    }
    
    return result

# 保存配置（通过调用main.py中的save_config函数）
def update_configuration(config_data):
    # 准备配置数据
    config = {
        'UPDATE_INTERVAL': config_data.get('UPDATE_INTERVAL', CONFIG['UPDATE_INTERVAL']),
        'TARGET_CONTAINERS': config_data.get('TARGET_CONTAINERS', ','.join(CONFIG['TARGET_CONTAINERS']) if isinstance(CONFIG['TARGET_CONTAINERS'], list) else CONFIG['TARGET_CONTAINERS']),
        'CF_DOMAINS': config_data.get('CF_DOMAINS', ','.join(CONFIG['CF_DOMAINS']) if isinstance(CONFIG['CF_DOMAINS'], list) else CONFIG['CF_DOMAINS']),
        'IP_COUNT': int(config_data.get('IP_COUNT', CONFIG['IP_COUNT'])),
        'PREFERRED_IP': config_data.get('PREFERRED_IP', CONFIG['PREFERRED_IP']),
        'SPEED_TEST_ARGS': config_data.get('SPEED_TEST_ARGS', CONFIG['SPEED_TEST_ARGS'])
    }
    
    # 保存到config.toml
    success = save_config(config)
    
    if success:
        logger.info("通过Web界面更新了配置")
    else:
        logger.error("通过Web界面更新配置失败")
    
    return success

# 获取日志
def get_logs(lines=50):
    log_path = '/app/data/updater.log'
    if os.path.exists(log_path):
        try:
            result = subprocess.run(['tail', '-n', str(lines), log_path], 
                                   capture_output=True, text=True)
            return result.stdout
        except Exception as e:
            return f"读取日志出错: {str(e)}"
    return "日志文件不存在"

# 获取当前使用的IP
def get_current_ips():
    try:
        if os.path.exists(HOSTS_FILE):
            with open(HOSTS_FILE, 'r') as f:
                content = f.read()
                # 改进hosts文件解析逻辑
                ips = {}
                for line in content.splitlines():
                    # 跳过注释行或空行
                    if not line or line.startswith('#'):
                        continue
                    
                    # 必须包含IP地址（第一部分）和域名（第二部分）
                    parts = line.split()
                    if len(parts) >= 2:
                        # 第一部分是IP地址
                        ip = parts[0]
                        # 第二部分是域名
                        domain = parts[1]
                        
                        # 验证IP格式（简单检查）
                        if all(part.isdigit() for part in ip.split('.')):
                            ips[domain] = ip
                return ips
        return {}
    except Exception as e:
        logger.error(f"获取当前IP出错: {str(e)}")
        return {}

# 获取容器状态
def get_container_status():
    # 获取最新配置中的容器列表
    config = load_config()
    target_containers = config['TARGET_CONTAINERS']
    
    containers = []
    for container in target_containers:
        if not container:
            continue
        try:
            # 检查容器是否存在
            result = subprocess.run(['docker', 'inspect', container], 
                                    capture_output=True, text=True)
            exists = result.returncode == 0
            
            # 获取容器hosts文件内容
            hosts_content = ""
            if exists:
                hosts_cmd = f"docker exec {container} cat /etc/hosts"
                result = subprocess.run(hosts_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    hosts_content = result.stdout
            
            containers.append({
                'name': container,
                'exists': exists,
                'hosts': hosts_content
            })
        except Exception as e:
            containers.append({
                'name': container,
                'exists': False,
                'error': str(e)
            })
    return containers

# 获取更新历史
def get_update_history():
    """获取更新历史记录"""
    try:
        if os.path.exists(UPDATE_HISTORY_FILE):
            with open(UPDATE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
            return history
        return []
    except Exception as e:
        logger.error(f"读取更新历史失败: {str(e)}")
        return []

# 路由
@app.route('/')
def index():
    data = {
        'config': get_config(),
        'logs': get_logs(),
        'current_ips': get_current_ips(),
        'containers': get_container_status(),
        'last_update': get_last_update_time(),
        'version': VERSION,
        'update_history': get_update_history()
    }
    return render_template('index.html', data=data)

# 获取最后更新时间
def get_last_update_time():
    try:
        if os.path.exists(HOSTS_FILE):
            mtime = os.path.getmtime(HOSTS_FILE)
            # 使用上海时区
            update_time = datetime.fromtimestamp(mtime, TIMEZONE)
            # 确保时间显示为上海时区
            return update_time.astimezone(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        return "未知"
    except Exception as e:
        logger.error(f"获取最后更新时间出错: {str(e)}")
        return "获取时间出错"

# 更新配置
@app.route('/update_config', methods=['POST'])
def update_config():
    config = {
        'UPDATE_INTERVAL': request.form.get('UPDATE_INTERVAL'),
        'TARGET_CONTAINERS': request.form.get('TARGET_CONTAINERS'),
        'CF_DOMAINS': request.form.get('CF_DOMAINS'),
        'IP_COUNT': int(request.form.get('IP_COUNT', 3)),
        'PREFERRED_IP': request.form.get('PREFERRED_IP', ''),
        'SPEED_TEST_ARGS': request.form.get('SPEED_TEST_ARGS', '')
    }
    
    success = update_configuration(config)
    
    # 配置更新后立即更新hosts文件
    if success:
        try:
            # 不运行测速，直接使用已有结果更新hosts
            logger.info("配置已更新，使用现有测速结果更新hosts文件")
            
            # 获取最新的配置
            config = load_config()
            # 获取最新的域名配置
            new_domains = config['CF_DOMAINS']
            
            # 直接解析结果文件，不运行测速
            ip_list = parse_speedtest_results()
            if ip_list:
                # 使用最新配置中的域名生成hosts内容
                hosts_content = generate_hosts_content(ip_list, domains=new_domains)
                if hosts_content:
                    save_hosts_file(hosts_content)
                    # 更新容器
                    for container in config['TARGET_CONTAINERS']:
                        if container:
                            update_container_hosts(container, hosts_content)
            time.sleep(1)  # 添加短暂延迟，确保文件更新完成
        except Exception as e:
            logger.error(f"更新配置后更新hosts文件失败: {str(e)}")
    
    return redirect(url_for('index'))

# 手动触发测速
@app.route('/run_speedtest', methods=['POST'])
def trigger_speedtest():
    try:
        # 获取最新配置
        config = load_config()
        domains = config['CF_DOMAINS']
        
        # 保留原有功能 - 运行测速并更新hosts
        success = run_cloudflare_speedtest()
        if success:
            ip_list = parse_speedtest_results()
            if ip_list:
                # 使用最新域名配置
                hosts_content = generate_hosts_content(ip_list, domains=domains)
                if hosts_content:
                    save_hosts_file(hosts_content)
                    # 更新容器
                    for container in config['TARGET_CONTAINERS']:
                        if container:
                            update_container_hosts(container, hosts_content)
                    # 记录更新历史
                    save_update_history(ip_list, False)  # False表示非定时任务
            return jsonify({'success': True, 'message': 'IP优选完成，并已更新hosts'})
        else:
            return jsonify({'success': False, 'message': 'IP优选失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'IP优选出错: {str(e)}'})

@app.route('/update_hosts', methods=['POST'])
def update_hosts_only():
    try:
        # 获取最新配置
        config = load_config()
        domains = config['CF_DOMAINS']
        
        # 直接解析结果文件，不运行测速
        ip_list = parse_speedtest_results()
        if ip_list:
            # 使用最新域名配置
            hosts_content = generate_hosts_content(ip_list, domains=domains)
            if hosts_content:
                save_hosts_file(hosts_content)
                # 更新容器
                for container in config['TARGET_CONTAINERS']:
                    if container:
                        update_container_hosts(container, hosts_content)
                # 记录更新历史
                save_update_history(ip_list, False)  # False表示非定时任务
            return jsonify({'success': True, 'message': 'hosts文件已更新'})
        else:
            logger.error("无法从result.csv获取IP列表")
            return jsonify({'success': False, 'message': "无法从result.csv获取IP列表"})
    except Exception as e:
        logger.error(f"更新hosts出错: {str(e)}")
        return jsonify({'success': False, 'message': f"更新hosts出错: {str(e)}"})

# 获取最新日志
@app.route('/api/logs')
def api_logs():
    lines = request.args.get('lines', 50, type=int)
    return jsonify({'logs': get_logs(lines)})

# 启动Web服务器
def start_web_server():
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)

if __name__ == '__main__':
    start_web_server() 