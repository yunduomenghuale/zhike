"""预置 7 个计算机网络虚拟仿真实验模板（对应实验平台静态页）。"""
from django.core.management.base import BaseCommand

from apps.labs.models import LabTemplate

TEMPLATES = [
    {
        "code": "switch-vlan-stp-lab",
        "title": "实验一：交换机基础配置与VLAN/STP实验",
        "description": "使用华为命令完成交换机基础配置、VLAN 划分与生成树协议观察。",
        "default_standard_minutes": 30,
        "random_config": {"ranges": {"vlan_id": [10, 99]}},
        "order": 1,
    },
    {
        "code": "arp-ip-lab",
        "title": "实验二：ARP与IP子网综合实验",
        "description": "观察 ARP 解析过程，完成 IP 子网划分与跨网段通信验证。",
        "default_standard_minutes": 30,
        "random_config": {"ranges": {"s1": [1, 9], "s2": [1, 9]}},
        "order": 2,
    },
    {
        "code": "routing-ospf-lab",
        "title": "实验三：路由器基础与OSPF动态路由实验",
        "description": "配置路由器接口与 OSPF 动态路由，观察路由表收敛过程。",
        "default_standard_minutes": 35,
        "random_config": {"ranges": {"area": [0, 9], "s1": [1, 9]}},
        "order": 3,
    },
    {
        "code": "vlan-nat-lab",
        "title": "实验四：VLAN间通信与NAT地址转换实验",
        "description": "实现 VLAN 间路由，配置 NAT 完成私网到公网的地址转换。",
        "default_standard_minutes": 35,
        "random_config": {"ranges": {"s1": [1, 9], "s2": [1, 9]}},
        "order": 4,
    },
    {
        "code": "tcp-udp-lab",
        "title": "实验五：传输层TCP/UDP协议分析实验",
        "description": "通过抓包与连接模拟观察 TCP 三次握手、四次挥手与 UDP 无连接传输。",
        "default_standard_minutes": 30,
        "random_config": {"ranges": {"port": [1024, 65535]}},
        "order": 5,
    },
    {
        "code": "app-layer-lab",
        "title": "实验六：应用层协议（DNS/DHCP/HTTP）实验",
        "description": "模拟 DNS 解析、DHCP 地址分配与 HTTP 请求响应全流程。",
        "default_standard_minutes": 30,
        "random_config": {"ranges": {"s1": [1, 9]}},
        "order": 6,
    },
    {
        "code": "comprehensive-lab",
        "title": "实验七：综合组网实验",
        "description": "综合运用 VLAN、路由、NAT、DHCP 等技术完成中小型校园网组网。",
        "default_standard_minutes": 45,
        "random_config": {"ranges": {"s1": [1, 9], "s2": [1, 9], "vlan_id": [10, 99]}},
        "order": 7,
    },
]


class Command(BaseCommand):
    help = "预置 7 个虚拟仿真实验模板（幂等，可重复执行）"

    def handle(self, *args, **options):
        created = 0
        for item in TEMPLATES:
            obj, was_created = LabTemplate.objects.update_or_create(
                code=item["code"],
                defaults={k: v for k, v in item.items() if k != "code"},
            )
            created += 1 if was_created else 0
        self.stdout.write(self.style.SUCCESS(f"实验模板就绪：共 {created} 个新建，{len(TEMPLATES)} 个在库"))
