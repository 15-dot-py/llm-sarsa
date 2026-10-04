"""Share only configured HTTP addresses; distinguish LAN sharing from public hosting."""
import ipaddress
import os
import socket
from urllib.parse import urlsplit

def usable_address(url):
    try:
        parsed=urlsplit(url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password: return False
        if parsed.hostname.lower() in {'localhost','0.0.0.0'}: return False
        try:
            addr=ipaddress.ip_address(parsed.hostname)
            return not (addr.is_loopback or addr.is_link_local or addr.is_unspecified)
        except ValueError: return True
    except ValueError: return False

def access_info():
    configured=os.getenv('PUBLIC_BASE_URL','').strip().rstrip('/')
    rendered=os.getenv('RENDER_EXTERNAL_URL','').strip().rstrip('/')
    host=os.getenv('HOST','127.0.0.1')
    port=int(os.getenv('PORT','8000'))
    lan_ip=os.getenv('LAN_ADDRESS','').strip()
    if not lan_ip:
        try:
            addresses=[x[4][0] for x in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)]
            lan_ip=next((x for x in addresses if ipaddress.ip_address(x).is_private and usable_address('http://'+x)), '')
        except (OSError,ValueError): pass
    lan_url=f'http://{lan_ip}:{port}' if lan_ip and host=='0.0.0.0' else None
    share_url=next((url for url in [configured,rendered,lan_url] if url and usable_address(url)),None)
    mode='unavailable'
    if share_url:
        try: mode='lan' if ipaddress.ip_address(urlsplit(share_url).hostname).is_private else 'public'
        except ValueError: mode='public'
    return {'mode':mode,'share_url':share_url,'lan_url':lan_url,
            'local_url':f'http://127.0.0.1:{port}',
            'description':'同一 Wi-Fi 下使用，电脑须保持运行；路由器与系统防火墙需允许连接。' if mode=='lan' else
                          '使用实际托管地址；网页、数据库和模型由服务器提供。' if mode=='public' else
                          '当前只监听本机。使用“手机共享启动.cmd”启动局域网服务，或完成公网发布。'}
