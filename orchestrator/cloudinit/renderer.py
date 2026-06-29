"""Cloud-init user-data rendering."""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class CloudInitParams:
    gateway_name: str
    wg_private_key: str
    wg_gateway_ip: str
    wg_subnet: str
    wg_listen_port: int
    headscale_url: str
    tailscale_auth_key: str
    agent_token: str
    orch_allowed_ip: str
    vm_ip: str
    agent_port: int
    gateway_agent_wheel_url: str = ""
    use_golden_image: bool = False
    net_interface: str = "eth0"


def render_user_data(params: CloudInitParams) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template_name = (
        "user-data-golden.yaml.j2" if params.use_golden_image else "user-data.yaml.j2"
    )
    template = env.get_template(template_name)
    return template.render(**params.__dict__)


def render_openwrt_setup(params: CloudInitParams) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(default=False),
        # Heredoc terminators must stay on their own line; trim_blocks merges them into includes.
        trim_blocks=False,
        lstrip_blocks=False,
    )
    return env.get_template("openwrt-setup.sh.j2").render(**params.__dict__)
